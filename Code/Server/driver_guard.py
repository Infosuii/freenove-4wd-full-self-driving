"""Opt-in bounded CMD_MOTOR ownership. No GPIO dependencies; monotonic deadlines.

Only this object writes motors in --ai-safe mode. Polling telemetry never renews
a movement lease. The original raw motor scale (0.8) is preserved.
"""
import logging
import math
import secrets
import threading
import time

log = logging.getLogger(__name__)


class DriverGuard:
    def __init__(self, motor, send, clock=time.monotonic, watchdog=1.0,
                 max_duration=0.75, threshold=30.0, sensor_age=0.5):
        if not (0 < max_duration <= watchdog <= 2 and 0 < threshold < 300
                and 0 < sensor_age <= 1):
            raise ValueError("Invalid Pi safety limits")
        self.motor, self.send, self.clock = motor, send, clock
        self.watchdog, self.max_duration = watchdog, max_duration
        self.threshold, self.sensor_age = threshold, sensor_age
        self.lock = threading.RLock()
        self.owner = self.token = None
        self.sequence = 0
        self.distance, self.sample_time = None, 0.0
        self.duties = (0, 0, 0, 0)
        self.deadline = self.communication_deadline = None
        self.hardware_fault = False
        self.closed = threading.Event()
        self.worker = None

    def start(self):
        self.closed.clear()
        self.stop("startup")
        self.worker = threading.Thread(target=self._watch, daemon=True, name="pi-watchdog")
        self.worker.start()

    def _watch(self):
        while not self.closed.wait(0.01):
            try:
                self.tick()
            except Exception:
                log.exception("watchdog motor failure")
                # Fault remains latched; keep attempting zero outputs.

    def _write(self, duties):
        try:
            self.motor.set_motor_model(*duties)
        except Exception:
            self.hardware_fault = True
            raise
        self.duties = duties

    def stop(self, reason, notify=False):
        with self.lock:
            self.deadline = self.communication_deadline = None
            self._write((0, 0, 0, 0))
            log.info("motor_stop reason=%s", reason)
            if notify and self.owner is not None:
                self.send(f"CMD_DRIVER#STOPPED#{reason}#{self.sequence}\n", self.owner)

    def disconnect(self, address):
        with self.lock:
            if address == self.owner:
                self.owner = self.token = None
                self.stop("disconnected")

    def update_distance(self, distance, sampled_at=None):
        with self.lock:
            self.distance = distance
            self.sample_time = self.clock() if sampled_at is None else sampled_at
            self.tick()

    def sensor_valid(self):
        return (type(self.distance) in (int, float) and math.isfinite(self.distance)
                and 0 < self.distance <= 300
                and 0 <= self.clock() - self.sample_time <= self.sensor_age)

    def tick(self):
        with self.lock:
            if self.hardware_fault:
                self.stop("hardware_fault")
            elif any(self.duties):
                if not self.sensor_valid():
                    self.stop("ultrasonic_unavailable", True)
                elif sum(self.duties) > 0 and self.distance <= self.threshold:
                    self.stop("obstacle", True)
                elif self.clock() >= self.communication_deadline:
                    self.stop("watchdog", True)
                elif self.clock() >= self.deadline:
                    self.stop("completed", True)

    def handle(self, line, address):
        """Consume a complete line. Strict parsing is isolated from legacy parser."""
        with self.lock:
            if self.closed.is_set():
                self.stop("server_closed")
                return
            try:
                parts = line.strip().split("#")
                if parts == ["CMD_MOTOR", "0", "0", "0", "0"] or parts in (
                        ["CMD_MODE", "one"], ["CMD_MODE", "0"]):
                    self.stop("requested", True)
                elif parts == ["CMD_DRIVER", "HELLO", "1"]:
                    self.stop("new_session")
                    self.owner, self.token = address, secrets.token_hex(8)
                    self.sequence = 0
                    self.send(f"CMD_DRIVER#READY#1#{self.token}#{self.watchdog}#"
                              f"{self.max_duration}#{self.threshold}\n", address)
                elif parts == ["CMD_SONIC"]:
                    value = self.distance if self.sensor_valid() else float("nan")
                    self.send(f"CMD_MODE#3#{value}\n", address)
                elif len(parts) == 8 and parts[0] == "CMD_MOTOR":
                    duties = tuple(int(p) for p in parts[1:5])
                    milliseconds, sequence = int(parts[5]), int(parts[7])
                    if (address != self.owner or parts[6] != self.token
                            or sequence <= self.sequence):
                        raise ValueError("invalid_session_or_sequence")
                    if (not 1 <= milliseconds <= int(self.max_duration * 1000)
                            or any(abs(d) > 1500 for d in duties)):
                        raise ValueError("motor_limits")
                    if self.hardware_fault:
                        raise ValueError("hardware_fault")
                    if not self.sensor_valid():
                        raise ValueError("ultrasonic_unavailable")
                    if sum(duties) > 0 and self.distance <= self.threshold:
                        raise ValueError("obstacle")
                    if any(self.duties):
                        raise ValueError("action_already_running")
                    self.sequence = sequence
                    now = self.clock()
                    self.deadline = now + milliseconds / 1000
                    self.communication_deadline = now + self.watchdog
                    self._write(tuple(int(round(d * 0.8)) for d in duties))
                    log.info("motor_start seq=%s duties=%s duration_ms=%s", sequence, duties, milliseconds)
                    self.send(f"CMD_DRIVER#ACTING#{sequence}\n", address)
                else:
                    # Includes servo commands and legacy autonomous/rotation modes.
                    raise ValueError("unsupported_in_guarded_mode")
            except (ValueError, OverflowError) as exc:
                self.stop(str(exc))
                log.warning("command_rejected reason=%s", exc)
                self.send(f"CMD_DRIVER#ERROR#{exc}\n", address)
            except Exception:
                log.exception("guard internal failure")
                self.stop("internal_error")
                raise

    def close(self):
        self.closed.set()
        with self.lock:
            self.owner = self.token = None
            self.stop("shutdown")
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(0.5)
