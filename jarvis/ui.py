from __future__ import annotations

import datetime
import html
import os
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QIcon, QPixmap, QCloseEvent
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextBrowser, QStackedWidget, QScrollArea, QFrame,
    QCheckBox, QSlider, QComboBox, QFormLayout, QSpinBox, QListWidget, QListWidgetItem,
    QSystemTrayIcon, QMenu, QFileDialog, QMessageBox, QDoubleSpinBox, QProgressBar)

from .core import Store, ROOT
from .windows import Apps, IS_WINDOWS
from .voice import Speaker, Listener, available_voices
from .assistant import Assistant, HELP
from .model import model_path, ModelInstaller, MODELS, selected_model_key
from .ui_components import Hologram, MicrophoneMeter
from . import __version__

STYLE = """
* { font-family: 'Segoe UI'; font-size: 13px; color: #dce9f3; }
QMainWindow, QWidget#shell { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #06121d, stop:0.55 #030b13, stop:1 #081c2b); }
QWidget#settingsPage { background: #071420; }
QWidget#sidebar { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0a1d2a, stop:1 #05101c); border-right: 1px solid #173d4f; }
QLabel#brand { font-size: 31px; font-weight: 600; letter-spacing: 5px; color: #c5f5ff; }
QLabel#eyebrow { color: #6babbc; font-size: 10px; letter-spacing: 2px; font-weight: 500; }
QLabel#title { font-size: 26px; font-weight: 600; color: #eef8ff; }
QLabel#stateTitle { font-size: 19px; font-weight: 500; color: #d9f9ff; }
QLabel#subtitle { color: #91aabd; font-size: 12px; }
QLabel#clock { font-size: 29px; font-weight: 300; color: #dff6ff; }
QLabel#number { font-size: 25px; font-weight: 500; color: #e3f6ff; }
QLabel#statusPill { color: #6fdfd6; background: #102b35; border: 1px solid #234854; border-radius: 7px; padding: 7px 10px; font-size: 11px; }
QLabel#warning { color: #e5ba7a; font-size: 11px; }
QFrame#card { background: qlineargradient(x1:0, y1:0, x2:0.7, y2:1, stop:0 #0b2030, stop:1 #071420); border: 1px solid #1d4559; border-radius: 12px; }
QFrame#portraitPanel { background: #030d17; border: 1px solid #1c576e; border-radius: 12px; }
QFrame#conversation { background: #091724; border: 1px solid #1b3e51; border-radius: 12px; }
QFrame#musicPanel { background: #0b2130; border: 1px solid #204b5e; border-radius: 9px; }
QFrame#composer { background: #0b2131; border: 1px solid #2d657b; border-radius: 12px; }
QPushButton { background: #162b40; border: 1px solid #29475c; border-radius: 8px; padding: 10px 13px; color: #cfdfeb; }
QPushButton:hover { background: #1b3a50; border-color: #58c6d3; color: #edfaff; }
QPushButton:pressed { background: #244c61; }
QPushButton:disabled { color: #557083; background: #112033; border-color: #1c3346; }
QPushButton#primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #78e4e7, stop:1 #39bacf); color: #08212c; font-weight: 600; border: 1px solid #78e4e7; }
QPushButton#primary:hover { background: #90f1ef; }
QPushButton#nav { text-align: left; background: transparent; border: 0; padding: 13px 14px; color: #94abbe; border-radius: 8px; }
QPushButton#nav:hover { background: #152c3e; color: #d1eff8; }
QPushButton#nav:checked { background: #17354a; color: #b0f6fa; border: 1px solid #2a4c61; }
QPushButton#small { padding: 6px 10px; font-size: 11px; }
QPushButton#link { background: transparent; border: 0; color: #70d5e3; padding: 3px 0; font-size: 11px; text-align: left; }
QLineEdit, QTextBrowser, QComboBox, QSpinBox, QDoubleSpinBox { background: #0b1828; border: 1px solid #2a4258; border-radius: 8px; padding: 10px; selection-background-color: #236a7a; }
QLineEdit:focus, QComboBox:focus { border-color: #51cddc; }
QLineEdit#commandInput { background: transparent; border: 0; padding: 6px; font-size: 14px; }
QTextBrowser#chat { background: transparent; border: 0; padding: 2px; font-size: 13px; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView { background: #14283b; selection-background-color: #264b60; border: 1px solid #37566b; padding: 6px; }
QScrollArea, QListWidget { background: transparent; border: 0; }
QListWidget::item { border-bottom: 1px solid #1e3348; padding: 10px; }
QListWidget::item:selected { background: #19384b; border-radius: 6px; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 4px; }
QScrollBar::handle:vertical { background: #2b4d64; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QCheckBox { spacing: 10px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #466980; border-radius: 4px; background: #0b1b2b; }
QCheckBox::indicator:checked { background: #57cbd9; border-color: #86e7eb; }
QSlider::groove:horizontal { height: 4px; background: #263e50; border-radius: 2px; }
QSlider::handle:horizontal { background: #57dae6; width: 13px; margin: -5px 0; border-radius: 6px; }
QProgressBar { border: 1px solid #29475b; border-radius: 4px; background: #0b1b2a; color: #cee8f3; height: 11px; text-align: center; font-size: 10px; }
QProgressBar::chunk { background: #3db5c8; border-radius: 3px; }
QMenu { background: #101f2c; border: 1px solid #29475c; }
QMenu::item { padding: 10px 22px; }
QMenu::item:selected { background: #214457; }
QToolTip { background: #15293a; color: #d8f1fa; border: 1px solid #3f6479; padding: 5px; }
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
        self.processing = False
        self.preparing = False
        self.speaking = False
        self.listening_transition = False
        self.listen_request = 0
        self.last_transcript = ""
        self.input_warning = ""
        self.last_mic_level = 0.0
        self.voice_state = "Voice setup"
        self.brain_message = "Conversation setup"
        self.setWindowTitle(f"JARVIS {__version__} · Desktop Assistant")
        self.resize(1360, 920)
        self.setMinimumSize(1080, 780)
        self.setWindowIcon(self.make_icon())
        shell = QWidget()
        shell.setObjectName("shell")
        self.setCentralWidget(shell)
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(195)
        sidebar = QVBoxLayout(side)
        sidebar.setContentsMargins(18, 30, 16, 24)
        sidebar.setSpacing(8)
        sidebar.addWidget(label("JARVIS", "brand"))
        sidebar.addWidget(label("PERSONAL ASSISTANT", "eyebrow"))
        sidebar.addSpacing(33)
        self.nav_buttons = []
        for index, name in enumerate(["◈  Command centre", "✓  Tasks", "▦  Applications", "⚙  Settings"]):
            nav = button(name)
            nav.setObjectName("nav")
            nav.setCheckable(True)
            nav.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            self.nav_buttons.append(nav)
            sidebar.addWidget(nav)
        sidebar.addStretch()
        self.state_label = label("◌  VOICE SETUP", "statusPill")
        sidebar.addWidget(self.state_label)
        sidebar.addSpacing(4)
        sidebar.addWidget(label(f"WINDOWS 10 / 11  ·  {__version__}", "eyebrow"))
        sidebar.addSpacing(15)
        sidebar.addWidget(button("☾  Sleep mode", self.sleep))
        sidebar.addWidget(button("Quit JARVIS", self.quit))
        root.addWidget(side)

        content = QVBoxLayout()
        content.setContentsMargins(26, 25, 26, 22)
        content.setSpacing(14)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        titles.addWidget(label("J.A.R.V.I.S. / COMMAND CENTRE", "eyebrow"))
        self.page_title = label("At your service, boss.", "title")
        titles.addWidget(self.page_title)
        self.page_subtitle = label("Speak naturally. Make things happen.", "subtitle")
        titles.addWidget(self.page_subtitle)
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
        self.assistant.busy.connect(self.assistant_busy)
        self.listener.wake.connect(self.wake)
        self.listener.command.connect(self.assistant.submit)
        self.listener.status.connect(self.microphone_changed)
        self.listener.transcript.connect(self.transcript_changed)
        self.listener.level.connect(self.level_changed)
        self.speaker.speaking.connect(self.speech_changed)
        self.speaker.problem.connect(lambda text: self.add_message("SYSTEM", text))
        if hasattr(self.listener, "partial"):
            self.listener.partial.connect(self.partial_changed)
        if hasattr(self.listener, "state"):
            self.listener.state.connect(self.listener_state_changed)
        if hasattr(self.listener, "input_device"):
            self.listener.input_device.connect(self.input_device_changed)
        if hasattr(self.listener, "warning"):
            self.listener.warning.connect(self.input_warning_changed)
        if hasattr(self.speaker, "preparing"):
            self.speaker.preparing.connect(self.preparing_changed)
        if hasattr(self.assistant, "brain_status"):
            self.assistant.brain_status.connect(self.brain_status_changed)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        self.update_clock()
        self.refresh_tasks()
        self.add_message("JARVIS", "At your service, boss. Say ‘Hey Jarvis’, then tell me what you need. You can also click Listen or type below.")
        if start_workers:
            self.speaker.start()
            self.assistant.start()
            self.start_voice()
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        middle = QHBoxLayout()
        middle.setSpacing(15)

        reactor_card, reactor_layout = card()
        reactor_card.setObjectName("portraitPanel")
        reactor_card.setMinimumWidth(315)
        reactor_layout.setContentsMargins(16, 14, 16, 15)
        reactor_layout.setSpacing(8)
        portrait_header = QHBoxLayout()
        portrait_header.addWidget(label("J.A.R.V.I.S.", "eyebrow"))
        portrait_header.addStretch()
        portrait_header.addWidget(label("VOICE CONNECTION", "eyebrow"))
        reactor_layout.addLayout(portrait_header)
        self.reactor = Hologram()
        self.hologram = self.reactor
        reactor_layout.addWidget(self.reactor, 1)
        self.activity_title = label("Getting ready", "stateTitle")
        self.activity_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        reactor_layout.addWidget(self.activity_title)
        self.activity_hint = label("Preparing offline speech recognition…", "subtitle")
        self.activity_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.activity_hint.setWordWrap(True)
        reactor_layout.addWidget(self.activity_hint)
        self.mic_meter = MicrophoneMeter()
        reactor_layout.addWidget(self.mic_meter)
        mic_row = QHBoxLayout()
        self.mic_device_label = label("MICROPHONE", "eyebrow")
        self.mic_device_label.setMaximumWidth(290)
        self.mic_device_label.setToolTip("The active Windows microphone appears here after voice setup.")
        mic_row.addWidget(self.mic_device_label, 1)
        self.mic_level_label = label("0%", "subtitle")
        mic_row.addWidget(self.mic_level_label)
        reactor_layout.addLayout(mic_row)
        self.microphone_status = self.activity_hint
        self.warning_label = label("", "warning")
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        reactor_layout.addWidget(self.warning_label)
        self.retry_voice = button("Retry voice setup", self.start_voice)
        self.retry_voice.setObjectName("small")
        self.retry_voice.hide()
        reactor_layout.addWidget(self.retry_voice)
        actions = QHBoxLayout()
        self.listen_button = button("◉  Listen", self.listen, True)
        self.listen_button.setToolTip("Start a voice command. This also stops JARVIS's current reply.")
        actions.addWidget(self.listen_button, 1)
        self.stop_button = button("Stop reply", self.stop_reply)
        self.stop_button.setEnabled(False)
        actions.addWidget(self.stop_button)
        reactor_layout.addLayout(actions)
        middle.addWidget(reactor_card, 5)

        conversation = QFrame()
        conversation.setObjectName("conversation")
        chat_layout = QVBoxLayout(conversation)
        chat_layout.setContentsMargins(21, 19, 21, 17)
        chat_layout.setSpacing(11)
        conversation_header = QHBoxLayout()
        conversation_header.addWidget(label("CONVERSATION", "eyebrow"))
        conversation_header.addStretch()
        provider = self.store.settings.get("ai_provider", "Local commands")
        badge = "Local AI setup" if provider == "Built-in AI (local)" else "Ollama" if provider == "Ollama (local)" else "OpenAI" if provider == "OpenAI" else "Local commands"
        self.brain_badge = label(badge, "subtitle")
        self.brain_badge.setToolTip("Natural conversation can be enabled in Settings.")
        conversation_header.addWidget(self.brain_badge)
        chat_layout.addLayout(conversation_header)
        chat_layout.addWidget(label("Ask a question. Plan your day. Control your PC.", "subtitle"))
        self.chat = QTextBrowser()
        self.chat.setObjectName("chat")
        self.chat.setOpenExternalLinks(False)
        self.chat.setMinimumHeight(160)
        self.chat.document().setDefaultStyleSheet("p { line-height: 1.5; }")
        chat_layout.addWidget(self.chat, 1)
        self.partial_label = label("", "subtitle")
        self.partial_label.setWordWrap(True)
        self.partial_label.hide()
        chat_layout.addWidget(self.partial_label)
        heard_row = QHBoxLayout()
        self.heard_label = label("Say ‘Hey Jarvis’ to start a conversation.", "subtitle")
        self.heard_label.setWordWrap(True)
        self.heard_label.setTextFormat(Qt.TextFormat.PlainText)
        heard_row.addWidget(self.heard_label, 1)
        self.edit_heard_button = button("Edit words", self.edit_heard)
        self.edit_heard_button.setObjectName("link")
        self.edit_heard_button.hide()
        heard_row.addWidget(self.edit_heard_button)
        chat_layout.addLayout(heard_row)
        self.brain_progress = QProgressBar()
        self.brain_progress.setRange(0, 100)
        self.brain_progress.hide()
        chat_layout.addWidget(self.brain_progress)
        self.brain_download_label = label("", "subtitle")
        self.brain_download_label.setWordWrap(True)
        self.brain_download_label.setTextFormat(Qt.TextFormat.PlainText)
        self.brain_download_label.hide()
        chat_layout.addWidget(self.brain_download_label)
        music = QFrame()
        music.setObjectName("musicPanel")
        music_layout = QVBoxLayout(music)
        music_layout.setContentsMargins(12, 11, 12, 11)
        music_layout.setSpacing(8)
        music_heading = QHBoxLayout()
        music_heading.addWidget(label("SPOTIFY / SPOTX", "eyebrow"))
        music_heading.addStretch()
        music_heading.addWidget(label("Your music, on this PC", "subtitle"))
        music_layout.addLayout(music_heading)
        spotify_row = QHBoxLayout()
        spotify_row.setSpacing(5)
        self.music_buttons = {}
        for name, command in [("Previous", "previous song"), ("Replay", "replay song"),
                              ("Play", "play spotify"), ("Pause", "pause music"), ("Next", "next song")]:
            control = button(name, lambda checked=False, text=command: self.assistant.submit(text))
            control.setObjectName("small")
            control.setAccessibleName(name + " Spotify music")
            self.music_buttons[name] = control
            spotify_row.addWidget(control, 1)
        music_layout.addLayout(spotify_row)
        volume_row = QHBoxLayout()
        volume_row.addWidget(label("Set volume", "subtitle"))
        self.spotify_volume = QSlider(Qt.Orientation.Horizontal)
        self.spotify_volume.setRange(0, 100)
        self.spotify_volume.setValue(50)
        self.spotify_volume.setAccessibleName("Set Spotify or SpotX app volume")
        self.spotify_volume.setToolTip("Choose Spotify / SpotX's volume. Other apps keep their own volume.")
        self.spotify_volume_preview = label("50%", "subtitle")
        self.spotify_volume_preview.setMinimumWidth(35)
        self.spotify_volume.valueChanged.connect(lambda value: self.spotify_volume_preview.setText(f"{value}%"))
        self.spotify_volume.sliderReleased.connect(self.set_music_volume)
        volume_row.addWidget(self.spotify_volume, 1)
        volume_row.addWidget(self.spotify_volume_preview)
        # The button also lets keyboard users apply an exact selected level.
        apply_volume = button("Apply", self.set_music_volume)
        apply_volume.setObjectName("small")
        volume_row.addWidget(apply_volume)
        music_layout.addLayout(volume_row)
        chat_layout.addWidget(music)
        middle.addWidget(conversation, 6)
        layout.addLayout(middle, 1)

        composer = QFrame()
        composer.setObjectName("composer")
        entry = QHBoxLayout(composer)
        entry.setContentsMargins(14, 9, 9, 9)
        entry.setSpacing(12)
        entry.addWidget(label("›", "number"))
        self.command_entry = QLineEdit()
        self.command_entry.setObjectName("commandInput")
        self.command_entry.setPlaceholderText('Search Chrome, replay a song, or ask me anything…')
        self.command_entry.returnPressed.connect(self.submit_entry)
        entry.addWidget(self.command_entry, 1)
        entry.addWidget(button("Send  ↗", self.submit_entry, True))
        layout.addWidget(composer)
        suggestions = QHBoxLayout()
        suggestions.setSpacing(14)
        suggestions.addWidget(label("TRY ASKING", "eyebrow"))
        for title, command in [("Search Chrome", "search Chrome for "), ("Play a song", "play Hello by Adele"), ("Add a task", "add task ")]:
            shortcut = button(title, lambda checked=False, text=command: self.suggest_command(text))
            shortcut.setObjectName("link")
            suggestions.addWidget(shortcut)
        suggestions.addStretch()
        layout.addLayout(suggestions)
        self.stack.addWidget(page)

    def set_music_volume(self):
        self.assistant.submit(f"spotify volume {self.spotify_volume.value()}%")

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
        layout.addWidget(label("Fine-tune your microphone, natural voice, and conversation.", "subtitle"))
        form = QFormLayout()
        form.setVerticalSpacing(15)
        form.setHorizontalSpacing(22)
        options = self.store.settings
        self.settings_widgets = {}
        form.addRow(label("ACTIVATION", "eyebrow"))
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
        recognition = QComboBox()
        recognition.addItem("Accurate English · 128 MB download", "accurate")
        recognition.addItem("Compact English · 40 MB download", "compact")
        recognition.setCurrentIndex(max(0, recognition.findData(options.get("recognition_model", "compact"))))
        self.settings_widgets["recognition_model"] = recognition
        form.addRow("Recognition (restart required)", recognition)
        enhanced = QCheckBox("Enhanced offline transcription (Whisper)")
        enhanced.setChecked(options.get("enhanced_transcription", True))
        self.settings_widgets["enhanced_transcription"] = enhanced
        form.addRow(enhanced)
        gain = QDoubleSpinBox()
        gain.setRange(1.0, 4.0)
        gain.setSingleStep(.25)
        gain.setDecimals(2)
        gain.setSuffix(" ×")
        gain.setValue(options.get("microphone_gain", 1.0))
        gain.setToolTip("Increase for a quiet microphone. Reduce if the dashboard warns about clipping.")
        self.settings_widgets["microphone_gain"] = gain
        form.addRow("Microphone gain", gain)
        recognition_note = label("The compact model detects wake words quickly. Enhanced transcription downloads a second offline model (118 MB) to interpret your command. The 128 MB recognizer is another option to try. Watch the input meter while speaking and use ‘Edit words’ to correct a misheard command. Restart after changing recognition options.", "subtitle")
        recognition_note.setWordWrap(True)
        form.addRow(recognition_note)
        form.addRow(label("NATURAL VOICE", "eyebrow"))
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
        form.addRow(button("Test natural voice", lambda: self.speaker.say("Hello, boss. How can I help you today?")))
        form.addRow(button("Windows voice settings", lambda: os.startfile("ms-settings:speech") if IS_WINDOWS else None))
        note = label("Natural voice: Ryan, British English. Requires internet and sends reply text to Microsoft's speech service. Microphone recognition stays offline. If unavailable, JARVIS uses your installed Windows voice. Install an English (United Kingdom) male Windows voice for a British offline voice.", "subtitle")
        note.setWordWrap(True)
        form.addRow(note)
        form.addRow(label("MUSIC & CONVERSATION", "eyebrow"))
        uri = QLineEdit(options["spotify_uri"])
        uri.setPlaceholderText("Optional spotify:playlist:… or spotify:track:…")
        self.settings_widgets["spotify_uri"] = uri
        form.addRow("Spotify wake URI", uri)
        provider = QComboBox()
        provider.addItems(["Built-in AI (local)", "Local commands", "Ollama (local)", "OpenAI"])
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
        ai_note = label("Built-in AI downloads its local conversation model on first use (about 1.1 GB) and needs about 2 GB of free memory. It runs on this PC through a local-only connection and needs no API key. Ollama requires a separately installed model. OpenAI requires your own key and has usage charges; it receives your requests and tool results. Microphone audio stays local.", "subtitle")
        ai_note.setWordWrap(True)
        form.addRow(ai_note)
        layout.addLayout(form)
        layout.addWidget(button("Save settings", self.save_settings, True))
        layout.addWidget(button("Enable natural conversation", self.enable_conversation))
        layout.addWidget(button("Install local conversational AI (Ollama)", self.install_ai))
        self.settings_status = label("", "subtitle")
        layout.addWidget(self.settings_status)
        layout.addStretch()
        scroll.setWidget(page)
        self.stack.addWidget(scroll)

    def provider_changed(self, provider):
        if "ai_model" in self.settings_widgets:
            self.settings_widgets["ai_model"].setText("gpt-4.1-mini" if provider == "OpenAI" else "qwen2.5-1.5b-instruct" if provider == "Built-in AI (local)" else "llama3.2")

    def enable_conversation(self):
        self.settings_widgets["ai_provider"].setCurrentText("Built-in AI (local)")
        self.save_settings()
        if hasattr(self.assistant, "start_brain"):
            self.assistant.start_brain()
            self.settings_status.setText("Preparing local conversation. Follow its download progress in Command centre.")
            self.navigate(0)

    def install_ai(self):
        if IS_WINDOWS:
            os.startfile(str(ROOT / "Install Local AI.cmd"))
            self.settings_status.setText("After installation, choose Ollama (local), model llama3.2, then Save settings.")

    def start_voice(self):
        if self.listener.isRunning():
            return
        self.retry_voice.hide()
        if model_path(self.store):
            if self.store.settings.get("enhanced_transcription", True):
                from .transcription import WhisperTranscriber, TranscriptionInstaller
                if not WhisperTranscriber(self.store).ready():
                    if hasattr(self, "transcription_installer") and self.transcription_installer.isRunning():
                        return
                    self.transcription_installer = TranscriptionInstaller(self.store)
                    self.transcription_installer.progress.connect(lambda percent: self.microphone_status.setText(f"Preparing enhanced offline transcription… {percent}%"))
                    self.transcription_installer.ready.connect(self.start_voice)
                    self.transcription_installer.failed.connect(self.transcription_download_failed)
                    self.microphone_status.setText("Downloading enhanced offline transcription… 118 MB")
                    self.set_mode("VOICE SETUP")
                    self.transcription_installer.start()
                    return
            self.listener.start()
            return
        if hasattr(self, "model_installer") and self.model_installer.isRunning():
            return
        self.model_installer = ModelInstaller(self.store)
        self.model_installer.progress.connect(lambda percent: self.microphone_status.setText(f"Downloading offline voice model… {percent}%"))
        self.model_installer.ready.connect(self.start_voice)
        self.model_installer.failed.connect(self.voice_download_failed)
        spec = MODELS[selected_model_key(self.store)]
        self.microphone_status.setText(f"Downloading {spec.label.lower()} recognition… {spec.download_mb} MB")
        self.set_mode("VOICE SETUP")
        self.model_installer.start()

    def voice_download_failed(self, message):
        self.microphone_status.setText(message)
        self.voice_state = "Voice unavailable"
        self.set_mode("VOICE UNAVAILABLE")
        self.retry_voice.show()

    def transcription_download_failed(self, message):
        self.add_message("SYSTEM", message + " Basic offline recognition is still available. Restart JARVIS to retry enhanced transcription, or turn it off in Settings.")
        self.listener.start()

    def save_settings(self):
        values = {}
        for key, widget in self.settings_widgets.items():
            if isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                values[key] = widget.value()
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentData() if key in {"microphone", "voice", "speech_engine", "recognition_model"} else widget.currentText()
            else:
                values[key] = widget.text().strip()
        if values["spotify_uri"] and not values["spotify_uri"].startswith(("spotify:playlist:", "spotify:track:", "spotify:album:")):
            self.settings_status.setText("Use a Spotify playlist, track, or album URI.")
            return
        self.store.update_settings(values)
        self.assistant.api_key = self.api_key_entry.text().strip()
        self.settings_status.setText("Settings saved. Restart to apply microphone or recognition model changes. API keys stay in memory only.")

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        titles = [
            ("At your service, boss.", "Speak naturally. Make things happen."),
            ("A clear mind. A clear plan.", "Your tasks, saved on this PC."),
            ("Your desktop, connected.", "Find an application and ask JARVIS to open it."),
            ("Designed around you.", "Fine-tune the way we talk."),
        ]
        self.page_title.setText(titles[index][0])
        self.page_subtitle.setText(titles[index][1])
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
            item.setSizeHint(QSize(400, 64))
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
            if self.speaking or self.preparing:
                self.stop_reply()
            self.assistant.submit(text)
            self.command_entry.clear()

    def suggest_command(self, command):
        self.command_entry.setText(command)
        self.command_entry.setFocus()
        self.command_entry.setCursorPosition(len(command))

    def edit_heard(self):
        if self.last_transcript:
            self.suggest_command(self.last_transcript)

    def add_message(self, sender, text):
        color = "#7adce4" if sender == "JARVIS" else "#a3bacb" if sender == "YOU" else "#e5ba7a"
        background = "#132a3e" if sender == "JARVIS" else "#172538" if sender == "YOU" else "#2c2a2b"
        escaped = html.escape(str(text)).replace(chr(10), "<br>")
        self.chat.append(
            f'<p style="color:{color};font-size:10px;margin-top:10px;margin-bottom:6px">'
            f'{html.escape(sender)} &nbsp; · &nbsp; {datetime.datetime.now():%H:%M}</p>'
            f'<table width="100%" bgcolor="{background}" cellspacing="0" cellpadding="11"><tr><td>'
            f'<span style="color:#dfedf6;font-size:13px">{escaped}</span></td></tr></table>'
            '<p style="font-size:3px;margin:0">&nbsp;</p>'
        )
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())

    def set_mode(self, text):
        normalized = str(text).upper()
        self.reactor.mode = "SLEEP MODE" if self.asleep else normalized
        self.reactor.update()
        if self.asleep:
            title, badge = "Standing by", "◌  SLEEP MODE"
        elif normalized == "STOPPING REPLY":
            title, badge = "One moment", "◌  SWITCHING TO LISTEN"
        elif "UNAVAILABLE" in normalized:
            title, badge = "Voice unavailable", "◌  CHECK VOICE SETUP"
        elif self.speaking or "SPEAKING" in normalized:
            title, badge = "Speaking", "●  SPEAKING"
        elif self.preparing or "PREPARING" in normalized:
            title, badge = "Preparing reply", "◌  PREPARING REPLY"
        elif self.processing or any(word in normalized for word in ("PROCESSING", "THINKING")):
            title, badge = "Thinking", "◌  WORKING"
        elif any(word in normalized for word in ("TRANSCRIB", "RECOGNIZ", "UNDERSTAND")):
            title, badge = "Understanding", "◌  UNDERSTANDING"
        elif "SETUP" in normalized or not self.listener.ready:
            title, badge = "Getting ready", "◌  VOICE SETUP"
        elif "LISTENING" in normalized:
            title, badge = "Listening", "●  LISTENING"
        else:
            title, badge = "Ready when you are", "●  MICROPHONE READY"
        self.activity_title.setText(title)
        self.state_label.setText(badge)
        self.stop_button.setEnabled(self.speaking or self.preparing)

    def refresh_mode(self):
        mode = "STOPPING REPLY" if self.listening_transition else "SPEAKING" if self.speaking else "PREPARING REPLY" if self.preparing else "PROCESSING" if self.processing else self.voice_state
        self.set_mode(mode)

    def assistant_busy(self, busy):
        self.processing = bool(busy)
        self.refresh_mode()

    def speech_changed(self, speaking):
        self.speaking = bool(speaking)
        self.hologram.set_speaking(self.speaking)
        if speaking:
            self.partial_label.hide()
        self.refresh_mode()

    def preparing_changed(self, preparing):
        self.preparing = bool(preparing)
        self.refresh_mode()

    def microphone_changed(self, message):
        self.microphone_status.setText(message)
        failed = any(word in message.lower() for word in ("unavailable", "failed", "missing", "can't", "cannot"))
        self.retry_voice.setVisible(failed)
        if failed:
            self.voice_state = "Voice unavailable"
        elif self.listener.ready:
            self.voice_state = "Standby"
        self.refresh_mode()

    def listener_state_changed(self, state):
        self.voice_state = state
        self.refresh_mode()

    def input_device_changed(self, device):
        self.mic_device_label.setText(device)
        self.mic_device_label.setToolTip(device)

    def transcript_changed(self, text):
        self.last_transcript = text
        self.heard_label.setText("Heard: “" + text + "”")
        self.edit_heard_button.setVisible(bool(text))
        self.partial_label.clear()
        self.partial_label.hide()

    def partial_changed(self, text):
        self.partial_label.setText("Hearing: “" + text + "”…" if text else "")
        self.partial_label.setVisible(bool(text))

    def input_warning_changed(self, message):
        self.input_warning = message
        self.warning_label.setText(message)
        self.warning_label.setVisible(bool(message))
        self.mic_meter.feed(self.last_mic_level, "clip" in message.lower())

    def brain_status_changed(self, message, percent):
        self.brain_message = message
        self.brain_badge.setToolTip(message)
        lowered = message.lower()
        failed = any(word in lowered for word in ("failed", "unavailable", "error"))
        ready = not failed and "not ready" not in lowered and ("ready" in lowered or "available" in lowered)
        self.brain_badge.setText("Local conversation" if ready else "AI needs attention" if failed else "Preparing local AI")
        self.brain_progress.setVisible(not ready and not failed and percent < 100)
        self.brain_download_label.setText(message)
        self.brain_download_label.setVisible(not ready)
        if percent >= 0:
            self.brain_progress.setRange(0, 100)
            self.brain_progress.setValue(min(100, percent))
        else:
            self.brain_progress.setRange(0, 0)
        if ready:
            self.settings_status.setText("Local conversation is ready. Talk naturally or ask JARVIS to do something.")

    def level_changed(self, value):
        self.reactor.amplitude = max(self.reactor.amplitude, value)
        self.last_mic_level = float(value)
        self.mic_meter.feed(value, "clip" in self.input_warning.lower())
        self.mic_level_label.setText(f"{min(100, max(0, value * 100)):.0f}%")

    def stop_reply(self):
        if hasattr(self.speaker, "interrupt"):
            self.speaker.interrupt()
        self.speaking = False
        self.hologram.set_speaking(False)
        self.preparing = False
        self.refresh_mode()

    def listen(self):
        self.listen_request += 1
        request = self.listen_request
        was_speaking = (self.speaking or self.preparing or self.listening_transition
                        or self.speaker.active.is_set()
                        or time.monotonic() < getattr(self.speaker, "echo_until", 0))
        if was_speaking:
            self.listening_transition = True
            self.stop_reply()
            # Let playback and its room echo settle before asking the user to
            # speak. The listener discards that brief interval deliberately.
            QTimer.singleShot(300, lambda: self.begin_listening(request))
        else:
            self.begin_listening(request)

    def begin_listening(self, request):
        if self.quitting or request != self.listen_request:
            return
        self.listening_transition = False
        if not self.listener.ready:
            self.refresh_mode()
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
        self.voice_state = "Listening"
        self.refresh_mode()
        if source == "clap" or (source == "voice" and bring_forward):
            greeting = "Good morning, boss." if source == "clap" else "At your service, boss."
            self.add_message("JARVIS", greeting)
            self.speaker.say(greeting)
            if self.store.settings["spotify_on_wake"]:
                self.assistant.autoplay()

    def sleep(self):
        self.listen_request += 1
        self.listening_transition = False
        self.stop_reply()
        self.asleep = True
        self.listener.set_sleep(True)
        self.state_label.setText("◌  SLEEP MODE")
        self.set_mode("SLEEP MODE")
        if self.tray.isVisible():
            self.hide()
            self.tray.showMessage("JARVIS is standing by", "Say Hey Jarvis or clap twice. Double-click the tray icon to open manually.", QSystemTrayIcon.MessageIcon.Information, 2500)
        else:
            self.showMinimized()

    def update_clock(self):
        now = datetime.datetime.now()
        self.clock_label.setText(now.strftime("%H:%M:%S"))
        self.date_label.setText(now.strftime("%A, %d %B %Y"))

    def quit(self):
        self.quitting = True
        self.listen_request += 1
        self.listening_transition = False
        if hasattr(self, "model_installer"):
            self.model_installer.cancel()
        if hasattr(self, "transcription_installer"):
            self.transcription_installer.cancel()
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
        self.quitting = True
        self.listen_request += 1
        self.listening_transition = False
        if hasattr(self, "model_installer"):
            self.model_installer.cancel()
        if hasattr(self, "transcription_installer"):
            self.transcription_installer.cancel()
        self.listener.stop()
        self.assistant.stop()
        self.speaker.stop()
        self.listener.wait(2500)
        self.assistant.wait(3000)
        self.speaker.wait(3000)
