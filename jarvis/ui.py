from __future__ import annotations

import datetime
import html
import math
import os
import threading
import time

import psutil
from PySide6.QtCore import Qt, QTimer, QPointF, Signal, QObject
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QIcon, QPixmap, QCloseEvent
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextBrowser, QStackedWidget, QScrollArea, QFrame,
    QCheckBox, QSlider, QComboBox, QFormLayout, QSpinBox, QListWidget, QListWidgetItem,
    QSystemTrayIcon, QMenu, QFileDialog, QMessageBox, QDoubleSpinBox)

from .core import Store, ROOT
from .windows import Apps, IS_WINDOWS, gpu_usage
from .voice import Speaker, Listener, available_voices
from .assistant import Assistant, HELP
from .model import model_path, ModelInstaller
from . import __version__

STYLE = """
* { font-family: 'Segoe UI'; font-size: 13px; color: #d7e8f2; }
QMainWindow, QWidget#shell { background: #090f17; }
QWidget#settingsPage { background: #090f17; }
QWidget#sidebar { background: #0d1621; border-right: 1px solid #203142; }
QLabel#brand { font-size: 25px; font-weight: 700; letter-spacing: 5px; color: #56ddeb; }
QLabel#eyebrow { color: #65839b; font-size: 10px; letter-spacing: 2px; }
QLabel#title { font-size: 27px; font-weight: 600; }
QLabel#subtitle { color: #7e9bb1; }
QLabel#clock { font-size: 30px; font-weight: 300; color: #e9faff; }
QLabel#number { font-size: 21px; font-weight: 600; }
QFrame#card { background: #0f1b28; border: 1px solid #203448; border-radius: 13px; }
QPushButton { background: #152433; border: 1px solid #294257; border-radius: 8px; padding: 10px 15px; }
QPushButton:hover { background: #1b3545; border-color: #54d8e7; }
QPushButton:pressed { background: #224d59; }
QPushButton#primary { background: #44cede; color: #06151c; font-weight: 700; border: 0; }
QPushButton#nav { text-align: left; background: transparent; border: 0; padding: 13px 18px; color: #8aa5ba; }
QPushButton#nav:checked { background: #16303f; color: #60e2ec; border-left: 3px solid #60e2ec; border-radius: 4px; }
QPushButton#small { padding: 6px 12px; }
QLineEdit, QTextBrowser, QComboBox, QSpinBox, QDoubleSpinBox { background: #0a141f; border: 1px solid #2a4054; border-radius: 8px; padding: 10px; selection-background-color: #236a7a; }
QLineEdit:focus { border-color: #51d6e5; }
QTextBrowser { padding: 15px; }
QScrollArea, QListWidget { background: transparent; border: 0; }
QScrollBar:vertical { background: #101b27; width: 8px; }
QScrollBar::handle:vertical { background: #2c4c60; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QCheckBox { spacing: 10px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #426075; border-radius: 4px; background: #0a1722; }
QCheckBox::indicator:checked { background: #43cddd; }
QSlider::groove:horizontal { height: 4px; background: #263e50; border-radius: 2px; }
QSlider::handle:horizontal { background: #57dae6; width: 13px; margin: -5px 0; border-radius: 6px; }
QMenu { background: #101f2c; border: 1px solid #29475c; }
QMenu::item { padding: 10px 22px; }
QMenu::item:selected { background: #214457; }
QToolTip { background: #15293a; color: #d8f1fa; border: 1px solid #3f6479; }
"""


def label(text, name=None):
    result = QLabel(text)
    if name:
        result.setObjectName(name)
    return result


def button(text, callback=None, primary=False):
    result = QPushButton(text)
    if primary:
        result.setObjectName("primary")
    if callback:
        result.clicked.connect(callback)
    return result


def card():
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 17, 20, 17)
    return frame, layout


class Reactor(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(280, 255)
        self.setMaximumHeight(310)
        self.phase = 0
        self.amplitude = 0
        self.mode = "STANDING BY"
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(40)

    def animate(self):
        self.phase = (self.phase + 0.65) % 360
        self.amplitude *= 0.93
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2 - 8)
        radius = min(self.width(), self.height()) * 0.37
        cyan = QColor("#56dfea")
        for offset, alpha in [(13, 12), (8, 20), (4, 30)]:
            painter.setPen(QPen(QColor(60, 210, 230, alpha), offset * 2))
            painter.drawEllipse(center, radius * .65, radius * .65)
        for scale, speed, width in [(1, 1, 2), (.87, -1.3, 1), (.67, .55, 3)]:
            r = radius * scale
            painter.setPen(QPen(QColor("#193c4e"), width))
            painter.drawEllipse(center, r, r)
            painter.setPen(QPen(cyan, width))
            rect = (int(center.x()-r), int(center.y()-r), int(r*2), int(r*2))
            for start in [0, 120, 240]:
                painter.drawArc(*rect, int((start+self.phase*speed)*16), 70*16)
        for i in range(48):
            angle = math.radians(i*7.5 + self.phase * .15)
            r = radius * 1.1
            length = 5 + (9 if i%4 == 0 else 0) + min(self.amplitude*150, 22)
            painter.setPen(QPen(QColor("#38697c"), 2))
            painter.drawLine(QPointF(center.x()+math.cos(angle)*r, center.y()+math.sin(angle)*r),
                             QPointF(center.x()+math.cos(angle)*(r+length), center.y()+math.sin(angle)*(r+length)))
        painter.setPen(QPen(cyan, 2))
        inner = radius * .37
        points = [QPointF(center.x()+math.cos(math.radians(270+i*120))*inner,
                         center.y()+math.sin(math.radians(270+i*120))*inner) for i in range(3)]
        painter.setBrush(QColor(53, 193, 222, 25))
        painter.drawPolygon(points)
        painter.setBrush(QColor("#78edfa"))
        painter.drawEllipse(center, 4, 4)
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor("#76a6bb"))
        painter.drawText(0, self.height()-24, self.width(), 24, Qt.AlignmentFlag.AlignCenter, self.mode)


class Telemetry(QObject):
    gpu = Signal(object, str)


class Window(QMainWindow):
    def __init__(self, store=None, start_workers=True):
        super().__init__()
        self.store = store or Store()
        self.apps = Apps(self.store)
        self.speaker = Speaker(self.store)
        self.listener = Listener(self.store, self.speaker)
        self.assistant = Assistant(self.store, self.apps, self.speaker)
        self.asleep = False
        self.quitting = False
        self.gpu_value = None
        self.gpu_busy = False
        self.telemetry = Telemetry()
        self.telemetry.gpu.connect(self.gpu_updated)
        self.setWindowTitle(f"JARVIS {__version__} · Desktop Assistant")
        self.resize(1160, 790)
        self.setMinimumSize(950, 680)
        self.setWindowIcon(self.make_icon())
        shell = QWidget()
        shell.setObjectName("shell")
        self.setCentralWidget(shell)
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(205)
        sidebar = QVBoxLayout(side)
        sidebar.setContentsMargins(22, 30, 18, 24)
        sidebar.addWidget(label("J.A.R.V.I.S.", "brand"))
        sidebar.addWidget(label("DESKTOP ASSISTANT", "eyebrow"))
        sidebar.addSpacing(38)
        self.nav_buttons = []
        for index, name in enumerate(["◈  Command centre", "✓  My tasks", "▦  Applications", "⚙  Settings"]):
            nav = button(name)
            nav.setObjectName("nav")
            nav.setCheckable(True)
            nav.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            self.nav_buttons.append(nav)
            sidebar.addWidget(nav)
        sidebar.addStretch()
        self.state_label = label("●  ONLINE", "subtitle")
        sidebar.addWidget(self.state_label)
        sidebar.addWidget(label(f"WINDOWS · v{__version__}", "eyebrow"))
        sidebar.addSpacing(15)
        sidebar.addWidget(button("☾  Sleep mode", self.sleep))
        sidebar.addWidget(button("Quit JARVIS", self.quit))
        root.addWidget(side)

        content = QVBoxLayout()
        content.setContentsMargins(30, 24, 30, 23)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("At your service.", "title"))
        titles.addWidget(label("Your desktop. Your voice. Your command.", "subtitle"))
        header.addLayout(titles)
        header.addStretch()
        clock_box = QVBoxLayout()
        self.clock_label = label("", "clock")
        self.date_label = label("", "subtitle")
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        clock_box.addWidget(self.clock_label)
        clock_box.addWidget(self.date_label)
        header.addLayout(clock_box)
        content.addLayout(header)
        content.addSpacing(20)
        stats = QHBoxLayout()
        self.stat_labels = {}
        for title in ["CPU", "GPU", "MEMORY"]:
            frame, layout = card()
            layout.addWidget(label(title + " UTILISATION", "eyebrow"))
            value = label("—", "number")
            self.stat_labels[title] = value
            layout.addWidget(value)
            stats.addWidget(frame)
        content.addLayout(stats)
        self.stack = QStackedWidget()
        self.build_dashboard()
        self.build_tasks()
        self.build_apps()
        self.build_settings()
        content.addWidget(self.stack, 1)
        root.addLayout(content, 1)
        self.navigate(0)

        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("JARVIS · Say Hey Jarvis or clap twice")
        tray_menu = QMenu()
        tray_menu.addAction("Open JARVIS", lambda: self.wake("manual"))
        tray_menu.addAction("Sleep mode", self.sleep)
        tray_menu.addSeparator()
        tray_menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(lambda reason: self.wake("manual") if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.assistant.response.connect(lambda text: self.add_message("JARVIS", text))
        self.assistant.user_message.connect(lambda text: self.add_message("YOU", text))
        self.assistant.changed_tasks.connect(self.refresh_tasks)
        self.assistant.sleep_requested.connect(self.sleep)
        self.assistant.wake_requested.connect(self.wake)
        self.assistant.busy.connect(lambda busy: self.set_mode("PROCESSING" if busy else "LISTENING"))
        self.listener.wake.connect(self.wake)
        self.listener.command.connect(self.assistant.submit)
        self.listener.status.connect(self.microphone_status.setText)
        self.listener.status.connect(lambda text: self.retry_voice.setVisible("unavailable" in text.lower()))
        self.listener.transcript.connect(lambda text: self.heard_label.setText("Heard: " + text))
        self.listener.level.connect(self.level_changed)
        self.speaker.speaking.connect(lambda speaking: self.set_mode("SPEAKING" if speaking else "LISTENING"))
        self.speaker.problem.connect(lambda text: self.add_message("SYSTEM", text))
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_stats)
        self.clock_timer.start(1000)
        self.gpu_timer = QTimer(self)
        self.gpu_timer.timeout.connect(self.poll_gpu)
        self.gpu_timer.start(5000)
        self.update_stats()
        self.refresh_tasks()
        self.add_message("JARVIS", "Welcome, boss. Say ‘Hey Jarvis’, clap twice, or type a command below. Your tasks stay saved on this PC. Type ‘help’ for commands.")
        if start_workers:
            self.speaker.start()
            self.assistant.start()
            self.start_voice()
            self.poll_gpu()
            if self.store.settings["start_sleeping"]:
                QTimer.singleShot(300, self.sleep)

    def make_icon(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("#091721"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#5be1ef"), 3))
        painter.drawEllipse(8, 8, 48, 48)
        painter.drawEllipse(16, 16, 32, 32)
        painter.setPen(QColor("#a6f7ff"))
        painter.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "J")
        painter.end()
        return QIcon(pixmap)

    def build_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 20, 0, 0)
        top = QHBoxLayout()
        reactor_card, reactor_layout = card()
        self.reactor = Reactor()
        reactor_layout.addWidget(self.reactor)
        reactor_card.setFixedWidth(335)
        top.addWidget(reactor_card)
        control_card, controls = card()
        controls.addWidget(label("VOICE LINK", "eyebrow"))
        controls.addWidget(label("Ready when you are.", "title"))
        self.microphone_status = label("Microphone initialising…", "subtitle")
        self.microphone_status.setWordWrap(True)
        controls.addWidget(self.microphone_status)
        self.retry_voice = button("Retry voice setup", self.start_voice)
        self.retry_voice.setObjectName("small")
        self.retry_voice.hide()
        controls.addWidget(self.retry_voice)
        self.heard_label = label("Wake word: Hey Jarvis  ·  Double clap: ON", "subtitle")
        self.heard_label.setWordWrap(True)
        controls.addWidget(self.heard_label)
        controls.addStretch()
        controls.addWidget(button("🎙  Listen to my next command", self.listen, True))
        controls.addSpacing(5)
        controls.addWidget(label("SPOTIFY DESKTOP CONTROLS", "eyebrow"))
        spotify_row = QHBoxLayout()
        for name, command in [("Previous", "previous song"), ("Play", "play spotify"), ("Pause", "pause music"), ("Next", "next song")]:
            b = button(name, lambda checked=False, text=command: self.assistant.submit(text))
            b.setObjectName("small")
            spotify_row.addWidget(b)
        controls.addLayout(spotify_row)
        top.addWidget(control_card, 1)
        layout.addLayout(top)
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        self.chat.setMinimumHeight(120)
        layout.addWidget(self.chat, 1)
        entry = QHBoxLayout()
        self.command_entry = QLineEdit()
        self.command_entry.setPlaceholderText('Try play "Hello by Adele" or search Chrome for weather')
        self.command_entry.returnPressed.connect(self.submit_entry)
        entry.addWidget(self.command_entry, 1)
        entry.addWidget(button("Send  ↗", self.submit_entry, True))
        layout.addLayout(entry)
        self.stack.addWidget(page)

    def build_tasks(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 20, 0, 0)
        layout.addWidget(label("Your next moves.", "title"))
        layout.addWidget(label('Say “add task” followed by the task. Complete by saying “complete task 1”.', "subtitle"))
        row = QHBoxLayout()
        self.task_entry = QLineEdit()
        self.task_entry.setPlaceholderText("What needs doing?")
        self.task_entry.returnPressed.connect(self.add_task)
        row.addWidget(self.task_entry, 1)
        row.addWidget(button("+ Add task", self.add_task, True))
        layout.addLayout(row)
        self.task_list = QListWidget()
        layout.addWidget(self.task_list, 1)
        self.stack.addWidget(page)

    def build_apps(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 20, 0, 0)
        layout.addWidget(label("Your applications.", "title"))
        layout.addWidget(label("Discovered from Start Menu and Windows app registrations. Double-click to launch.", "subtitle"))
        self.app_filter = QLineEdit()
        self.app_filter.setPlaceholderText("Find an app…")
        self.app_filter.textChanged.connect(self.refresh_apps)
        layout.addWidget(self.app_filter)
        self.app_list = QListWidget()
        self.app_list.itemDoubleClicked.connect(lambda item: self.assistant.submit("open " + item.text()))
        layout.addWidget(self.app_list, 1)
        layout.addWidget(button("+ Register an app shortcut", self.register_app))
        self.stack.addWidget(page)

    def build_settings(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 20, 10, 0)
        layout.addWidget(label("Make it yours.", "title"))
        layout.addWidget(label("Voice, activation, Spotify, and optional conversational AI.", "subtitle"))
        form = QFormLayout()
        form.setVerticalSpacing(15)
        options = self.store.settings
        self.settings_widgets = {}
        for key, text in [("wake_enabled", "Listen for Hey Jarvis"), ("clap_enabled", "Activate with two claps"),
                          ("spotify_on_wake", "Start Spotify when waking"), ("start_sleeping", "Open in sleep mode")]:
            widget = QCheckBox(text)
            widget.setChecked(options[key])
            self.settings_widgets[key] = widget
            form.addRow(widget)
        threshold = QDoubleSpinBox()
        threshold.setRange(.02, .95)
        threshold.setSingleStep(.02)
        threshold.setValue(options["clap_threshold"])
        threshold.setToolTip("Lower is more sensitive. Start at 0.16; increase if music triggers wake-ups.")
        self.settings_widgets["clap_threshold"] = threshold
        form.addRow("Clap threshold", threshold)
        microphone = QComboBox()
        microphone.addItem("Windows default input", -1)
        try:
            import sounddevice as sd
            for index, device in enumerate(sd.query_devices()):
                if device["max_input_channels"] > 0:
                    microphone.addItem(device["name"], index)
        except Exception:
            pass
        selected = microphone.findData(options["microphone"])
        microphone.setCurrentIndex(max(0, selected))
        self.settings_widgets["microphone"] = microphone
        form.addRow("Microphone (restart required)", microphone)
        engine = QComboBox()
        engine.addItem("British male · natural online voice", "neural")
        engine.addItem("Windows voice · offline", "windows")
        engine.setCurrentIndex(max(0, engine.findData(options["speech_engine"])))
        self.settings_widgets["speech_engine"] = engine
        form.addRow("Speech output", engine)
        voice = QComboBox()
        voice.addItem("Automatic · prefer British English", "")
        if options["voice"]:
            voice.addItem(options["voice"], options["voice"])
            voice.setCurrentIndex(1)
        # Voice enumeration is performed asynchronously when opening Settings.
        self.voice_combo = voice
        self.settings_widgets["voice"] = voice
        form.addRow("Offline / fallback voice", voice)
        rate = QSpinBox()
        rate.setRange(-10, 10)
        rate.setValue(options["speech_rate"])
        self.settings_widgets["speech_rate"] = rate
        form.addRow("Speech rate", rate)
        speech_volume = QSpinBox()
        speech_volume.setRange(0, 100)
        speech_volume.setValue(options["speech_volume"])
        self.settings_widgets["speech_volume"] = speech_volume
        form.addRow("Speech volume", speech_volume)
        form.addRow(button("Test voice", lambda: self.speaker.say("Good morning, boss. All systems are standing by.")))
        form.addRow(button("Windows voice settings", lambda: os.startfile("ms-settings:speech") if IS_WINDOWS else None))
        note = label("Natural voice: Ryan, British English. Requires internet and sends reply text to Microsoft's speech service. Microphone recognition stays offline. If unavailable, JARVIS uses your installed Windows voice. Install an English (United Kingdom) male Windows voice for a British offline voice.", "subtitle")
        note.setWordWrap(True)
        form.addRow(note)
        uri = QLineEdit(options["spotify_uri"])
        uri.setPlaceholderText("Optional spotify:playlist:… or spotify:track:…")
        self.settings_widgets["spotify_uri"] = uri
        form.addRow("Spotify wake URI", uri)
        provider = QComboBox()
        provider.addItems(["Local commands", "Ollama (local)", "OpenAI"])
        provider.setCurrentText(options["ai_provider"])
        provider.currentTextChanged.connect(self.provider_changed)
        self.settings_widgets["ai_provider"] = provider
        form.addRow("Conversational AI", provider)
        for key, title in [("ai_model", "AI model"), ("ollama_url", "Local Ollama address")]:
            entry = QLineEdit(options[key])
            self.settings_widgets[key] = entry
            form.addRow(title, entry)
        self.api_key_entry = QLineEdit()
        self.api_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_entry.setPlaceholderText("Optional API key · kept only for this session")
        form.addRow("OpenAI API key", self.api_key_entry)
        ai_note = label("Ollama: install Ollama and pull llama3.2 first. OpenAI requires your own API key and incurs usage charges. Cloud conversation sends the request and tool results to your provider. Audio recognition stays local.", "subtitle")
        ai_note.setWordWrap(True)
        form.addRow(ai_note)
        layout.addLayout(form)
        layout.addWidget(button("Save settings", self.save_settings, True))
        layout.addWidget(button("Install local conversational AI (Ollama)", self.install_ai))
        self.settings_status = label("", "subtitle")
        layout.addWidget(self.settings_status)
        layout.addStretch()
        scroll.setWidget(page)
        self.stack.addWidget(scroll)

    def provider_changed(self, provider):
        if "ai_model" in self.settings_widgets:
            self.settings_widgets["ai_model"].setText("gpt-4.1-mini" if provider == "OpenAI" else "llama3.2")

    def install_ai(self):
        if IS_WINDOWS:
            os.startfile(str(ROOT / "Install Local AI.cmd"))
            self.settings_status.setText("After installation, choose Ollama (local), model llama3.2, then Save settings.")

    def start_voice(self):
        if self.listener.isRunning():
            return
        self.retry_voice.hide()
        if model_path(self.store):
            self.listener.start()
            return
        if hasattr(self, "model_installer") and self.model_installer.isRunning():
            return
        self.model_installer = ModelInstaller(self.store)
        self.model_installer.progress.connect(lambda percent: self.microphone_status.setText(f"Downloading offline voice model… {percent}%"))
        self.model_installer.ready.connect(self.start_voice)
        self.model_installer.failed.connect(self.voice_download_failed)
        self.microphone_status.setText("Downloading the 40 MB offline voice model…")
        self.model_installer.start()

    def voice_download_failed(self, message):
        self.microphone_status.setText(message)
        self.retry_voice.show()

    def save_settings(self):
        values = {}
        for key, widget in self.settings_widgets.items():
            if isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                values[key] = widget.value()
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentData() if key in {"microphone", "voice", "speech_engine"} else widget.currentText()
            else:
                values[key] = widget.text().strip()
        if values["spotify_uri"] and not values["spotify_uri"].startswith(("spotify:playlist:", "spotify:track:", "spotify:album:")):
            self.settings_status.setText("Use a Spotify playlist, track, or album URI.")
            return
        self.store.update_settings(values)
        self.assistant.api_key = self.api_key_entry.text().strip()
        self.settings_status.setText("Settings saved. Restart after changing microphones. API keys remain in memory only.")

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        for i, nav in enumerate(self.nav_buttons):
            nav.setChecked(i == index)
        if index == 1:
            self.refresh_tasks()
        elif index == 2:
            self.refresh_apps()
        elif index == 3 and self.voice_combo.count() == 1:
            # Avoid blocking the UI with a PowerShell launch.
            self.load_voices()

    def load_voices(self):
        # A small worker emits through a Qt signal, so widgets are only touched on the GUI thread.
        if not hasattr(self, "voice_events"):
            class VoiceEvents(QObject):
                found = Signal(list)
            self.voice_events = VoiceEvents()
            self.voice_events.found.connect(self.set_voices)
        threading.Thread(target=lambda: self.voice_events.found.emit(available_voices()), daemon=True).start()

    def set_voices(self, names):
        for name in names:
            if self.voice_combo.findData(name) < 0:
                self.voice_combo.addItem(name, name)
        index = self.voice_combo.findData(self.store.settings["voice"])
        if index >= 0:
            self.voice_combo.setCurrentIndex(index)

    def refresh_apps(self):
        query = self.app_filter.text().lower()
        self.app_list.clear()
        with self.apps.lock:
            names = sorted(self.apps.entries)
        for name in names:
            if query in name:
                self.app_list.addItem(name)

    def register_app(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose an app", "", "Windows applications (*.exe *.lnk)")
        if not path:
            return
        from pathlib import Path
        name = Path(path).stem.lower()
        with self.store.lock:
            self.store.data["apps"][name] = path
            self.store.save()
        with self.apps.lock:
            self.apps.entries[name] = path
        self.refresh_apps()

    def refresh_tasks(self):
        self.task_list.clear()
        tasks = self.store.tasks
        if not tasks:
            self.task_list.addItem("Your list is clear. Add your first task above or by voice.")
        for index, task in enumerate(tasks):
            item = QListWidgetItem()
            item.setSizeHint(__import__('PySide6.QtCore', fromlist=['QSize']).QSize(400, 64))
            widget = QWidget()
            row = QHBoxLayout(widget)
            done = QCheckBox(f"{index + 1}. {task['text']}")
            done.setChecked(task["done"])
            done.toggled.connect(lambda checked, task_id=task["id"]: self.store.toggle_task(task_id, checked))
            row.addWidget(done, 1)
            remove = button("Remove", lambda checked=False, task_id=task["id"]: self.remove_task(task_id))
            remove.setObjectName("small")
            row.addWidget(remove)
            self.task_list.addItem(item)
            self.task_list.setItemWidget(item, widget)

    def remove_task(self, task_id):
        self.store.remove_task(task_id)
        self.refresh_tasks()

    def add_task(self):
        text = self.task_entry.text().strip()
        if text:
            self.assistant.submit("add task " + text)
            self.task_entry.clear()

    def submit_entry(self):
        text = self.command_entry.text().strip()
        if text:
            self.assistant.submit(text)
            self.command_entry.clear()

    def add_message(self, sender, text):
        color = "#5edeea" if sender == "JARVIS" else "#9ab2c7"
        self.chat.append(f'<p style="color:{color};font-size:10px;letter-spacing:1px;margin-bottom:4px">{sender} · {datetime.datetime.now():%H:%M}</p><p style="color:#d8e8f2;line-height:1.5;margin-bottom:14px">{html.escape(text).replace(chr(10), "<br>")}</p>')
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())

    def set_mode(self, text):
        self.reactor.mode = "SLEEP MODE · WAKE WORD ARMED" if self.asleep else text
        self.reactor.update()

    def level_changed(self, value):
        self.reactor.amplitude = max(self.reactor.amplitude, value)

    def listen(self):
        if not self.listener.ready:
            self.add_message("SYSTEM", "Voice isn't ready yet. Check the microphone status and Settings; typed commands remain available.")
            return
        self.wake("manual")
        self.listener.listen_now()
        self.set_mode("LISTENING · SPEAK NOW")

    def wake(self, source="manual"):
        was_asleep = self.asleep
        bring_forward = was_asleep or source in {"clap", "manual", "command"} or not self.isVisible()
        self.asleep = False
        self.listener.set_sleep(False)
        if bring_forward:
            self.showNormal()
            self.raise_()
            self.activateWindow()
            if IS_WINDOWS:
                import ctypes
                foreground = ctypes.windll.user32.SetForegroundWindow
                foreground.argtypes = [ctypes.c_void_p]
                foreground.restype = ctypes.c_int
                foreground(int(self.winId()))
        self.state_label.setText("●  ONLINE")
        self.set_mode("LISTENING")
        if source == "clap" or (source == "voice" and bring_forward):
            greeting = "Good morning, boss." if source == "clap" else "At your service, boss."
            self.add_message("JARVIS", greeting)
            self.speaker.say(greeting)
            if self.store.settings["spotify_on_wake"]:
                self.assistant.autoplay()

    def sleep(self):
        self.asleep = True
        self.listener.set_sleep(True)
        self.state_label.setText("◌  SLEEP MODE")
        self.set_mode("SLEEP MODE")
        if self.tray.isVisible():
            self.hide()
            self.tray.showMessage("JARVIS is standing by", "Say Hey Jarvis or clap twice. Double-click the tray icon to open manually.", QSystemTrayIcon.MessageIcon.Information, 2500)
        else:
            self.showMinimized()

    def update_stats(self):
        now = datetime.datetime.now()
        self.clock_label.setText(now.strftime("%H:%M:%S"))
        self.date_label.setText(now.strftime("%A, %d %B %Y"))
        self.stat_labels["CPU"].setText(f"{psutil.cpu_percent():.0f}%")
        self.stat_labels["MEMORY"].setText(f"{psutil.virtual_memory().percent:.0f}%")

    def poll_gpu(self):
        if self.gpu_busy:
            return
        self.gpu_busy = True
        def work():
            value, name = gpu_usage()
            self.telemetry.gpu.emit(value, name)
        threading.Thread(target=work, daemon=True).start()

    def gpu_updated(self, value, name):
        self.gpu_busy = False
        self.gpu_value = value
        self.stat_labels["GPU"].setText("N/A" if value is None else f"{value:.0f}%")
        self.stat_labels["GPU"].setToolTip(name)

    def quit(self):
        self.quitting = True
        self.listener.stop()
        self.assistant.stop()
        self.speaker.stop()
        self.tray.hide()
        self.close()
        QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent):
        if self.quitting:
            event.accept()
        else:
            self.sleep()
            event.ignore()

    def cleanup(self):
        self.listener.stop()
        self.assistant.stop()
        self.speaker.stop()
        self.listener.wait(2500)
        self.assistant.wait(3000)
        self.speaker.wait(3000)
