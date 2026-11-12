import logging
import threading
from PyQt5.QtCore import Qt, QTimer, QEvent
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton,
                             QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
                             QLineEdit, QPlainTextEdit, QProgressBar, QCheckBox)

log = logging.getLogger(__name__)
KEYS = {Qt.Key_W: "FORWARD", Qt.Key_Up: "FORWARD", Qt.Key_S: "BACKWARD",
        Qt.Key_Down: "BACKWARD", Qt.Key_A: "LEFT", Qt.Key_Left: "LEFT",
        Qt.Key_D: "RIGHT", Qt.Key_Right: "RIGHT", Qt.Key_Q: "ROTATE_LEFT", Qt.Key_E: "ROTATE_RIGHT"}


class Dashboard(QMainWindow):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self.last_frame = None
        self.held_key = None
        self.test_worker = None
        self.setWindowTitle("Freenove • Local AI Driver")
        self.resize(1180, 780)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        left, right = QVBoxLayout(), QVBoxLayout()
        layout.addLayout(left, 3)
        layout.addLayout(right, 2)
        self.camera = QLabel("Waiting for Pi camera…")
        self.camera.setAlignment(Qt.AlignCenter)
        self.camera.setMinimumSize(480, 360)
        self.camera.setStyleSheet("background:#10151e; color:#b8c3d6; border-radius:8px")
        left.addWidget(self.camera, 1)
        self.connection = QLabel()
        self.connection.setWordWrap(True)
        left.addWidget(self.connection)
        self.distance = QLabel("Distance: unavailable")
        self.distance.setStyleSheet("font-size:25px; font-weight:bold")
        left.addWidget(self.distance)
        self.distance_bar = QProgressBar()
        self.distance_bar.setRange(0, 300)
        self.distance_bar.setFormat("%v cm")
        left.addWidget(self.distance_bar)
        self.status = QLabel("IDLE")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(100)
        left.addWidget(self.status)
        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        self.events.document().setMaximumBlockCount(100)
        self.events.setMaximumHeight(140)
        left.addWidget(self.events)
        self.last_status = None

        manual = QGroupBox("Manual • short bounded bursts")
        grid = QGridLayout(manual)
        self.buttons = {}
        positions = {"FORWARD": (0, 1), "LEFT": (1, 0), "STOP": (1, 1), "RIGHT": (1, 2),
                     "BACKWARD": (2, 1), "ROTATE_LEFT": (3, 0), "ROTATE_RIGHT": (3, 2)}
        for action, position in positions.items():
            button = QPushButton(action.replace("_", " "))
            button.setMinimumHeight(42)
            button.pressed.connect(lambda a=action: self.manual(a))
            if action != "STOP":
                button.released.connect(self.stop)
            grid.addWidget(button, *position)
            self.buttons[action] = button
        right.addWidget(manual)
        right.addWidget(QLabel("WASD / arrows • Q/E inspect • Space STOP • Esc EMERGENCY\nRelease stops. Hold does not extend a burst."))

        ai_box = QGroupBox("Local autonomous driver")
        ai_layout = QVBoxLayout(ai_box)
        self.ai_enabled = QCheckBox("AI ON / OFF")
        self.ai_enabled.toggled.connect(self.toggle_ai)
        ai_layout.addWidget(self.ai_enabled)
        self.objective = QLineEdit("Explore the room safely.")
        self.objective.setMaxLength(1000)
        ai_layout.addWidget(QLabel("Objective"))
        ai_layout.addWidget(self.objective)
        ai_buttons = QHBoxLayout()
        self.start_button = QPushButton("Start AI")
        self.start_button.clicked.connect(self.start_ai)
        self.stop_button = QPushButton("Stop AI")
        self.stop_button.clicked.connect(self.stop)
        ai_buttons.addWidget(self.start_button)
        ai_buttons.addWidget(self.stop_button)
        ai_layout.addLayout(ai_buttons)
        right.addWidget(ai_box)

        ollama = QGroupBox("Ollama • laptop only")
        ollama_layout = QVBoxLayout(ollama)
        cfg = runtime.config
        self.model_label = QLabel(f"Model: {cfg.model}\nEndpoint: {cfg.ollama_host}:{cfg.ollama_port}")
        self.model_label.setWordWrap(True)
        ollama_layout.addWidget(self.model_label)
        self.ollama_status = QLabel("Untested")
        self.ollama_status.setWordWrap(True)
        ollama_layout.addWidget(self.ollama_status)
        self.test_button = QPushButton("Test Ollama (hi + image)")
        self.test_button.clicked.connect(self.test_ollama)
        ollama_layout.addWidget(self.test_button)
        right.addWidget(ollama)

        self.emergency_button = QPushButton("EMERGENCY STOP")
        self.emergency_button.setMinimumHeight(65)
        self.emergency_button.setStyleSheet("background:#b42332;color:white;font-size:22px;font-weight:bold")
        self.emergency_button.clicked.connect(self.emergency_stop)
        right.addWidget(self.emergency_button)
        self.reset_button = QPushButton("Reset emergency → MANUAL")
        self.reset_button.clicked.connect(runtime.controller.reset_emergency)
        right.addWidget(self.reset_button)
        right.addStretch()
        root.setStyleSheet("QGroupBox {font-weight:bold; margin-top:12px; padding-top:14px} QPushButton {padding:7px} QLineEdit {padding:8px}")
        QApplication.instance().installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(50)
        self.runtime.controller.pulse()
        self.refresh()

    def _off(self):
        self.ai_enabled.blockSignals(True)
        self.ai_enabled.setChecked(False)
        self.ai_enabled.blockSignals(False)

    def manual(self, action):
        self.runtime.driver.cancel.set()
        self._off()
        self.runtime.controller.manual(action)

    def stop(self):
        self._off()
        self.runtime.driver.stop()

    def emergency_stop(self):
        self.runtime.driver.cancel.set()
        self._off()
        self.runtime.controller.emergency_stop()

    def toggle_ai(self, enabled):
        if enabled:
            self.start_ai()
        else:
            self.stop()

    def start_ai(self):
        try:
            self.runtime.driver.start(self.objective.text())
            self.ai_enabled.blockSignals(True)
            self.ai_enabled.setChecked(True)
            self.ai_enabled.blockSignals(False)
        except Exception as exc:
            self.events.appendPlainText("AI start failed: " + str(exc))
            log.warning("AI start failed: %s", exc)
            self._off()

    def test_ollama(self):
        if self.test_worker and self.test_worker.is_alive():
            return
        self.stop()
        self.test_button.setEnabled(False)
        self.test_worker = threading.Thread(target=self.runtime.ollama.test, name="ollama-test", daemon=True)
        self.test_worker.start()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.WindowDeactivate and obj is self:
            self.held_key = None
            if self.runtime.controller.mode != "AUTONOMOUS":
                self.stop()
        if event.type() in (QEvent.KeyPress, QEvent.KeyRelease):
            key = event.key()
            if event.type() == QEvent.KeyPress and key == Qt.Key_Escape:
                self.emergency_stop()
                return True
            typing = isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit))
            if event.type() == QEvent.KeyRelease and key == self.held_key and not event.isAutoRepeat():
                self.held_key = None
                self.stop()
                return True
            if not typing and event.type() == QEvent.KeyPress and not event.isAutoRepeat():
                if key == Qt.Key_Space:
                    self.stop()
                    return True
                if key in KEYS:
                    self.held_key = key
                    self.manual(KEYS[key])
                    return True
        return super().eventFilter(obj, event)

    def refresh(self):
        self.runtime.controller.pulse()
        net = self.runtime.client.snapshot()
        state = self.runtime.controller.snapshot()
        cfg = self.runtime.config
        self.connection.setText(f"Pi {cfg.pi_host}:{cfg.command_port} • {net['command_status']}\nVideo :{cfg.video_port} • {net['video_status']}")
        age = self.runtime.controller.clock() - net["distance_time"]
        value = net["distance"] if age <= cfg.sensor_max_age else None
        self.distance.setText(f"Distance: {value:.1f} cm" if value is not None else "Distance: UNAVAILABLE")
        self.distance_bar.setValue(round(value) if value is not None else 0)
        color = "#c62c3a" if value is None or value <= cfg.ultrasonic_threshold else "#26865a"
        self.distance_bar.setStyleSheet(f"QProgressBar::chunk {{background:{color}}}")
        status = f"{state['mode']} • {state['phase']}\nAction: {state['action']}\n{state['status']}"
        self.status.setText(status)
        if status != self.last_status:
            self.events.appendPlainText(status.replace("\n", " | "))
            self.last_status = status
        if state["mode"] != "AUTONOMOUS":
            self._off()
        for action, button in self.buttons.items():
            button.setEnabled(action == "STOP" or net["ready"] and state["mode"] != "EMERGENCY_STOP")
        self.reset_button.setEnabled(state["mode"] == "EMERGENCY_STOP")
        model = self.runtime.ollama.status
        self.ollama_status.setText(f"Connection: {model['connection']}\nModel: {model['available']}\nVision: {model['vision']}\n{model['result']}")
        self.test_button.setEnabled(not self.test_worker or not self.test_worker.is_alive())
        frame = self.runtime.client.frames.get(cfg.frame_max_age)
        if frame and frame.sequence != self.last_frame:
            image = QImage.fromData(frame.jpeg, "JPEG")
            self.camera.setPixmap(QPixmap.fromImage(image).scaled(self.camera.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.last_frame = frame.sequence
        elif frame is None:
            self.camera.clear()
            self.camera.setText("Camera unavailable / stale")
            self.last_frame = None

    def closeEvent(self, event):
        self.timer.stop()
        QApplication.instance().removeEventFilter(self)
        self.runtime.close()
        event.accept()
