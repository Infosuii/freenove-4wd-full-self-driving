from dataclasses import dataclass, fields
import json
import math


@dataclass(frozen=True)
class Config:
    pi_host: str = "raspberrypi.local"
    command_port: int = 5000
    video_port: int = 8000
    ollama_host: str = "127.0.0.1"
    ollama_port: int = 11434
    model: str = "qwen2.5vl:7b"
    loop_interval: float = 0.2
    max_action_duration: float = 0.75
    manual_duration: float = 0.35
    watchdog_timeout: float = 1.0
    ultrasonic_threshold: float = 30.0
    sensor_max_age: float = 0.5
    frame_max_age: float = 1.0
    decision_max_age: float = 30.0
    inference_timeout: float = 30.0
    reconnect_interval: float = 1.0
    poll_interval: float = 0.2
    socket_timeout: float = 0.1
    settle_time: float = 0.15
    speed: int = 1200
    min_confidence: float = 0.6
    history_size: int = 12
    image_size: int = 448
    max_frame_bytes: int = 2_000_000

    def __post_init__(self):
        for f in fields(self):
            v = getattr(self, f.name)
            if f.type is str:
                if not isinstance(v, str) or not v.strip() or len(v) > 255:
                    raise ValueError(f"Invalid {f.name}")
            elif type(v) not in (int, float) or not math.isfinite(v) or v <= 0:
                raise ValueError(f"Invalid {f.name}")
            elif f.type is int and type(v) is not int:
                raise ValueError(f"{f.name} must be an integer")
        if any(not 1 <= p <= 65535 for p in (self.command_port, self.video_port, self.ollama_port)):
            raise ValueError("Invalid port")
        if not self.manual_duration <= self.max_action_duration <= self.watchdog_timeout <= 2:
            raise ValueError("Require manual_duration <= max_action_duration <= watchdog_timeout <= 2s")
        if not self.socket_timeout < self.poll_interval < self.sensor_max_age <= 1:
            raise ValueError("Require socket_timeout < poll_interval < sensor_max_age <= 1s")
        if self.speed > 1500 or self.ultrasonic_threshold >= 300:
            raise ValueError("Speed or ultrasonic threshold exceeds limits")
        if self.min_confidence > 1:
            raise ValueError("min_confidence must be in (0, 1]")
        if self.history_size > 50 or self.image_size > 1024 or self.max_frame_bytes > 8_000_000:
            raise ValueError("Memory/image limit exceeded")
        if any('/' in host or '@' in host for host in (self.pi_host, self.ollama_host)):
            raise ValueError("Hosts must be hostnames/IPs, without URL paths or credentials")

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
        return cls(**data)
