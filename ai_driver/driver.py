import logging
import queue
import threading
import time
from .actions import validate
from .state import Phase, oscillating

log = logging.getLogger(__name__)


class AIDriver:
    def __init__(self, controller, ollama):
        self.controller, self.ollama = controller, ollama
        self.config = controller.config
        self.worker = None
        self.inference = None
        self.cancel = threading.Event()
        self.lock = threading.Lock()

    def start(self, objective):
        with self.lock:
            if self.worker and self.worker.is_alive() or self.inference and self.inference.is_alive():
                raise ValueError("Previous AI request is still finishing; wait before restarting")
            if not self.ollama.verified:
                self.controller.stop("Ollama unavailable; run Test Ollama")
                raise ValueError("Test Ollama successfully before starting AI")
            epoch = self.controller.start_ai(objective)
            self.cancel = threading.Event()
            self.worker = threading.Thread(target=self._run, args=(epoch,), name="ai-loop", daemon=True)
            self.worker.start()
            log.info("AI started epoch=%s", epoch)

    def stop(self):
        self.cancel.set()
        self.controller.stop("AI OFF / manual STOP")

    def _active(self, epoch):
        return not self.cancel.is_set() and self.controller.active(epoch)

    def _infer(self, observation, jpeg, epoch):
        result = queue.Queue(maxsize=1)

        def request():
            try:
                result.put((True, self.ollama.decide(observation, jpeg)))
            except Exception as exc:
                result.put((False, exc))

        self.inference = threading.Thread(target=request, name="ollama-inference", daemon=True)
        self.inference.start()
        deadline = time.monotonic() + self.config.inference_timeout
        while self._active(epoch):
            try:
                ok, response = result.get(timeout=0.02)
                if not ok:
                    raise response
                return response
            except queue.Empty:
                if time.monotonic() >= deadline:
                    self.ollama.verified = False
                    raise TimeoutError("Ollama inference timed out; remaining stopped")
        return None

    def _observe(self, after, epoch):
        deadline = time.monotonic() + self.config.frame_max_age + self.config.settle_time
        while self._active(epoch):
            frame = self.controller.client.frames.get(self.config.frame_max_age, after)
            if frame:
                state = self.controller.snapshot()
                net = self.controller.client.snapshot()
                with self.controller.lock:
                    reason = self.controller.safety_reason("STOP", "ai", epoch)
                if reason:
                    raise ValueError(reason)
                history = state["history"]
                observation = dict(objective=state["objective"], mode=state["mode"],
                                   current_action=state["action"], recent_actions=history,
                                   ultrasonic_cm=net["distance"], connected=net["ready"],
                                   safety=state["safety"], frame_sequence=frame.sequence,
                                   max_duration=self.config.max_action_duration,
                                   min_confidence=self.config.min_confidence,
                                   reassess=oscillating(history))
                log.info("observation frame=%s age_s=%.3f distance_cm=%s mode=%s history_count=%s reassess=%s",
                         frame.sequence, self.controller.clock() - frame.received_at,
                         net["distance"], state["mode"], len(history), observation["reassess"])
                return observation, frame
            if time.monotonic() >= deadline:
                raise ValueError("Camera did not deliver a fresh post-action observation")
            self.cancel.wait(0.02)
        return None

    def _run(self, epoch):
        last_reassessment = -1
        try:
            if not self.controller.client.wait_stopped():
                raise ValueError("Pi did not acknowledge startup STOP")
            after = self.controller.clock() + self.config.settle_time
            while self._active(epoch):
                self.controller.phase(Phase.AI_OBSERVING, epoch)
                observed = self._observe(after, epoch)
                if observed is None:
                    break
                observation, frame = observed
                self.controller.phase(Phase.AI_DECIDING, epoch)
                raw = self._infer(observation, frame.jpeg, epoch)
                if raw is None or not self._active(epoch):
                    break
                if self.controller.clock() - frame.received_at > self.config.decision_max_age:
                    raise ValueError("AI decision observation expired")
                decision = validate(raw, self.config.max_action_duration)
                if observation["reassess"]:
                    # Stop a cycle of repeated failed strategies. The model chooses
                    # a purposeful inspection, never an invented/random rotation.
                    if decision.action not in ("STOP", "ROTATE_LEFT", "ROTATE_RIGHT"):
                        raise ValueError("Repeated/oscillating actions: stopped; restart with a new strategy")
                    if last_reassessment == len(observation["recent_actions"]):
                        raise ValueError("Reassessment made no progress; operator review required")
                    last_reassessment = len(observation["recent_actions"])
                if not self.controller.submit(decision, "ai", epoch):
                    break
                while self._active(epoch):
                    self.controller.tick()
                    execution = self.controller.snapshot()["execution"]
                    if not execution or execution["state"] != "running":
                        break
                    self.cancel.wait(0.01)
                if self._active(epoch) and not self.controller.client.wait_stopped():
                    raise ValueError("Pi did not acknowledge STOP after action")
                after = self.controller.clock() + self.config.settle_time
                self.cancel.wait(self.config.loop_interval)
        except Exception as exc:
            log.exception("AI cycle failed")
            if self._active(epoch):
                self.controller.fail(f"AI error: {exc}", Phase.AI_ERROR)
        finally:
            if self._active(epoch):
                self.controller.stop("AI finished")
            log.info("AI loop exited epoch=%s", epoch)

    def close(self):
        self.stop()
        if self.worker:
            self.worker.join(0.5)
