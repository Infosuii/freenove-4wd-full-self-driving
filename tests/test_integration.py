from dataclasses import replace
import json
import importlib.util
import socket
import struct
import time
import unittest
from unittest.mock import Mock, patch
from ai_driver.config import Config
from ai_driver.actions import validate
from ai_driver.controller import Controller
from ai_driver.driver import AIDriver
from ai_driver.network import PiClient
from ai_driver.ollama import Ollama
from ai_driver.protocol import STOP, SIGNS, Lines
from ai_driver.state import Mode, Phase
from tests.helpers import response, wait_until, jpeg, SERVER
from tests.local_pi import LocalPi


class RealServerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.pi = LocalPi()
        self.config = replace(Config(), pi_host="127.0.0.1", command_port=self.pi.command_port,
                              video_port=self.pi.video_port, reconnect_interval=0.1,
                              loop_interval=0.03, settle_time=0.03)
        self.client = PiClient(self.config)
        self.controller = Controller(self.client, self.config)
        self.controller.start()
        self.client.start()
        wait_until(lambda: self.client.ready and self.client.frames.get(1) and self.client.distance == 100)

    def tearDown(self):
        self.controller.close()
        self.client.close()
        self.pi.close()

    def test_original_main_starts_with_mock_hardware_and_correct_profile(self):
        self.pi.car_factory.assert_called_once_with(enable_servos=False, fresh_sonic=True)
        self.assertTrue(self.pi.window.cmd_thread.is_alive())
        self.assertTrue(self.pi.window.video_thread.is_alive())
        self.assertTrue(self.pi.window.car_thread.is_alive())
        self.assertTrue(self.pi.guard.worker.is_alive())
        self.assertEqual(self.client.distance, 100)
        self.assertTrue(self.client.frames.get(1).jpeg.startswith(b"\xff\xd8"))

    def test_all_actions_through_real_sockets_parser_to_original_motor_interface(self):
        for action in SIGNS:
            with self.subTest(action=action):
                self.assertTrue(self.controller.manual(action))
                expected = tuple(s * 960 for s in SIGNS[action])
                wait_until(lambda: self.pi.motor.calls[-1] == expected)
                if action != "STOP":
                    self.assertTrue(any(line.startswith(b"CMD_MOTOR#") and b"#350#" in line for line in self.pi.commands))
                    self.controller.stop()
                    wait_until(lambda: self.pi.motor.calls[-1] == (0,) * 4)
        self.assertEqual(self.pi.motor.maximum_active, 1)
        self.assertFalse(any(b"SERVO" in line or b"CAR_ROTATE" in line for line in self.pi.commands))

    def test_complete_camera_ollama_validation_safety_network_motor_closed_loop(self):
        scripted = iter([response("FORWARD", duration=0.1), response("ROTATE_RIGHT", duration=0.1),
                         response("BACKWARD", duration=0.1), response("STOP", goal_reached=True)])
        seen = []

        def http(method, url, body, timeout):
            if url.endswith("/api/tags"):
                return {"models": [{"name": self.config.model}]}
            if url.endswith("/api/show"):
                return {"capabilities": ["vision"]}
            if "format" not in body:
                return {"done": True, "message": {"content": "hi"}}
            seen.append(body)
            return {"done": True, "message": {"content": next(scripted)}}

        model = Ollama(self.config, http)
        self.assertTrue(model.test())
        driver = AIDriver(self.controller, model)
        try:
            driver.start("Find the doorway")
            wait_until(lambda: not driver.worker.is_alive(), timeout=5)
            self.assertIn("Goal reported reached", self.controller.status)
            movement = [d for d in self.pi.motor.calls if any(d)]
            self.assertEqual(movement, [(960, 960, 960, 960), (960, 960, -960, -960), (-960,) * 4])
            self.assertEqual(self.pi.motor.calls[-1], (0,) * 4)
            observations = [json.loads(b["messages"][1]["content"]) for b in seen]
            self.assertEqual(len(observations), 4)
            self.assertTrue(all(o["objective"] == "Find the doorway" and o["current_action"] == "STOP" for o in observations))
            self.assertEqual(len({o["frame_sequence"] for o in observations}), 4)
            self.assertTrue(all(b["messages"][1]["images"] for b in seen))
            self.assertEqual(self.pi.motor.maximum_active, 1)
        finally:
            driver.close()

    def test_obstacle_is_enforced_on_pi_independent_of_laptop(self):
        self.controller.manual("FORWARD")
        wait_until(lambda: any(self.pi.motor.calls[-1]))
        self.pi.distance = 10
        wait_until(lambda: self.pi.motor.calls[-1] == (0,) * 4)
        wait_until(lambda: self.controller.mode == Mode.MANUAL and "obstacle" in self.controller.status.lower())
        count = len([d for d in self.pi.motor.calls if any(d)])
        self.client.move("FORWARD", 0.1)  # Bypass laptop safety deliberately in test.
        wait_until(lambda: "Pi safety" in self.controller.status)
        self.assertEqual(len([d for d in self.pi.motor.calls if any(d)]), count)

    def test_complete_pipeline_executes_original_motor_and_pca_with_only_smbus_mocked(self):
        bus = Mock()
        bus.SMBus.return_value.read_byte_data.return_value = 0
        with patch.dict("sys.modules", {"smbus": bus}):
            spec = importlib.util.spec_from_file_location("tested_pca", SERVER / "pca9685.py")
            pca = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pca)
        with patch.dict("sys.modules", {"pca9685": pca}):
            spec = importlib.util.spec_from_file_location("tested_motor", SERVER / "motor.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        motor = module.Ordinary_Car()
        motor.set_motor_model = Mock(wraps=motor.set_motor_model)
        with self.pi.guard.lock:
            self.pi.guard.motor = motor
        model = Mock(verified=True)
        model.decide.side_effect = [response("FORWARD", duration=0.1), response("STOP", goal_reached=True)]
        driver = AIDriver(self.controller, model)
        try:
            driver.start("Pipeline to I2C boundary")
            wait_until(lambda: not driver.worker.is_alive())
            self.assertIn("Goal reported reached", self.controller.status)
            motor.set_motor_model.assert_any_call(960, 960, 960, 960)
            motor.set_motor_model.assert_called_with(0, 0, 0, 0)
            # Original PCA9685 writes channel 1 OFF low/high for duty 960.
            bus.SMBus.return_value.write_byte_data.assert_any_call(0x40, 0x0C, 192)
            bus.SMBus.return_value.write_byte_data.assert_any_call(0x40, 0x0D, 3)
        finally:
            driver.close()
            with self.pi.guard.lock:
                self.pi.guard.motor = self.pi.motor
            motor.close()

    def test_socket_disconnect_reconnect_requires_deliberate_ai_restart(self):
        epoch = self.controller.start_ai("Explore")
        self.controller.phase(Phase.AI_OBSERVING, epoch)
        self.controller.phase(Phase.AI_DECIDING, epoch)
        self.controller.submit(validate(response(duration=0.5), 0.75), epoch=epoch)
        wait_until(lambda: any(self.pi.motor.calls[-1]))
        old_token = self.client.token
        self.pi.disconnect_command()
        wait_until(lambda: self.pi.motor.calls[-1] == (0,) * 4)
        wait_until(lambda: self.client.ready and self.client.token != old_token)
        self.assertEqual(self.controller.mode, Mode.MANUAL)
        count = len([d for d in self.pi.motor.calls if any(d)])
        self.assertFalse(self.controller.submit(validate(response(), 0.75), epoch=epoch))
        time.sleep(0.15)
        self.assertEqual(len([d for d in self.pi.motor.calls if any(d)]), count)

    def test_laptop_control_silence_cannot_leave_motor_command_running(self):
        self.client.move("ROTATE_LEFT", 0.1)
        wait_until(lambda: any(self.pi.motor.calls[-1]))
        # Telemetry worker still polls, but no further control messages arrive.
        wait_until(lambda: self.pi.motor.calls[-1] == (0,) * 4)
        self.assertIsNone(self.pi.guard.deadline)

    def test_sensor_failure_during_motion_stops_both_layers(self):
        self.controller.manual("BACKWARD")
        wait_until(lambda: any(self.pi.motor.calls[-1]))
        self.pi.distance = None
        wait_until(lambda: self.pi.motor.calls[-1] == (0,) * 4)
        wait_until(lambda: self.client.distance is None)
        self.assertFalse(self.controller.manual("BACKWARD"))

    def test_corrupt_video_discard_then_valid_frame_recovers(self):
        old_sequence = self.client.frames.sequence
        self.pi.window.tcp_server.send_data_to_video_client(struct.pack("<I", 4) + b"junk")
        wait_until(lambda: self.client.frames.sequence > old_sequence)
        self.assertTrue(self.client.frames.get(1))


class NetworkBoundaryTests(unittest.TestCase):
    def test_original_tcp_server_reassembles_bytewise_commands_and_disconnect_callback(self):
        from tcp_server import TCPServer
        disconnected = Mock()
        server = TCPServer(newline_framing=True, on_disconnect=disconnected)
        server.start("127.0.0.1", 0)
        sock = socket.create_connection(server.server_socket.getsockname(), timeout=1)
        try:
            for byte in b"CMD_SONIC\nCMD_MOTOR#0#0#0#0\n":
                sock.sendall(bytes([byte]))
            wait_until(lambda: server.message_queue.qsize() == 2)
            self.assertEqual(server.message_queue.get()[1], "CMD_SONIC\n")
            self.assertEqual(server.message_queue.get()[1], "CMD_MOTOR#0#0#0#0\n")
            sock.sendall(b"partial")
            sock.close()
            wait_until(lambda: disconnected.called)
            self.assertTrue(server.message_queue.empty())
        finally:
            sock.close()
            server.close()

    def test_real_client_fails_visibly_with_absent_local_services(self):
        held = socket.socket()
        held.bind(("127.0.0.1", 0))  # Reserved, not listening: deterministic refusal.
        cfg = replace(Config(), pi_host="127.0.0.1", command_port=held.getsockname()[1], video_port=held.getsockname()[1])
        client = PiClient(cfg)
        controller = Controller(client, cfg)
        client.start()
        try:
            wait_until(lambda: "error" in client.command_status and "error" in client.video_status)
            self.assertFalse(client.ready)
            self.assertEqual(controller.mode, Mode.MANUAL)
            self.assertFalse(controller.manual("FORWARD"))
        finally:
            controller.close()
            client.close()
            held.close()

    def test_client_rejects_bad_handshake_and_telemetry(self):
        client = PiClient(Config())
        for line in ("CMD_DRIVER#READY#1#bad#1#0.75#30", "CMD_DRIVER#READY#1#0123456789abcdef#nan#0.75#30",
                     "CMD_DRIVER#READY#1#0123456789abcdef#2#0.75#30", "CMD_DRIVER#READY#1#0123456789abcdef#1#0.75#10",
                     "CMD_DRIVER#ACTING#bad", "CMD_MODE#2#34", "garbage"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                client._line(line)
        for value in ("NaN", "-1", "10000", "none"):
            client._line("CMD_MODE#3#" + value)
            self.assertIsNone(client.distance)

    def test_stop_ack_is_correlated_with_last_sent_action(self):
        client = PiClient(Config())
        client.pending_stop = 4
        client._line("CMD_DRIVER#STOPPED#requested#3")
        self.assertFalse(client.stopped_ack.is_set())
        client._line("CMD_DRIVER#STOPPED#completed#4")
        self.assertFalse(client.stopped_ack.is_set())
        client._line("CMD_DRIVER#STOPPED#requested#4")
        self.assertTrue(client.wait_stopped(0.01))

    def test_debug_logs_redact_session_token(self):
        client = PiClient(Config())
        client.ready = True
        client.token = "0123456789abcdef"
        client.command_socket = Mock()
        with self.assertLogs("ai_driver.network", level="DEBUG") as logs:
            client.move("FORWARD", 0.1)
        self.assertNotIn(client.token, " ".join(logs.output))
        self.assertIn("<session>", " ".join(logs.output))
