import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import unittest
from unittest.mock import Mock
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from ai_driver.app import Runtime
from ai_driver.config import Config
from ai_driver.gui import Dashboard, KEYS
from ai_driver.protocol import STOP, motor_command
from tests.helpers import FakeClient


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.client = FakeClient()
        model = Mock(verified=True)
        model.status = dict(connection="Mock reachable", available="Installed", vision="TEST DOUBLE", result="SUCCESS")
        self.runtime = Runtime(Config(), self.client, model)
        self.window = Dashboard(self.runtime)
        self.window.show()
        self.app.processEvents()
        self.window.setFocus()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_camera_and_ultrasonic_render_synthetic_runtime_data(self):
        self.window.refresh()
        self.assertFalse(self.window.camera.pixmap().isNull())
        self.assertIn("100.0 cm", self.window.distance.text())
        self.assertEqual(self.window.distance_bar.value(), 100)
        self.client.data["distance"] = None
        self.client.frames.clear()
        self.window.refresh()
        self.assertIn("UNAVAILABLE", self.window.distance.text())
        self.assertIn("stale", self.window.camera.text())

    def test_buttons_send_exact_motor_bytes_and_release_stop(self):
        for action, button in self.window.buttons.items():
            with self.subTest(action=action):
                QTest.mousePress(button, Qt.LeftButton)
                self.assertEqual(self.client.wire[-1], motor_command(action, 1200, 0.35, "0123456789abcdef", self.client.sequence))
                QTest.mouseRelease(button, Qt.LeftButton)
                self.assertEqual(self.client.wire[-1], STOP)

    def test_keyboard_uses_same_paths_and_does_not_drive_while_typing(self):
        for key, action in KEYS.items():
            with self.subTest(key=key):
                self.window.setFocus()
                QTest.keyPress(self.window, key)
                self.assertEqual(self.client.moves[-1][0], action)
                QTest.keyRelease(self.window, key)
                self.assertEqual(self.client.wire[-1], STOP)
        count = len(self.client.moves)
        self.window.objective.setFocus()
        QTest.keyClicks(self.window.objective, "wasd")
        self.assertEqual(len(self.client.moves), count)
        QTest.keyClick(self.window.objective, Qt.Key_Escape)
        self.assertTrue(self.runtime.controller.emergency.is_set())

    def test_start_stop_toggle_objective_and_emergency_wiring(self):
        self.runtime.driver.start = Mock()
        self.window.objective.setText("Find the red object")
        QTest.mouseClick(self.window.start_button, Qt.LeftButton)
        self.runtime.driver.start.assert_called_once_with("Find the red object")
        self.assertTrue(self.window.ai_enabled.isChecked())
        self.window.ai_enabled.setChecked(False)
        self.assertEqual(self.client.wire[-1], STOP)
        QTest.mouseClick(self.window.emergency_button, Qt.LeftButton)
        self.assertTrue(self.runtime.controller.emergency.is_set())
        self.window.refresh()
        self.assertIn("EMERGENCY_STOP", self.window.status.text())
        QTest.mouseClick(self.window.reset_button, Qt.LeftButton)
        self.assertFalse(self.runtime.controller.emergency.is_set())

    def test_ai_on_checkbox_starts_same_objective_path(self):
        self.runtime.driver.start = Mock()
        self.window.ai_enabled.setChecked(True)
        self.runtime.driver.start.assert_called_once_with(self.window.objective.text())
        self.window.ai_enabled.setChecked(False)
        self.assertEqual(self.client.wire[-1], STOP)

    def test_ollama_test_button_is_off_gui_thread_and_emergency_works(self):
        entered, release = threading.Event(), threading.Event()

        def test_model():
            entered.set()
            release.wait(1)

        self.runtime.ollama.test.side_effect = test_model
        QTest.mouseClick(self.window.test_button, Qt.LeftButton)
        self.assertTrue(entered.wait(1))
        self.assertNotEqual(self.window.test_worker.ident, threading.get_ident())
        QTest.mouseClick(self.window.emergency_button, Qt.LeftButton)
        self.assertTrue(self.runtime.controller.emergency.is_set())
        self.assertEqual(self.client.wire[-1], STOP)
        release.set()
        self.window.test_worker.join(1)

    def test_stop_space_and_close_send_stop_before_connection_close(self):
        self.window.setFocus()
        QTest.keyClick(self.window, Qt.Key_Space)
        self.assertEqual(self.client.wire[-1], STOP)
        order = []
        self.client.stop = Mock(side_effect=lambda: order.append("STOP"))
        self.client.close = Mock(side_effect=lambda: order.append("CLOSE"))
        self.window.close()
        self.assertEqual(order[-1], "CLOSE")
        self.assertTrue(all(item == "STOP" for item in order[:-1]))
