"""Single movement arbiter; emergency/collision/fault/watchdog outrank callers."""
from collections import deque
from dataclasses import asdict, dataclass
import json
import logging
import threading
import time
from .actions import Decision, validate
from .state import Mode, Phase, StateMachine

log = logging.getLogger(__name__)
PRIORITY = ("emergency", "collision", "hardware", "watchdog", "manual", "autonomous", "objective")


@dataclass
class Execution:
    action: str
    started: float
    deadline: float
    state: str = "running"
    reason: str = ""


class Controller:
    def __init__(self, client, config, clock=time.monotonic):
        self.client, self.config, self.clock = client, config, clock
        self.lock = threading.RLock()
        self.emergency = threading.Event()
        self.closed = threading.Event()
        self.mode = Mode.MANUAL
        self.machine = StateMachine()
        self.epoch = 0
        self.execution = None
        self.history = deque(maxlen=config.history_size)
        self.status = "Ready to connect"
        self.objective = ""
        self.hardware_fault = False
        self.gui_heartbeat = None
        self.worker = None
        client.on_event = self.network_event

    def start(self):
        self.worker = threading.Thread(target=self._monitor, name="safety-controller", daemon=True)
        self.worker.start()

    def _monitor(self):
        while not self.closed.wait(0.02):
            try:
                self.tick()
            except Exception as exc:
                log.exception("controller internal failure")
                self.fail(f"Internal controller error: {exc}", Phase.SAFETY_STOP)

    def pulse(self):
        self.gui_heartbeat = self.clock()

    def _stop_wire(self):
        try:
            self.client.stop()
        except Exception as exc:
            log.warning("STOP transmission failed; Pi lease remains bounded: %s", exc)

    def _finish(self, state, reason):
        if self.execution and self.execution.state == "running":
            self.execution.state, self.execution.reason = state, reason
            self.history.append(dict(action=self.execution.action, outcome=state, reason=reason[:240]))
        self._stop_wire()

    def stop(self, reason="Manual STOP"):
        with self.lock:
            self.epoch += 1
            self.mode = Mode.EMERGENCY_STOP if self.emergency.is_set() else Mode.MANUAL
            self._finish("cancelled", reason)
            self.machine.transition(Phase.EMERGENCY_STOP if self.emergency.is_set() else Phase.MANUAL)
            self.status = reason
            log.info("control_stop mode=%s reason=%s epoch=%s", self.mode.value, reason, self.epoch)

    def emergency_stop(self):
        self.emergency.set()  # Priority flag precedes lock acquisition/network I/O.
        self.stop("EMERGENCY STOP — reset required")

    def reset_emergency(self):
        with self.lock:
            self._finish("cancelled", "Emergency reset")
            self.epoch += 1
            self.emergency.clear()
            self.mode = Mode.MANUAL
            self.machine.transition(Phase.MANUAL, recovery=True)
            self.status = "Emergency reset; MANUAL — AI requires Start"

    def fail(self, reason, phase=Phase.SAFETY_STOP):
        with self.lock:
            self.epoch += 1
            self._finish("interrupted", reason)
            if self.emergency.is_set():
                self.mode = Mode.EMERGENCY_STOP
                self.machine.transition(Phase.EMERGENCY_STOP)
            else:
                self.mode = Mode.MANUAL
                self.machine.transition(phase)
            self.status = reason
            log.warning("safety_stop phase=%s reason=%s", self.machine.phase.value, reason)

    def safety_reason(self, action, source="ai", epoch=None):
        """Ordered deterministic authority; no writes. Caller holds arbiter lock."""
        state = self.client.snapshot()
        now = self.clock()
        if self.emergency.is_set() or self.mode == Mode.EMERGENCY_STOP:
            return "emergency: reset required"
        distance = state["distance"]
        if distance is None or not 0 <= now - state["distance_time"] <= self.config.sensor_max_age:
            return "collision: Ultrasonic safety sensor unavailable"
        # Sources normally normalize distance; defend the boundary again.
        from .protocol import distance_value
        if distance_value(distance) is None:
            return "collision: Ultrasonic safety sensor unavailable"
        if action == "FORWARD" and distance <= self.config.ultrasonic_threshold:
            return "collision: Obstacle inside forward safety threshold"
        if self.hardware_fault:
            return "hardware: fault latched"
        if not self.client.frames.get(self.config.frame_max_age) or not state["video_connected"]:
            return "hardware: Camera unavailable or stale"
        if (not state["ready"] or not 0 <= now - state["last_reply"] <= self.config.watchdog_timeout
                or self.gui_heartbeat is not None and now - self.gui_heartbeat > self.config.watchdog_timeout):
            return "watchdog: Connection or GUI heartbeat unavailable"
        if self.mode not in (Mode.MANUAL, Mode.AUTONOMOUS):
            return "autonomous: Unexpected controller mode"
        if source == "ai" and (self.mode != Mode.AUTONOMOUS or epoch != self.epoch):
            return "manual: AI command superseded by operator"
        return None

    def start_ai(self, objective):
        with self.lock:
            if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 1000:
                raise ValueError("Enter an objective of 1–1000 characters")
            self.stop("AI starting from STOP")
            reason = self.safety_reason("STOP", "manual")
            if reason:
                self.fail(reason)
                raise ValueError(reason)
            self.objective = objective.strip()
            self.mode = Mode.AUTONOMOUS
            self.machine.transition(Phase.AI_STARTING)
            self.status = "AI starting"
            return self.epoch

    def phase(self, phase, epoch):
        with self.lock:
            if self.active(epoch):
                self.machine.transition(phase)

    def active(self, epoch):
        return (not self.closed.is_set() and not self.emergency.is_set()
                and self.mode == Mode.AUTONOMOUS and epoch == self.epoch)

    def manual(self, action):
        with self.lock:
            self.stop("Manual override")
            if action == "STOP":
                return True
            return self.submit(Decision(action, self.config.manual_duration, 1, "Manual control", False), "manual")

    def submit(self, decision, source="ai", epoch=None):
        with self.lock:
            try:
                decision = validate(json.dumps(asdict(decision)), self.config.max_action_duration)
            except Exception as exc:
                self.fail(f"Invalid command: {exc}", Phase.AI_ERROR)
                return False
            reason = self.safety_reason(decision.action, source, epoch)
            if reason:
                # An obsolete AI response must not cancel a newer manual action.
                if reason.startswith("manual:"):
                    log.info("rejected stale AI command epoch=%s", epoch)
                    return False
                self.fail(reason)
                return False
            if decision.action != "STOP" and decision.confidence < self.config.min_confidence:
                self.fail("autonomous: Low-confidence decision; remain stopped")
                return False
            if self.execution and self.execution.state == "running":
                log.warning("Rejected overlapping action")
                return False
            self.status = decision.status
            log.info("approved_decision source=%s action=%s duration=%.3f confidence=%.2f goal=%s status=%s",
                     source, decision.action, decision.duration, decision.confidence, decision.goal_reached, decision.status)
            if decision.action == "STOP":
                self._stop_wire()
                self.history.append(dict(action="STOP", outcome="completed", reason=decision.status))
                if decision.goal_reached:
                    self.stop("Goal reported reached: " + decision.status)
                return True
            if self.emergency.is_set():
                return False
            now = self.clock()
            self.execution = Execution(decision.action, now, now + decision.duration)
            try:
                self.client.move(decision.action, decision.duration)
            except Exception as exc:
                self.fail(f"Command failed: {exc}", Phase.CONNECTION_ERROR)
                return False
            if source == "ai":
                self.machine.transition(Phase.AI_INSPECTING if decision.action.startswith("ROTATE") else Phase.AI_ACTING)
            log.info("action_start source=%s action=%s duration=%.3f", source, decision.action, decision.duration)
            return True

    def tick(self):
        with self.lock:
            running = self.execution and self.execution.state == "running"
            if running or self.mode == Mode.AUTONOMOUS:
                action = self.execution.action if running else "STOP"
                reason = self.safety_reason(action, "ai" if self.mode == Mode.AUTONOMOUS else "manual", self.epoch)
                if reason:
                    self.fail(reason)
                elif running and self.clock() >= self.execution.deadline:
                    self._finish("completed", "Bounded action completed")
                    if self.mode == Mode.AUTONOMOUS:
                        self.machine.transition(Phase.AI_OBSERVING)

    def network_event(self, kind, value):
        if self.closed.is_set():
            return
        if kind in ("disconnected", "video_disconnected"):
            self.fail(str(value), Phase.CONNECTION_ERROR)
        elif kind == "error" or kind == "stopped" and value not in ("requested", "completed"):
            self.fail("Pi safety: " + str(value))
        elif kind == "distance":
            self.tick()
        elif kind == "ready":
            self.stop("Pi connected; MANUAL — explicit AI Start required")

    def snapshot(self):
        with self.lock:
            return dict(mode=self.mode.value, phase=self.machine.phase.value, status=self.status,
                        action=self.execution.action if self.execution and self.execution.state == "running" else "STOP",
                        history=list(self.history), objective=self.objective,
                        safety="emergency" if self.emergency.is_set() else self.status,
                        execution=asdict(self.execution) if self.execution else None)

    def close(self):
        self.stop("Application shutdown")
        self.closed.set()
        if self.worker:
            self.worker.join(0.5)
