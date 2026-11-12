"""Explicit development-only GUI smoke run. ALL hardware and AI are synthetic.

Runs original server workers, real loopback TCP and HTTP, and the production GUI.
Never imports a physical peripheral implementation or connects to a real Pi.
"""
import argparse
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
from PyQt5.QtCore import QTimer
from tests.local_pi import LocalPi
from tests.helpers import response
from ai_driver.app import Runtime
from ai_driver.config import Config
from ai_driver.gui import Dashboard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument("--screenshot", help="Optional screenshot output path")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    pi = LocalPi()
    requests = []
    decisions = iter([response("FORWARD", duration=0.1), response("ROTATE_LEFT", duration=0.1),
                      response("STOP", goal_reached=True, status="Synthetic goal reached")])

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.reply({"models": [{"name": "synthetic-test-model"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            if self.path == "/api/show":
                self.reply({"capabilities": ["vision"]})
            else:
                content = next(decisions) if "format" in body else "Synthetic hello/red"
                self.reply({"done": True, "message": {"content": content}})

        def reply(self, obj):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(obj).encode())

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    http_thread = threading.Thread(target=http.serve_forever, daemon=True)
    http_thread.start()
    cfg = replace(Config(), pi_host="127.0.0.1", command_port=pi.command_port, video_port=pi.video_port,
                  model="synthetic-test-model", ollama_port=http.server_port, settle_time=0.03, loop_interval=0.03)
    runtime = Runtime(cfg)
    window = Dashboard(runtime)
    window.setWindowTitle("SIMULATION — synthetic camera, ultrasonic, motors and AI")
    window.objective.setText("Synthetic closed-loop smoke test")
    window.show()
    runtime.start()
    started = reached = False

    def progress():
        nonlocal started, reached
        if not started and runtime.ollama.verified and runtime.client.ready and runtime.client.frames.get(1) and runtime.client.distance:
            started = True
            window.start_ai()
        reached |= "Goal reported reached" in runtime.controller.status

    timer = QTimer()
    timer.timeout.connect(progress)
    timer.start(30)
    window.test_ollama()
    if args.screenshot:
        QTimer.singleShot(int(args.seconds * 700), lambda: window.grab().save(args.screenshot))
    QTimer.singleShot(int(args.seconds * 1000), window.close)
    try:
        pi.app.exec_()
        assert reached, "Synthetic objective did not complete"
        assert [d for d in pi.motor.calls if any(d)] == [(960,) * 4, (-960, -960, 960, 960)]
        assert pi.motor.calls[-1] == (0,) * 4
        assert len([b for b in requests if "format" in b]) == 3
        print("SMOKE PASS: GUI + original Pi workers + loopback TCP/HTTP + synthetic peripherals/model; 3 decisions, 2 bounded motor calls, final STOP")
    finally:
        timer.stop()
        runtime.close()
        http.shutdown()
        http.server_close()
        http_thread.join()
        pi.close()


if __name__ == "__main__":
    main()
