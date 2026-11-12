"""Development harness: ORIGINAL main.py workers + TCPServer; fake peripherals.

No physical hardware imports or network addresses other than loopback are used.
"""
import importlib.util
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
from tests.helpers import SERVER, Motor, jpeg

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication


class LocalPi:
    def __init__(self, command_port=0, video_port=0):
        self.app = QApplication.instance() or QApplication([])
        self.motor = Motor()
        self.distance = 100.0
        self.camera_ok = True
        self.car = SimpleNamespace(motor=self.motor, sonic=Mock(), close=Mock())
        self.car.sonic.get_fresh_sample.side_effect = lambda: (self.distance, time.monotonic())
        self.camera = Mock()

        def frame():
            time.sleep(0.025)
            return jpeg() if self.camera_ok else None

        self.camera.get_frame.side_effect = frame
        self.car_factory = Mock(return_value=self.car)
        modules = {"car": SimpleNamespace(Car=self.car_factory), "camera": SimpleNamespace(Camera=Mock(return_value=self.camera)),
                   "led": SimpleNamespace(Led=Mock()), "buzzer": SimpleNamespace(Buzzer=Mock())}
        with patch.dict("sys.modules", modules):
            spec = importlib.util.spec_from_file_location("tested_pi_main", SERVER / "main.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        options = SimpleNamespace(ai_safe=True, bind="127.0.0.1", command_port=command_port,
                                  video_port=video_port, watchdog=1.0, max_duration=0.75, threshold=30.0)
        with patch.object(module.mywindow, "set_process_led_running"):
            self.window = module.mywindow(options)
        self.window.timer.stop()
        # In production Pi and laptop are separate processes. This harness shares
        # Qt, so closing the laptop window must not invoke the Pi's sys.exit slot.
        self.app.lastWindowClosed.disconnect(self.window.close_application)
        self.command_port = self.window.tcp_server.command_server.server_socket.getsockname()[1]
        self.video_port = self.window.tcp_server.video_server.server_socket.getsockname()[1]
        self.guard = self.window.guard
        self.commands = []
        handle = self.guard.handle

        def recording_handle(line, address):
            self.commands.append(line.encode("ascii"))
            handle(line, address)

        self.guard.handle = recording_handle

    def disconnect_command(self):
        for sock in list(self.window.tcp_server.command_server.client_sockets):
            self.window.tcp_server.command_server.remove_client(sock)

    def close(self):
        self.window.guard.close()
        self.window.set_threading_cmd_receive(False)
        self.window.set_threading_car_task(False)
        self.window.set_threading_video_send(False)
        self.window.tcp_server.stop_tcp_servers()
        self.window.stop_car()
        self.window.deleteLater()
