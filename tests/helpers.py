"""Explicit test doubles. Production never imports this module."""
import io
import json
from pathlib import Path
import sys
import threading
import time
from PIL import Image
from ai_driver.config import Config
from ai_driver.protocol import LatestFrame, motor_command, STOP

SERVER = Path(__file__).resolve().parents[1] / "Code" / "Server"
sys.path.insert(0, str(SERVER))


def jpeg(color="green"):
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buffer, "JPEG")
    return buffer.getvalue()


def response(action="FORWARD", duration=0.04, **extra):
    obj = dict(action=action, duration=0 if action == "STOP" else duration,
               confidence=0.8, status="Path is clear", goal_reached=False)
    obj.update(extra)
    return json.dumps(obj)


class Clock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Motor:
    def __init__(self):
        self.calls = []
        self.active = 0
        self.maximum_active = 0
        self.lock = threading.Lock()

    def set_motor_model(self, *duties):
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.active, self.maximum_active)
        self.calls.append(duties)
        with self.lock:
            self.active -= 1


class FakeClient:
    def __init__(self, config=None, clock=time.monotonic):
        self.config, self.clock = config or Config(), clock
        self.frames = LatestFrame(clock)
        self.frames.put(jpeg())
        self.wire = []
        self.moves = []
        self.on_event = lambda *args: None
        self.sequence = 0
        self.data = dict(ready=True, video_connected=True, last_reply=clock(), distance=100.0,
                         distance_time=clock(), command_status="TEST DOUBLE", video_status="SYNTHETIC")
        self.closed = False

    def snapshot(self):
        return self.data.copy()

    def fresh(self):
        self.frames.put(jpeg())
        self.data.update(last_reply=self.clock(), distance_time=self.clock())

    def move(self, action, duration):
        self.sequence += 1
        self.wire.append(motor_command(action, self.config.speed, duration, "0123456789abcdef", self.sequence))
        self.moves.append((action, duration))

    def stop(self):
        self.wire.append(STOP)

    def wait_stopped(self, timeout=0.5):
        return True

    def start(self):
        pass

    def close(self):
        self.closed = True


def wait_until(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for test condition")


class FreshFeed:
    def __init__(self, client):
        self.client = client
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.done.wait(0.015):
            self.client.fresh()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.done.set()
        self.thread.join()
