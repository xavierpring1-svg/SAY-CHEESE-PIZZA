import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from jarvis.assistant import Assistant
from jarvis.core import Store, parse_command
from jarvis.ui import Window


@pytest.mark.parametrize("command,action,argument", [
    ('Hey Jarvis, play "Bohemian Rhapsody"', "spotify_play_song", "Bohemian Rhapsody"),
    ('play “Bohemian Rhapsody by Queen” on Spotify', "spotify_play_song", "Bohemian Rhapsody by Queen"),
    ("please play Hello by Adele", "spotify_play_song", "Hello by Adele"),
    ("play 'What's Up?'", "spotify_play_song", "What's Up?"),
    ("search Spotify for Queen", "spotify_search", "Queen"),
    ("play music", "spotify", "play"),
    ('search Chrome for "weather tomorrow"', "chrome_search", "weather tomorrow"),
    ("search in Chrome for pizza near me", "chrome_search", "pizza near me"),
    ("Chrome search for science news", "chrome_search", "science news"),
    ("type in the search bar Pizza Near Me", "chrome_type", "Pizza Near Me"),
    ("write in the Chrome search bar fish & chips", "chrome_type", "fish & chips"),
    ("type in Chrome https://example.com", "chrome_type", "https://example.com"),
    ("search that", "chrome_submit", ""),
    ("search it", "chrome_submit", ""),
    ("search the web for chrome extensions", "search_web", "chrome extensions"),
])
def test_v11_command_routing(command, action, argument):
    assert parse_command(command) == (action, argument)


class Speaker:
    def say(self, text):
        pass


def test_song_and_chrome_commands_reach_the_correct_adapter(tmp_path, monkeypatch):
    assistant = Assistant(Store(tmp_path), None, Speaker())
    calls = []
    monkeypatch.setattr(assistant.spotify, "play", lambda value, **kwargs: calls.append(("song", value)) or "Playing the requested track.")
    monkeypatch.setattr(assistant.spotify, "search", lambda value: calls.append(("spotify_search", value)) or "Opened results.")
    monkeypatch.setattr(assistant.chrome, "search", lambda value: calls.append(("chrome_search", value)) or "Searching Chrome.")
    monkeypatch.setattr(assistant.chrome, "type_search", lambda value: calls.append(("chrome_type", value)) or "Typed in Chrome.")
    monkeypatch.setattr(assistant.chrome, "submit_search", lambda: calls.append(("chrome_submit", "")) or "Search submitted.")
    for command in ["play Hello by Adele", "search Spotify for Adele", "search Chrome for weather",
                    "type in the search bar fish & chips", "search that"]:
        assistant.execute(*parse_command(command))
    assert calls == [("song", "Hello by Adele"), ("spotify_search", "Adele"),
                     ("chrome_search", "weather"), ("chrome_type", "fish & chips"), ("chrome_submit", "")]


def test_british_voice_choice_survives_ui_save_and_restart(tmp_path):
    qt = QApplication.instance() or QApplication([])
    store = Store(tmp_path)
    assert store.settings["speech_engine"] == "neural"
    window = Window(store, start_workers=False)
    combo = window.settings_widgets["speech_engine"]
    assert combo.currentData() == "neural"
    combo.setCurrentIndex(combo.findData("windows"))
    window.save_settings()
    assert Store(tmp_path).settings["speech_engine"] == "windows"
    combo.setCurrentIndex(combo.findData("neural"))
    window.save_settings()
    assert Store(tmp_path).settings["speech_engine"] == "neural"
    window.quitting = True
    window.close()
    qt.processEvents()


def test_followup_wake_phrase_preserves_chrome_focus_and_music(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    window = Window(Store(tmp_path), start_workers=False)
    window.show()
    qt.processEvents()
    events = []
    monkeypatch.setattr(window, "showNormal", lambda: events.append("show"))
    monkeypatch.setattr(window, "raise_", lambda: events.append("raise"))
    monkeypatch.setattr(window, "activateWindow", lambda: events.append("activate"))
    monkeypatch.setattr(window.speaker, "say", lambda text: events.append(text))
    monkeypatch.setattr(window.assistant, "autoplay", lambda: events.append("autoplay"))
    # Repeated 'Hey Jarvis' during Chrome dictation must keep Chrome foreground.
    window.wake("voice")
    assert events == []
    window.asleep = True
    window.wake("voice")
    assert events == ["show", "raise", "activate", "At your service, boss.", "autoplay"]
    window.quitting = True
    window.close()
    qt.processEvents()
