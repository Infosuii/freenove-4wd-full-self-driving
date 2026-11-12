import argparse
import logging
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
import queue
import sys
from .config import Config


def main():
    parser = argparse.ArgumentParser(description="Freenove local AI driver")
    parser.add_argument("--config", default="driver.json")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--quit-after", type=float, help="GUI smoke test: close after N seconds")
    args = parser.parse_args()
    try:
        config = Config.load(args.config)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    messages = queue.SimpleQueue()
    handler = QueueHandler(messages)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if args.debug else logging.INFO)
    root.addHandler(handler)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s %(message)s")
    file = RotatingFileHandler("ai-driver.log", maxBytes=2_000_000, backupCount=3)
    console = logging.StreamHandler()
    for h in (file, console):
        h.setFormatter(formatter)
    listener = QueueListener(messages, file, console)
    listener.start()
    runtime = None
    try:
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QTimer
        from .app import Runtime
        from .gui import Dashboard
        app = QApplication(sys.argv[:1])
        runtime = Runtime(config)
        window = Dashboard(runtime)
        window.show()
        runtime.start()
        if args.quit_after:
            QTimer.singleShot(int(args.quit_after * 1000), window.close)
        return app.exec_()
    finally:
        if runtime:
            runtime.close()
        listener.stop()
        file.close()
        root.removeHandler(handler)


if __name__ == "__main__":
    sys.exit(main())
