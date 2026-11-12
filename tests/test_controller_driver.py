from dataclasses import replace
import threading
import time
import unittest
from unittest.mock import Mock
from ai_driver.actions import Decision, validate
from ai_driver.config import Config
from ai_driver.controller import Controller, PRIORITY
from ai_driver.driver import AIDriver
from ai_driver.protocol import STOP, motor_command, SIGNS
from ai_driver.state import Mode, Phase, StateMachine, NEXT, INTERRUPTS, oscillating
from ai_driver.app import Runtime
from tests.helpers import Clock, FakeClient, FreshFeed, response, wait_until


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.config = Config()
        self.client = FakeClient(self.config, self.clock)
        self.controller = Controller(self.client, self.config, self.clock)
        self.decision = validate(response(duration=0.3), 0.75)

    def ai_ready(self):
        epoch = self.controller.start_ai("Find the doorway")
        self.controller.phase(Phase.AI_OBSERVING, epoch)
        self.controller.phase(Phase.AI_DECIDING, epoch)
        return epoch

    def test_manual_each_control_constructs_exact_wire(self):
        for action in SIGNS:
            with self.subTest(action=action):
                self.assertTrue(self.controller.manual(action))
                expected = motor_command(action, 1200, 0.35, "0123456789abcdef", self.client.sequence)
                self.assertEqual(self.client.wire[-1], expected)
                if action != "STOP":
                    self.assertEqual(self.client.wire[-2], STOP)

    def test_each_safety_condition_independently_blocks_motor_transport(self):
        cases = {
            "emergency": lambda: self.controller.emergency.set(),
            "obstacle": lambda: self.client.data.update(distance=10),
            "missing_sensor": lambda: self.client.data.update(distance=None),
            "negative_sensor": lambda: self.client.data.update(distance=-1),
            "nan_sensor": lambda: self.client.data.update(distance=float("nan")),
            "huge_sensor": lambda: self.client.data.update(distance=301),
            "stale_sensor": lambda: self.client.data.update(distance_time=self.clock() - 1),
            "missing_camera": lambda: self.client.frames.clear(),
            "stale_camera": lambda: setattr(self.client.frames, "frame", replace(self.client.frames.frame, received_at=self.clock() - 2)),
            "video_down": lambda: self.client.data.update(video_connected=False),
            "hardware_fault": lambda: setattr(self.controller, "hardware_fault", True),
            "disconnected": lambda: self.client.data.update(ready=False),
            "communication_gap": lambda: self.client.data.update(last_reply=self.clock() - 2),
            "gui_hung": lambda: setattr(self.controller, "gui_heartbeat", self.clock() - 2),
            "unknown_mode": lambda: setattr(self.controller, "mode", "BROKEN"),
        }
        for name, induce in cases.items():
            with self.subTest(name=name):
                self.setUp()
                epoch = self.ai_ready()
                induce()
                self.assertFalse(self.controller.submit(self.decision, epoch=epoch))
                self.assertEqual(self.client.moves, [])
                self.assertEqual(self.client.wire[-1], STOP)

    def test_explicit_priority_order_under_simultaneous_faults(self):
        self.assertEqual(PRIORITY, ("emergency", "collision", "hardware", "watchdog", "manual", "autonomous", "objective"))
        self.controller.emergency.set()
        self.client.data.update(distance=5, ready=False)
        self.controller.hardware_fault = True
        self.assertTrue(self.controller.safety_reason("FORWARD").startswith("emergency:"))
        self.controller.emergency.clear()
        self.assertTrue(self.controller.safety_reason("FORWARD").startswith("collision:"))
        self.client.data.update(distance=100)
        self.assertTrue(self.controller.safety_reason("FORWARD").startswith("hardware:"))
        self.controller.hardware_fault = False
        self.assertTrue(self.controller.safety_reason("FORWARD").startswith("watchdog:"))
        self.client.data.update(ready=True)
        self.assertTrue(self.controller.safety_reason("FORWARD").startswith("manual:"))
        self.assertFalse(self.controller.submit(self.decision, epoch=0))
        self.assertEqual(self.client.moves, [])

    def test_start_stop_manual_and_emergency_transitions_send_stop(self):
        epoch = self.ai_ready()
        self.assertEqual(self.client.wire[-1], STOP)
        self.assertTrue(self.controller.submit(self.decision, epoch=epoch))
        self.controller.stop()
        self.assertEqual(self.client.wire[-1], STOP)
        self.assertEqual(self.controller.mode, Mode.MANUAL)
        self.assertFalse(self.controller.submit(self.decision, epoch=epoch))
        self.controller.manual("ROTATE_LEFT")
        self.assertEqual(self.client.wire[-2], STOP)
        self.controller.emergency_stop()
        self.assertEqual(self.client.wire[-1], STOP)
        count = len(self.client.moves)
        for _ in range(5):
            self.controller.submit(self.decision, epoch=self.controller.epoch)
        self.assertEqual(len(self.client.moves), count)
        with self.assertRaises(ValueError):
            self.controller.start_ai("Move")
        self.controller.reset_emergency()
        self.assertEqual(self.client.wire[-1], STOP)
        self.assertEqual(self.controller.mode, Mode.MANUAL)

    def test_action_running_completed_cancelled_interrupted_and_overlap(self):
        epoch = self.ai_ready()
        self.controller.submit(self.decision, epoch=epoch)
        self.assertEqual(self.controller.execution.state, "running")
        self.assertFalse(self.controller.submit(self.decision, epoch=epoch))
        self.assertEqual(len(self.client.moves), 1)
        self.clock.advance(0.31)
        self.client.fresh()
        self.controller.tick()
        self.assertEqual(self.controller.execution.state, "completed")
        self.assertEqual(self.client.wire[-1], STOP)
        self.controller.manual("LEFT")
        self.controller.stop()
        self.assertEqual(self.controller.execution.state, "cancelled")
        self.controller.manual("FORWARD")
        self.client.data.update(distance=10)
        self.controller.tick()
        self.assertEqual(self.controller.execution.state, "interrupted")
        self.assertEqual(self.client.wire[-1], STOP)

    def test_rotations_are_bounded_and_interruptible(self):
        for action in ("ROTATE_LEFT", "ROTATE_RIGHT"):
            self.controller.manual(action)
            self.clock.advance(0.36)
            self.client.fresh()
            self.controller.tick()
            self.assertEqual(self.controller.execution.state, "completed")
            self.assertEqual(self.client.wire[-1], STOP)
            self.controller.manual(action)
            self.controller.emergency_stop()
            self.assertEqual(self.controller.execution.state, "cancelled")
            self.controller.reset_emergency()

    def test_memory_is_bounded(self):
        for _ in range(100):
            self.controller.manual("LEFT")
            self.controller.stop()
        self.assertEqual(len(self.controller.history), self.config.history_size)

    def test_low_confidence_cannot_move_and_invalid_controller_state_stops(self):
        epoch = self.ai_ready()
        self.assertFalse(self.controller.submit(replace(self.decision, confidence=0.1), epoch=epoch))
        self.assertEqual(self.client.moves, [])
        self.controller.manual("FORWARD")
        self.controller.mode = "UNKNOWN"
        self.controller.tick()
        self.assertEqual(self.client.wire[-1], STOP)
        self.assertEqual(self.controller.mode, Mode.MANUAL)

    def test_network_send_exception_stops(self):
        self.client.move = Mock(side_effect=OSError("Wi-Fi send failed"))
        self.assertFalse(self.controller.manual("FORWARD"))
        self.assertEqual(self.client.wire[-1], STOP)
        self.assertEqual(self.controller.machine.phase, Phase.CONNECTION_ERROR)

    def test_concurrent_manual_and_ai_manual_wins_and_writes_serialized(self):
        epoch = self.ai_ready()
        entered = threading.Event()
        release = threading.Event()
        active, maximum = 0, 0
        original = self.client.move

        def slow_move(action, duration):
            nonlocal active, maximum
            active += 1
            maximum = max(active, maximum)
            if action == "FORWARD":
                entered.set()
                release.wait(1)
            original(action, duration)
            active -= 1

        self.client.move = slow_move
        ai = threading.Thread(target=self.controller.submit, args=(self.decision, "ai", epoch))
        ai.start()
        self.assertTrue(entered.wait(1))
        manual = threading.Thread(target=self.controller.manual, args=("LEFT",))
        manual.start()
        release.set()
        ai.join(1)
        manual.join(1)
        self.assertEqual(maximum, 1)
        self.assertEqual(self.controller.mode, Mode.MANUAL)
        self.assertEqual(self.client.moves[-1][0], "LEFT")
        self.assertEqual(self.client.wire[-2], STOP)
        self.assertFalse(self.controller.submit(self.decision, epoch=epoch))
        self.assertEqual(self.client.moves[-1][0], "LEFT")

    def test_emergency_flag_wins_over_waiting_ai(self):
        epoch = self.ai_ready()
        with self.controller.lock:
            stop = threading.Thread(target=self.controller.emergency_stop)
            stop.start()
            self.assertTrue(self.controller.emergency.wait(1))
            self.assertFalse(self.controller.submit(self.decision, epoch=epoch))
        stop.join(1)
        self.assertEqual(self.client.moves, [])

    def test_all_state_transitions_and_illegal_edges(self):
        for source in Phase:
            for target in Phase:
                with self.subTest(source=source, target=target):
                    machine = StateMachine()
                    machine.phase = source
                    allowed = source == target or source != Phase.EMERGENCY_STOP and target in NEXT[source] | INTERRUPTS
                    if allowed:
                        machine.transition(target)
                        self.assertEqual(machine.phase, target)
                    else:
                        with self.assertRaises(ValueError):
                            machine.transition(target)
        machine.phase = Phase.EMERGENCY_STOP
        machine.transition(Phase.MANUAL, recovery=True)
        with self.assertRaises(ValueError):
            machine.transition("UNKNOWN")

    def test_shutdown_cancels_then_stops_before_closing_network(self):
        runtime = Runtime(self.config, self.client, Mock())
        order = []
        runtime.driver.close = Mock(side_effect=lambda: order.append("cancel_ai"))
        self.client.stop = Mock(side_effect=lambda: order.append("STOP"))
        self.client.wait_stopped = Mock(side_effect=lambda timeout: order.append("verify_stop"))
        self.client.close = Mock(side_effect=lambda: order.append("close_connections"))
        runtime.close()
        self.assertEqual(order, ["cancel_ai", "STOP", "verify_stop", "close_connections"])
        runtime.close()
        self.assertEqual(len(order), 4)


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.config = replace(Config(), loop_interval=0.01, settle_time=0.01)
        self.client = FakeClient(self.config)
        self.controller = Controller(self.client, self.config)
        self.ollama = Mock(verified=True)
        self.driver = AIDriver(self.controller, self.ollama)

    def tearDown(self):
        self.driver.close()
        self.controller.close()

    def test_closed_loop_reobserves_bounded_actions_objective_and_state(self):
        self.ollama.decide.side_effect = [response("FORWARD"), response("ROTATE_LEFT"), response("BACKWARD"),
                                           response("STOP", goal_reached=True)]
        with FreshFeed(self.client):
            self.driver.start("Find the red object")
            wait_until(lambda: not self.driver.worker.is_alive())
        self.assertEqual([a for a, _ in self.client.moves], ["FORWARD", "ROTATE_LEFT", "BACKWARD"])
        self.assertEqual([d for _, d in self.client.moves], [0.04] * 3)
        observations = [call.args[0] for call in self.ollama.decide.call_args_list]
        sequences = [o["frame_sequence"] for o in observations]
        self.assertEqual(len(set(sequences)), 4)
        self.assertEqual(sequences, sorted(sequences))
        self.assertTrue(all(o["current_action"] == "STOP" for o in observations))
        self.assertTrue(all(o["objective"] == "Find the red object" for o in observations))
        self.assertTrue(all(o["connected"] and o["ultrasonic_cm"] == 100 for o in observations))
        self.assertEqual(len(observations[2]["recent_actions"]), 2)
        for index, data in enumerate(self.client.wire):
            if data != STOP:
                self.assertEqual(self.client.wire[index + 1], STOP)
        self.assertIn("Goal reported reached", self.controller.status)

    def test_slow_inference_stays_stopped_and_emergency_remains_responsive(self):
        entered, release = threading.Event(), threading.Event()

        def slow(*args):
            entered.set()
            release.wait(2)
            return response()

        self.ollama.decide.side_effect = slow
        with FreshFeed(self.client):
            self.driver.start("Explore")
            self.assertTrue(entered.wait(1))
            start = time.monotonic()
            self.controller.emergency_stop()
            self.assertLess(time.monotonic() - start, 0.1)
            self.assertEqual(self.client.wire[-1], STOP)
            self.assertEqual(self.client.moves, [])
            release.set()
            wait_until(lambda: not self.driver.worker.is_alive())
        self.assertEqual(self.client.moves, [])

    def test_hanging_inference_timeout_does_not_repeat_last_movement(self):
        self.driver.config = replace(self.config, inference_timeout=0.08)
        release = threading.Event()
        calls = 0

        def model(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                return response()
            release.wait(1)
            return response()

        self.ollama.decide.side_effect = model
        with FreshFeed(self.client):
            self.driver.start("Explore")
            wait_until(lambda: not self.driver.worker.is_alive())
            self.assertEqual(len(self.client.moves), 1)
            self.assertEqual(self.client.wire[-1], STOP)
            self.assertIn("timed out", self.controller.status)
            with self.assertRaises(ValueError):
                self.driver.start("Explore")
            release.set()
            self.driver.inference.join(1)
        self.assertEqual(len(self.client.moves), 1)

    def test_each_model_failure_stops_without_movement(self):
        for failure in (OSError("Ollama unavailable"), RuntimeError("internal exception"), "not json", response(duration=999)):
            with self.subTest(failure=failure):
                self.ollama.verified = True
                if isinstance(failure, Exception):
                    self.ollama.decide.side_effect = failure
                else:
                    self.ollama.decide.side_effect = None
                    self.ollama.decide.return_value = failure
                with FreshFeed(self.client):
                    self.driver.start("Explore")
                    wait_until(lambda: not self.driver.worker.is_alive())
                self.assertEqual(self.client.moves, [])
                self.assertEqual(self.client.wire[-1], STOP)
                self.assertEqual(self.controller.machine.phase, Phase.AI_ERROR)

    def test_stale_decision_is_rejected(self):
        self.driver.config = replace(self.config, decision_max_age=0.001)
        self.ollama.decide.side_effect = lambda *args: (time.sleep(0.03), response())[1]
        with FreshFeed(self.client):
            self.driver.start("Explore")
            wait_until(lambda: not self.driver.worker.is_alive())
        self.assertEqual(self.client.moves, [])
        self.assertIn("expired", self.controller.status)

    def test_missing_stop_ack_prevents_observation_and_movement(self):
        self.client.wait_stopped = Mock(return_value=False)
        with FreshFeed(self.client):
            self.driver.start("Explore")
            wait_until(lambda: not self.driver.worker.is_alive())
        self.ollama.decide.assert_not_called()
        self.assertEqual(self.client.moves, [])
        self.assertIn("acknowledge", self.controller.status)

    def test_lost_post_action_stop_ack_prevents_next_decision(self):
        self.client.wait_stopped = Mock(side_effect=[True, False])
        self.ollama.decide.return_value = response()
        with FreshFeed(self.client):
            self.driver.start("Explore")
            wait_until(lambda: not self.driver.worker.is_alive())
        self.assertEqual(len(self.client.moves), 1)
        self.assertEqual(self.ollama.decide.call_count, 1)
        self.assertIn("acknowledge STOP after action", self.controller.status)

    def test_camera_failure_after_action_stops_reobservation(self):
        self.ollama.decide.return_value = response()
        with FreshFeed(self.client):
            self.driver.start("Explore")
            wait_until(lambda: len(self.client.moves) == 1)
        self.client.frames.clear()
        wait_until(lambda: not self.driver.worker.is_alive())
        self.assertEqual(len(self.client.moves), 1)
        self.assertEqual(self.client.wire[-1], STOP)

    def test_oscillation_requests_purposeful_reassessment(self):
        history = [{"action": a, "outcome": "completed"} for a in ["LEFT", "RIGHT"] * 3]
        self.assertTrue(oscillating(history))
        self.assertTrue(oscillating([{"action": a} for a in ["FORWARD", "STOP"] * 3]))
        self.assertFalse(oscillating(history[:4]))
        self.controller.history.extend(history)
        self.ollama.decide.side_effect = [response("ROTATE_LEFT"), response("STOP", goal_reached=True)]
        with FreshFeed(self.client):
            self.driver.start("Find another path")
            wait_until(lambda: not self.driver.worker.is_alive())
        self.assertTrue(self.ollama.decide.call_args_list[0].args[0]["reassess"])
        self.assertEqual(self.client.moves, [("ROTATE_LEFT", 0.04)])
        self.assertNotEqual(self.ollama.decide.call_args_list[0].args[0]["frame_sequence"],
                            self.ollama.decide.call_args_list[1].args[0]["frame_sequence"])

    def test_oscillation_cannot_continue_same_failed_strategy(self):
        self.controller.history.extend({"action": a} for a in ["LEFT", "RIGHT"] * 3)
        self.ollama.decide.return_value = response("LEFT")
        with FreshFeed(self.client):
            self.driver.start("Explore")
            wait_until(lambda: not self.driver.worker.is_alive())
        self.assertEqual(self.client.moves, [])
        self.assertIn("oscillating", self.controller.status)
