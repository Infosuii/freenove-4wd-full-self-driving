import logging
import math
import re
import socket
import threading
import time
from .protocol import HELLO, STOP, SONIC, Lines, JpegFrames, LatestFrame, motor_command, distance_value

log = logging.getLogger(__name__)


class PiClient:
    """Two Freenove sockets, bounded sends, no movement retry/command backlog."""
    def __init__(self, config, connect=socket.create_connection, clock=time.monotonic):
        self.config, self.connect, self.clock = config, connect, clock
        self.frames = LatestFrame(clock)
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.command_socket = self.video_socket = None
        self.ready = self.video_connected = False
        self.token = None
        self.sequence = 0
        self.stopped_ack = threading.Event()
        self.pending_stop = 0
        self.last_reply = 0.0
        self.distance, self.distance_time = None, 0.0
        self.command_status = "Disconnected"
        self.video_status = "Disconnected"
        self.on_event = lambda kind, value: None
        self.threads = []

    def start(self):
        for name, target in (("pi-command", self._commands), ("pi-video", self._video)):
            thread = threading.Thread(target=target, name=name, daemon=True)
            self.threads.append(thread)
            thread.start()

    def _send(self, data):
        with self.lock:
            if self.command_socket is None:
                raise ConnectionError("Pi command socket disconnected")
            self.command_socket.sendall(data)
            fields = data.decode("ascii").strip().split("#")
            if fields[0] == "CMD_MOTOR" and len(fields) == 8:
                fields[6] = "<session>"
            log.debug("tx %s", "#".join(fields))

    def move(self, action, duration):
        with self.lock:
            if not self.ready:
                raise ConnectionError("Guarded Pi handshake unavailable")
            self.sequence += 1
            data = motor_command(action, self.config.speed, duration, self.token, self.sequence)
            self._send(data)
            log.info("command_tx action=%s sequence=%s duration=%.3f", action, self.sequence, duration)

    def stop(self):
        with self.lock:
            self.pending_stop = self.sequence
            self.stopped_ack.clear()
            self._send(STOP)
        log.info("command_tx STOP")

    def wait_stopped(self, timeout=0.5):
        """ACK means the Pi invoked zero motor duties, not physical standstill."""
        acknowledged = self.stopped_ack.wait(timeout)
        log.info("stop_acknowledged=%s", acknowledged)
        return acknowledged

    def snapshot(self):
        with self.lock:
            return dict(ready=self.ready, video_connected=self.video_connected,
                        last_reply=self.last_reply, distance=self.distance,
                        distance_time=self.distance_time, command_status=self.command_status,
                        video_status=self.video_status)

    def _line(self, line):
        parts = line.split("#")
        event = None
        with self.lock:
            if len(parts) == 7 and parts[:3] == ["CMD_DRIVER", "READY", "1"]:
                limits = [float(p) for p in parts[4:]]
                if not re.fullmatch("[a-f0-9]{16}", parts[3]) or not all(math.isfinite(x) for x in limits):
                    raise ValueError("Malformed Pi handshake")
                wd, duration, threshold = limits
                if (not 0 < wd <= self.config.watchdog_timeout
                        or duration < self.config.max_action_duration or duration > wd
                        or threshold < self.config.ultrasonic_threshold or threshold >= 300):
                    raise ValueError("Pi safety limits incompatible with laptop config")
                self.token, self.ready = parts[3], True
                self.command_status = "Connected — guarded protocol v1"
                event = ("ready", True)
            elif len(parts) == 3 and parts[:2] == ["CMD_MODE", "3"]:
                self.distance = distance_value(parts[2])
                self.distance_time = self.clock()
                event = ("distance", self.distance)
            elif len(parts) == 4 and parts[:2] == ["CMD_DRIVER", "STOPPED"]:
                if not parts[3].isdigit():
                    raise ValueError("Malformed stop acknowledgement")
                if parts[2] == "requested" and int(parts[3]) == self.pending_stop:
                    self.stopped_ack.set()
                event = ("stopped", parts[2])
            elif len(parts) == 3 and parts[:2] == ["CMD_DRIVER", "ERROR"]:
                event = (parts[1].lower(), parts[2])
            elif len(parts) == 3 and parts[:2] == ["CMD_DRIVER", "ACTING"]:
                if not parts[2].isdigit():
                    raise ValueError("Malformed action acknowledgement")
            else:
                raise ValueError("Unexpected Pi telemetry")
            self.last_reply = self.clock()
        if event:
            self.on_event(*event)

    def _commands(self):
        while not self.closed.is_set():
            sock = None
            try:
                self.command_status = f"Connecting to {self.config.pi_host}:{self.config.command_port}"
                sock = self.connect((self.config.pi_host, self.config.command_port), timeout=1)
                sock.settimeout(self.config.socket_timeout)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                with self.lock:
                    self.command_socket = sock
                    self.sequence = 0
                    self.stopped_ack.clear()
                    self.last_reply = self.clock()
                self._send(STOP)
                self._send(HELLO)
                log.info("command connected; negotiating guard")
                parser, next_poll, opened = Lines(), 0.0, self.clock()
                while not self.closed.is_set():
                    now = self.clock()
                    if now >= next_poll:
                        self._send(SONIC)
                        next_poll = now + self.config.poll_interval
                    try:
                        data = sock.recv(4096)
                        if not data:
                            raise ConnectionError("Pi closed command connection")
                        for line in parser.feed(data):
                            self._line(line)
                    except socket.timeout:
                        pass
                    if not self.ready and self.clock() - opened > 2:
                        raise ConnectionError("Pi lacks guarded handshake; start main.py --ai-safe")
                    if self.clock() - self.last_reply > self.config.watchdog_timeout:
                        raise ConnectionError("Pi telemetry watchdog expired")
            except Exception as exc:
                self.command_status = f"Connection error: {exc}"
                if not self.closed.is_set():
                    log.warning("command disconnected: %s", exc)
            finally:
                with self.lock:
                    self.ready = False
                    self.token = self.command_socket = None
                    self.distance = None
                if sock:
                    sock.close()
                self.on_event("disconnected", self.command_status)
            self.closed.wait(self.config.reconnect_interval)

    def _video(self):
        while not self.closed.is_set():
            sock = None
            try:
                self.video_status = "Connecting camera"
                sock = self.connect((self.config.pi_host, self.config.video_port), timeout=1)
                sock.settimeout(self.config.frame_max_age)
                self.video_socket = sock
                parser = JpegFrames(self.config.max_frame_bytes)
                while not self.closed.is_set():
                    data = sock.recv(65536)
                    if not data:
                        parser.eof()
                        raise ConnectionError("Pi closed video connection")
                    for jpeg in parser.feed(data):
                        try:
                            self.frames.put(jpeg)
                        except (ValueError, OSError) as exc:
                            log.warning("discarded camera frame: %s", exc)
                            continue
                        self.video_connected = True
                        self.video_status = "Live JPEG stream"
            except Exception as exc:
                self.video_status = f"Camera error: {exc}"
                if not self.closed.is_set():
                    log.warning("video disconnected: %s", exc)
            finally:
                self.video_connected = False
                self.video_socket = None
                self.frames.clear()
                if sock:
                    sock.close()
                self.on_event("video_disconnected", self.video_status)
            self.closed.wait(self.config.reconnect_interval)

    def close(self):
        self.closed.set()
        for sock in (self.command_socket, self.video_socket):
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
        for thread in self.threads:
            thread.join(1.2)
        self.frames.clear()
        log.info("Pi connections/resources closed")
