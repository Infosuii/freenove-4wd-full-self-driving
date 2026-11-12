import json
import struct
import unittest
from ai_driver.actions import validate
from ai_driver.config import Config
from ai_driver.protocol import Lines, JpegFrames, LatestFrame, decode_jpeg, distance_value, SIGNS
from tests.helpers import Clock, jpeg, response


class ValidationTests(unittest.TestCase):
    def test_every_valid_action(self):
        for action in SIGNS:
            with self.subTest(action=action):
                self.assertEqual(validate(response(action), 0.75).action, action)
        self.assertTrue(validate(response("STOP", goal_reached=True), 0.75).goal_reached)

    def test_invalid_json_unknown_action_missing_extra_fields(self):
        bad = ["", "not JSON", "```json\n{}\n```", "[]", "null", "42", "true", "{}",
               response(action="SHELL"), response(action=[]), response(extra="ignored"),
               response() + "extra", response().replace('"action": "FORWARD"', '"action":"STOP","action":"FORWARD"')]
        obj = json.loads(response())
        for field in obj:
            bad.append(json.dumps({k: v for k, v in obj.items() if k != field}))
        bad.extend([None, {}, "x" * 4097])
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    validate(raw, 0.75)

    def test_exhaustive_invalid_numeric_duration_and_confidence(self):
        cases = {"duration": [-1, 0, 0.0001, 0.751, 1e300, float("nan"), float("inf"), -float("inf"), "0.3", True, None, []],
                 "confidence": [-0.1, 1.001, float("nan"), float("inf"), "0.5", True, None, {}]}
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        validate(response(**{field: value}), 0.75)
        self.assertEqual(validate(response(duration=0.75), 0.75).duration, 0.75)
        self.assertEqual(validate(response(duration=0.001), 0.75).duration, 0.001)

    def test_status_goal_and_stop_constraints(self):
        for status in ("", " ", "x" * 241, "x" + " " * 241, "bad\ntext", 1, None, {}):
            with self.subTest(status=status), self.assertRaises(ValueError):
                validate(response(status=status), 0.75)
        for goal in ("true", 1, None, []):
            with self.subTest(goal=goal), self.assertRaises(ValueError):
                validate(response(goal_reached=goal), 0.75)
        with self.assertRaises(ValueError):
            validate(response(goal_reached=True), 0.75)
        obj = json.loads(response("STOP"))
        obj["duration"] = 0.5
        with self.assertRaises(ValueError):
            validate(json.dumps(obj), 0.75)

    def test_configuration_rejects_unsafe_or_malformed_limits(self):
        for data in ({"speed": 1501}, {"max_action_duration": 5}, {"model": ""}, {"watchdog_timeout": float("nan")},
                     {"command_port": -1}, {"video_port": 70000}, {"speed": True}, {"history_size": 51},
                     {"ultrasonic_threshold": 301}, {"pi_host": "http://bad"}, {"socket_timeout": 0.5}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                Config(**data)


class ProtocolTests(unittest.TestCase):
    def test_arbitrary_command_fragment_boundaries(self):
        wire = b"CMD_MODE#3#34.5\nCMD_DRIVER#STOPPED#completed\n"
        expected = ["CMD_MODE#3#34.5", "CMD_DRIVER#STOPPED#completed"]
        for boundary in range(len(wire) + 1):
            parser = Lines()
            self.assertEqual(parser.feed(wire[:boundary]) + parser.feed(wire[boundary:]), expected)
        parser = Lines()
        self.assertEqual(sum((parser.feed(bytes([b])) for b in wire), []), expected)

    def test_bad_lines(self):
        for wire in (b"x" * 4097, b"x" * 4097 + b"\n", b"\xff\n"):
            with self.subTest(wire=wire[:10]), self.assertRaises(ValueError):
                Lines().feed(wire)

    def test_video_every_boundary_and_multiple_frames(self):
        frame = jpeg()
        wire = struct.pack("<I", len(frame)) + frame
        for boundary in range(len(wire) + 1):
            parser = JpegFrames()
            self.assertEqual(parser.feed(wire[:boundary]) + parser.feed(wire[boundary:]), [frame])
            parser.eof()
        self.assertEqual(JpegFrames().feed(wire * 3), [frame] * 3)
        self.assertEqual(decode_jpeg(frame).size, (64, 48))

    def test_truncated_corrupt_lengths_and_jpegs(self):
        frame = jpeg()
        wire = struct.pack("<I", len(frame)) + frame
        for size in (1, 3, 4, 10, len(wire) - 1):
            with self.subTest(size=size):
                parser = JpegFrames()
                self.assertEqual(parser.feed(wire[:size]), [])
                with self.assertRaises(ValueError):
                    parser.eof()
        for length in (0, 1, 3, 2_000_001, 0xFFFFFFFF):
            with self.subTest(length=length), self.assertRaises(ValueError):
                JpegFrames().feed(struct.pack("<I", length))
        for data in (b"junk", b"\xff\xd8junk\xff\xd9", frame[:-2]):
            with self.subTest(data=data[:10]), self.assertRaises((ValueError, OSError)):
                decode_jpeg(data)
        corrupt = b"junk"
        parser = JpegFrames()
        self.assertEqual(parser.feed(struct.pack("<I", 4) + corrupt + wire), [corrupt, frame])

    def test_latest_frame_replaces_stales_and_rejects_corrupt_refresh(self):
        clock = Clock()
        buffer = LatestFrame(clock)
        for _ in range(100):
            buffer.put(jpeg())
        self.assertEqual(buffer.get(1).sequence, 100)
        clock.advance(1.01)
        self.assertIsNone(buffer.get(1))
        with self.assertRaises(ValueError):
            buffer.put(b"bad")
        self.assertIsNone(buffer.get(1))
        buffer.put(jpeg("red"))
        self.assertIsNone(buffer.get(1, after=clock()))
        buffer.clear()
        self.assertIsNone(buffer.get(1))

    def test_all_invalid_sensor_values(self):
        for value in (None, "", "bad", -1, 0, "NaN", "inf", 301, 1e99, True, False):
            with self.subTest(value=value):
                self.assertIsNone(distance_value(value))
        self.assertEqual(distance_value("34.5"), 34.5)
