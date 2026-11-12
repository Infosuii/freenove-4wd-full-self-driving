"""Composition root and ordered shutdown, independent of Qt."""
from .controller import Controller
from .driver import AIDriver
from .network import PiClient
from .ollama import Ollama


class Runtime:
    def __init__(self, config, client=None, ollama=None):
        self.config = config
        self.client = client or PiClient(config)
        self.ollama = ollama or Ollama(config)
        self.controller = Controller(self.client, config)
        self.driver = AIDriver(self.controller, self.ollama)
        self.closed = False

    def start(self):
        self.controller.start()
        self.client.start()

    def close(self):
        if not self.closed:
            self.closed = True
            self.driver.close()  # Cancel inference, STOP, join control loop.
            self.controller.close()  # STOP before connection teardown.
            self.client.wait_stopped(0.3)
            self.client.close()
