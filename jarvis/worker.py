import threading
from PySide6.QtCore import QObject


class Worker(QObject):
    """Daemon worker whose signals deliver results to the GUI thread."""
    def start(self):
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def wait(self, milliseconds):
        thread = getattr(self, "_thread", None)
        if thread:
            thread.join(milliseconds / 1000)

    def isRunning(self):
        thread = getattr(self, "_thread", None)
        return bool(thread and thread.is_alive())
