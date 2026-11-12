"""Actual Freenove line protocol and <I length-prefixed JPEG framing."""
import io
import math
import struct
import threading
import time
from dataclasses import dataclass
from PIL import Image

STOP = b"CMD_MOTOR#0#0#0#0\n"
HELLO = b"CMD_DRIVER#HELLO#1\n"
SONIC = b"CMD_SONIC\n"
SIGNS = {
    "STOP": (0, 0, 0, 0),
    "FORWARD": (1, 1, 1, 1),
    "BACKWARD": (-1, -1, -1, -1),
    "LEFT": (-1, -1, 1, 1),
    "RIGHT": (1, 1, -1, -1),
    "ROTATE_LEFT": (-1, -1, 1, 1),
    "ROTATE_RIGHT": (1, 1, -1, -1),
}


def motor_command(action, speed, duration, token, sequence):
    if action == "STOP":
        return STOP
    duties = "#".join(str(s * speed) for s in SIGNS[action])
    return f"CMD_MOTOR#{duties}#{int(duration * 1000)}#{token}#{sequence}\n".encode("ascii")


class Lines:
    def __init__(self, limit=4096):
        self.buffer = b""
        self.limit = limit

    def feed(self, data):
        self.buffer += data
        result = []
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if len(line) > self.limit:
                raise ValueError("Oversized command line")
            result.append(line.decode("ascii").rstrip("\r"))
        if len(self.buffer) > self.limit:
            raise ValueError("Unterminated command line")
        return result


class JpegFrames:
    def __init__(self, limit=2_000_000):
        self.buffer = bytearray()
        self.length = None
        self.limit = limit

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while True:
            if self.length is None:
                if len(self.buffer) < 4:
                    break
                self.length = struct.unpack("<I", self.buffer[:4])[0]
                del self.buffer[:4]
                if not 4 <= self.length <= self.limit:
                    raise ValueError("Malformed JPEG length; reconnect required")
            if len(self.buffer) < self.length:
                break
            frames.append(bytes(self.buffer[:self.length]))
            del self.buffer[:self.length]
            self.length = None
        return frames

    def eof(self):
        if self.buffer or self.length is not None:
            raise ValueError("Truncated JPEG frame")


def decode_jpeg(data):
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError("Corrupt JPEG markers")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "JPEG" or image.width * image.height > 4_000_000:
            raise ValueError("Unexpected image format or dimensions")
        image.load()
        return image.convert("RGB")


def distance_value(value):
    if isinstance(value, bool):
        return None
    try:
        distance = float(value)
        if math.isfinite(distance) and 0 < distance <= 300:
            return distance
    except (TypeError, ValueError):
        pass
    return None


@dataclass(frozen=True)
class Frame:
    jpeg: bytes
    received_at: float
    sequence: int


class LatestFrame:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.frame = None
        self.sequence = 0

    def put(self, jpeg):
        decode_jpeg(jpeg)  # Invalid data never refreshes freshness.
        with self.lock:
            self.sequence += 1
            self.frame = Frame(jpeg, self.clock(), self.sequence)

    def clear(self):
        with self.lock:
            self.frame = None

    def get(self, max_age, after=-1):
        with self.lock:
            f = self.frame
            return f if (f and 0 <= self.clock() - f.received_at <= max_age
                         and f.received_at > after) else None
