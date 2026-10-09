import argparse
import sys

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from jarvis.ui import Window, STYLE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Render without microphone or Windows workers")
    parser.add_argument("--screenshot", help="Save a dashboard image and exit (use with --demo)")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    app.setApplicationName("JARVIS")
    app.setOrganizationName("JarvisDesktop")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    socket = QLocalSocket()
    if not args.demo:
        socket.connectToServer("jarvis-desktop-single-instance")
        if socket.waitForConnected(300):
            socket.write(b"show")
            socket.waitForBytesWritten(500)
            return 0
    server = QLocalServer()
    if not args.demo:
        QLocalServer.removeServer("jarvis-desktop-single-instance")
        server.listen("jarvis-desktop-single-instance")
    window = Window(start_workers=not args.demo)
    server.newConnection.connect(lambda: (server.nextPendingConnection().deleteLater(), window.wake("manual")))
    app.aboutToQuit.connect(window.cleanup)
    window.show()
    if args.screenshot:
        def capture():
            window.grab().save(args.screenshot)
            window.quitting = True
            app.quit()
        QTimer.singleShot(700, capture)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
