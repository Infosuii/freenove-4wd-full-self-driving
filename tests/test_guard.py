import ast
import importlib.util
import threading
import time
import unittest
from unittest.mock import Mock, patch
from tests.helpers import Clock, Motor, SERVER
from driver_guard import DriverGuard


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.motor, self.send = Clock(), Motor(), Mock()
        self.guard = DriverGuard(self.motor, self.send, clock=self.clock)
        self.address = ("127.0.0.1", 1234)
        self.guard.handle("CMD_DRIVER#HELLO#1", self.address)
        self.guard.update_distance(100)

    def move(self, duties=(1200, 1200, 1200, 1200), ms=500, seq=1, token=None):
        command = "CMD_MOTOR#" + "#".join(map(str, duties))
        self.guard.handle(f"{command}#{ms}#{token or self.guard.token}#{seq}", self.address)

    def test_original_scale_and_bounded_completion(self):
        self.move()
        self.assertEqual(self.motor.calls[-1], (960,) * 4)
        self.clock.advance(0.499)
        self.guard.tick()
        self.assertEqual(self.motor.calls[-1], (960,) * 4)
        self.clock.advance(0.0011)
        self.guard.update_distance(100)
        self.assertEqual(self.motor.calls[-1], (0,) * 4)
        self.assertIsNone(self.guard.deadline)

    def test_watchdog_exact_deadline_and_no_repeat_stop(self):
        self.guard.max_duration = self.guard.watchdog
        self.move(ms=1000)
        self.clock.advance(0.999)
        self.guard.update_distance(100)
        self.assertNotEqual(self.motor.calls[-1], (0,) * 4)
        self.clock.advance(0.0011)
        self.guard.update_distance(100)
        self.assertEqual(self.motor.calls[-1], (0,) * 4)
        self.assertIn("watchdog", self.send.call_args.args[0])
        count = len(self.motor.calls)
        self.guard.tick()
        self.assertEqual(len(self.motor.calls), count)

    def test_telemetry_does_not_extend_command_lifetime(self):
        self.move()
        for _ in range(6):
            self.clock.advance(0.1)
            self.guard.handle("CMD_SONIC", self.address)
            self.guard.update_distance(100)
        self.assertEqual(self.motor.calls[-1], (0,) * 4)

    def test_malformed_messages_never_move(self):
        for message in ["", "CMD_MOTOR", "CMD_MOTOR#NaN", "CMD_MOTOR#1#1#1#1",
                        "CMD_CAR_ROTATE#0#0#0#1500", "CMD_SERVO#0#90", "CMD_MODE#three",
                        "CMD_M_MOTOR#0#1500#0#0"]:
            with self.subTest(message=message):
                self.guard.handle(message, self.address)
                self.assertEqual(self.motor.calls[-1], (0,) * 4)
        self.assertTrue(all(c == (0,) * 4 for c in self.motor.calls))

    def test_bad_durations_duties_session_sequence(self):
        for ms in (-1, 0, 751, 999999):
            with self.subTest(ms=ms):
                self.move(ms=ms)
                self.assertEqual(self.motor.calls[-1], (0,) * 4)
        self.move(duties=(1501,) * 4)
        self.assertEqual(self.motor.calls[-1], (0,) * 4)
        self.move(token="wrong")
        self.assertEqual(self.motor.calls[-1], (0,) * 4)
        self.move()
        self.guard.stop("test")
        self.move()
        self.assertEqual(self.motor.calls[-1], (0,) * 4)

    def test_each_sensor_failure_stops_and_blocks(self):
        for distance in (None, -1, 0, float("nan"), float("inf"), 301):
            with self.subTest(distance=distance):
                self.guard.update_distance(distance)
                self.move()
                self.assertEqual(self.motor.calls[-1], (0,) * 4)
        self.guard.update_distance(100)
        self.move()
        self.clock.advance(0.501)
        self.guard.tick()
        self.assertEqual(self.motor.calls[-1], (0,) * 4)
        self.assertIn("ultrasonic_unavailable", self.send.call_args.args[0])

    def test_close_obstacle_interrupts_forward_but_allows_inspection(self):
        self.move()
        self.guard.update_distance(20)
        self.assertEqual(self.motor.calls[-1], (0,) * 4)
        self.move(duties=(-1200, -1200, 1200, 1200), seq=2)
        self.assertEqual(self.motor.calls[-1], (-960, -960, 960, 960))
        self.guard.handle("CMD_MOTOR#0#0#0#0", self.address)
        self.assertEqual(self.motor.calls[-1], (0,) * 4)

    def test_disconnect_revokes_token_and_stops(self):
        self.move()
        token = self.guard.token
        self.guard.disconnect(self.address)
        self.assertEqual(self.motor.calls[-1], (0,) * 4)
        self.assertIsNone(self.guard.token)
        self.move(token=token, seq=2)
        self.assertEqual(self.motor.calls[-1], (0,) * 4)

    def test_closed_guard_rejects_queued_handshake_and_motion(self):
        self.move()
        token = self.guard.token
        self.guard.close()
        count = len([c for c in self.motor.calls if any(c)])
        self.guard.handle("CMD_DRIVER#HELLO#1", self.address)
        self.move(token=token, seq=2)
        self.assertIsNone(self.guard.token)
        self.assertEqual(len([c for c in self.motor.calls if any(c)]), count)
        self.assertEqual(self.motor.calls[-1], (0,) * 4)

    def test_overlapping_command_stops_instead_of_stacking(self):
        self.move()
        self.move(seq=2)
        self.assertEqual(self.motor.calls[-1], (0,) * 4)

    def test_motor_failure_latches_and_retries_stop(self):
        self.guard.motor = Mock()
        self.guard.motor.set_motor_model.side_effect = OSError("I2C failed")
        with self.assertRaises(OSError):
            self.move()
        self.assertTrue(self.guard.hardware_fault)
        self.guard.motor.set_motor_model.side_effect = None
        self.guard.tick()
        self.guard.motor.set_motor_model.assert_called_with(0, 0, 0, 0)
        self.move(seq=2)
        self.guard.motor.set_motor_model.assert_called_with(0, 0, 0, 0)

    def test_real_watchdog_thread_independent_of_command_worker(self):
        guard = DriverGuard(self.motor, self.send, max_duration=0.05, watchdog=0.05)
        guard.start()
        try:
            guard.handle("CMD_DRIVER#HELLO#1", self.address)
            guard.update_distance(100)
            guard.handle(f"CMD_MOTOR#1200#1200#1200#1200#50#{guard.token}#1", self.address)
            time.sleep(0.09)
            self.assertEqual(self.motor.calls[-1], (0,) * 4)
            self.assertIn("watchdog", self.send.call_args.args[0])
        finally:
            guard.close()

    def test_guard_serializes_concurrent_motor_writers(self):
        threads = [threading.Thread(target=self.guard.stop, args=("concurrent",)) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.motor.maximum_active, 1)


class BaselineTests(unittest.TestCase):
    def test_motor_signs_match_original_executable_examples(self):
        from ai_driver.protocol import SIGNS
        source = (SERVER / "motor.py").read_text()
        examples = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "set_motor_model":
                try:
                    values = tuple(ast.literal_eval(a) for a in node.args)
                except ValueError:
                    continue
                if len(values) == 4 and any(values):
                    examples.append(tuple(1 if v > 0 else -1 for v in values))
        self.assertEqual(examples, [SIGNS[a] for a in ("FORWARD", "BACKWARD", "LEFT", "RIGHT")])

    def test_existing_hardware_diagnostic_entrypoints_import_without_hardware(self):
        spec = importlib.util.spec_from_file_location("original_diagnostics", SERVER / "test.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for device in ("Motor", "Ultrasonic", "Led", "Servo", "Infrared", "Adc", "Buzzer"):
            self.assertTrue(callable(getattr(module, "test_" + device)))

    def test_original_motor_runs_with_only_pca9685_mocked(self):
        pca = Mock()
        with patch.dict("sys.modules", {"pca9685": pca}):
            spec = importlib.util.spec_from_file_location("original_motor", SERVER / "motor.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            motor = module.Ordinary_Car()
            motor.set_motor_model(960, 960, 960, 960)
            pca.PCA9685.return_value.set_motor_pwm.assert_any_call(1, 960)
            pca.PCA9685.return_value.set_motor_pwm.assert_any_call(7, 960)
            motor.close()
            pca.PCA9685.return_value.close.assert_called_once()

    def test_safe_car_initialization_never_constructs_servo(self):
        modules = {name: Mock() for name in ("ultrasonic", "motor", "servo", "infrared", "adc")}
        with patch.dict("sys.modules", modules):
            spec = importlib.util.spec_from_file_location("original_car", SERVER / "car.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            car = module.Car(enable_servos=False, fresh_sonic=True)
            modules["servo"].Servo.assert_not_called()
            modules["ultrasonic"].Ultrasonic.assert_called_with(track_freshness=True)
            car.close()

    def test_gpiozero_freshness_records_failed_echo_not_old_median(self):
        # Real GPIOZero method boundary; no GPIO pin construction.
        import ultrasonic
        sensor = object.__new__(ultrasonic.FreshDistanceSensor)
        with patch.object(ultrasonic.DistanceSensor, "_read", return_value=0.5):
            self.assertEqual(sensor._read(), 0.5)
            self.assertEqual(sensor.latest_echo[0], 0.5)
        with patch.object(ultrasonic.DistanceSensor, "_read", return_value=None):
            sensor._read()
            self.assertIsNone(sensor.latest_echo[0])

    def test_modified_python_sources_compile_without_writing_user_caches(self):
        for path in list(SERVER.glob("*.py")) + list((SERVER.parents[1] / "ai_driver").glob("*.py")):
            compile(path.read_bytes(), str(path), "exec")

    def test_original_camera_lifecycle_with_picamera2_boundary_mocked(self):
        modules = {name: Mock() for name in ("picamera2", "picamera2.encoders", "picamera2.outputs", "libcamera")}
        with patch.dict("sys.modules", modules):
            spec = importlib.util.spec_from_file_location("original_camera", SERVER / "camera.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            camera = module.Camera()
            camera.start_stream()
            modules["picamera2.encoders"].JpegEncoder.assert_called_once()
            self.assertIsNone(camera.get_frame(timeout=0.001))
            result = []
            thread = threading.Thread(target=lambda: result.append(camera.get_frame(timeout=1)))
            thread.start()
            from tests.helpers import jpeg
            data = jpeg()
            time.sleep(0.01)
            camera.streaming_output.write(data)
            thread.join(1)
            self.assertEqual(result, [data])
            camera.close()
            modules["picamera2"].Picamera2.return_value.stop_recording.assert_called_once()
            modules["picamera2"].Picamera2.return_value.close.assert_called_once()
