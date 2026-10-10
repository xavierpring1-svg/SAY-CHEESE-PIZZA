import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_CACHE_HOME", "/workspace/.cache")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from jarvis.core import Store, parse_command, ClapDetector
from jarvis.assistant import Assistant
from jarvis.voice import Listener
from jarvis.ui import Window, STYLE
from jarvis.model import download_model


@pytest.fixture(scope="session")
def qt():
    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(STYLE)
    return application


@pytest.mark.parametrize("text,expected", [
    ("Hey Jarvis add task buy milk", ("add_task", "buy milk")),
    ("add task: Finish My Project", ("add_task", "Finish My Project")),
    ("open chrome", ("open_app", "chrome")),
    ("start spotify", ("spotify", "play")),
    ("play music", ("spotify", "play")),
    ("pause spotify", ("spotify", "pause")),
    ("next song", ("spotify", "next")),
    ("previous track", ("spotify", "previous")),
    ("go to sleep", ("sleep", "")),
    ("volume 75 percent", ("volume", "75")),
    ("what time is it", ("clock", "what time is it")),
    ("what is the date", ("clock", "what is the date")),
    ("complete task 1", ("complete_task", "1")),
    ("Tell me a story", ("conversation", "Tell me a story")),
])
def test_commands(text, expected):
    assert parse_command(text) == expected


def test_tasks_survive_restart(tmp_path):
    store = Store(tmp_path)
    task = store.add_task("Buy groceries")
    store.toggle_task(task["id"], True)
    other = Store(tmp_path)
    assert other.tasks[0]["text"] == "Buy groceries"
    assert other.tasks[0]["done"] is True
    other.remove_task(task["id"])
    assert Store(tmp_path).tasks == []


def test_corrupt_storage_is_preserved(tmp_path):
    (tmp_path / "settings.json").write_text("damaged!")
    assert Store(tmp_path).tasks == []
    assert list(tmp_path.glob("settings-recovery-*.json"))[0].read_text() == "damaged!"


def clap():
    samples = np.zeros(512, dtype=np.float32)
    samples[150:156] = [.8, -.7, .4, -.3, .2, -.1]
    return samples


def test_double_clap_and_cooldown():
    detector = ClapDetector()
    silence = np.zeros(512)
    assert not detector.feed(clap(), 10)
    detector.feed(silence, 10.1)
    assert detector.feed(clap(), 10.4)
    detector.feed(silence, 10.5)
    assert not detector.feed(clap(), 10.8)
    detector.feed(silence, 13.2)
    assert not detector.feed(clap(), 13.3)
    detector.feed(silence, 13.4)
    assert detector.feed(clap(), 13.7)


def test_single_clap_echo_music_and_late_clap_do_not_wake():
    detector = ClapDetector()
    assert not detector.feed(clap(), 5)
    assert not detector.feed(clap(), 5.03)
    detector.feed(np.zeros(512), 5.1)
    assert not detector.feed(clap(), 6.2)
    tone = .8 * np.sin(np.arange(512) * .06)
    for i in range(40):
        assert not detector.feed(tone, 8+i*.032)


class FakeSpeaker:
    def __init__(self):
        import threading
        self.active = threading.Event()
        self.spoken = []
    def say(self, text):
        self.spoken.append(text)


def test_wake_word_sleep_gating_and_followup(qt, tmp_path):
    speaker = FakeSpeaker()
    listener = Listener(Store(tmp_path), speaker)
    listener.sleeping = True
    wakes, commands = [], []
    listener.wake.connect(wakes.append)
    listener.command.connect(commands.append)
    listener._text("add task ignore this while sleeping")
    assert not commands
    listener._text("hey jarvis add task buy milk")
    assert wakes == ["voice_command"]
    assert commands == ["add task buy milk"]
    listener._text("open chrome")
    assert commands[-1] == "open chrome"
    speaker.active.set()
    listener._text("add task assistant feedback")
    assert commands[-1] == "open chrome"


def test_assistant_actions_use_real_persistence(qt, tmp_path):
    store = Store(tmp_path)
    assistant = Assistant(store, None, FakeSpeaker())
    assert "Task added" in assistant.execute("add_task", "Plan tomorrow")
    assert "Plan tomorrow" in assistant.execute("list_tasks")
    assistant.execute("complete_task", "1")
    assert Store(tmp_path).tasks[0]["done"]
    with pytest.raises(ValueError):
        assistant.execute("remove_task", "99")
    assistant.execute("remove_task", "1")
    assert not store.tasks


def test_ui_tasks_sleep_wake_and_settings(qt, tmp_path, monkeypatch):
    store = Store(tmp_path)
    window = Window(store, start_workers=False)
    window.show()
    qt.processEvents()
    store.add_task("UI smoke test")
    window.navigate(1)
    assert window.task_list.count() == 1
    window.settings_widgets["clap_threshold"].setValue(.3)
    window.save_settings()
    assert Store(tmp_path).settings["clap_threshold"] == .3
    events = []
    monkeypatch.setattr(window.speaker, "say", lambda text: events.append(text))
    monkeypatch.setattr(window.assistant, "autoplay", lambda: events.append("spotify"))
    window.sleep()
    assert window.asleep
    assert window.listener.sleeping
    window.wake("clap")
    qt.processEvents()
    assert window.isVisible()
    assert not window.asleep
    assert events == ["Good morning, boss.", "spotify"]
    assert window.clock_label.text()
    assert not hasattr(window, "stat_labels")
    window.quitting = True
    window.close()


def test_download_rejects_unsafe_archive(tmp_path, monkeypatch):
    import io, zipfile
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../../escape.txt", "bad")
    class Response(io.BytesIO):
        headers = {}
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response(archive.getvalue()))
    with pytest.raises(ValueError, match="Unsafe"):
        download_model(tmp_path)
    assert not (tmp_path.parent.parent / "escape.txt").exists()
    assert not list(tmp_path.glob(".download-*"))


def test_spotify_session_control_reports_actual_result(monkeypatch):
    import asyncio
    import jarvis.windows as windows
    import jarvis.spotify_desktop as desktop
    calls = []
    class Session:
        async def try_play_async(self):
            calls.append("play")
            return True
        async def try_pause_async(self):
            calls.append("pause")
            return True
        async def try_skip_next_async(self):
            calls.append("next")
            return False
        async def try_skip_previous_async(self):
            calls.append("previous")
            return True
    spotify = windows.Spotify()
    async def session():
        return Session()
    monkeypatch.setattr(spotify, "_session", session)
    async def playback(_session):
        return desktop.PlaybackState("Spotify.exe", "Song", "Artist", True, 20)
    monkeypatch.setattr(desktop, "read_session_playback", playback)
    monkeypatch.setattr(os, "startfile", lambda uri: calls.append(uri), raising=False)
    assert "Playing" in asyncio.run(spotify._control("play"))
    assert calls == ["spotify:", "play"]
    assert "paused" in asyncio.run(spotify._control("pause"))
    with pytest.raises(RuntimeError, match="declined"):
        asyncio.run(spotify._control("next"))


def test_conversation_tool_calls_use_supported_actions(qt, tmp_path, monkeypatch):
    import io
    store = Store(tmp_path)
    store.update_settings({"ai_provider": "Ollama (local)"})
    assistant = Assistant(store, None, FakeSpeaker())
    responses = iter([
        {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {
            "name": "desktop_action", "arguments": {"action": "add_task", "argument": "Buy milk"}}}]}},
        {"message": {"role": "assistant", "content": "I've added it, boss."}},
    ])
    requests = []
    def respond(request, **kwargs):
        requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps(next(responses)).encode())
    from types import SimpleNamespace
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: SimpleNamespace(open=respond))
    assert assistant.converse("Remember to buy milk") == "I've added it, boss."
    assert Store(tmp_path).tasks[0]["text"] == "Buy milk"
    assert requests[-1]["messages"][-1]["role"] == "tool"


def test_worker_updates_ui_on_gui_thread(qt, tmp_path):
    window = Window(Store(tmp_path), start_workers=False)
    window.assistant.start()
    window.assistant.submit("add task Threaded integration check")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not window.store.tasks:
        qt.processEvents()
        time.sleep(.01)
    for _ in range(5):
        qt.processEvents()
        time.sleep(.01)
    assert window.store.tasks[0]["text"] == "Threaded integration check"
    assert "Task added" in window.chat.toPlainText()
    window.assistant.stop()
    window.assistant.wait(500)
    window.quitting = True
    window.close()
