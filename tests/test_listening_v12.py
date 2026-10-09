import json
import queue
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from jarvis.core import Store, parse_command
from jarvis.listening import AudioInput, Utterances, microphone_choice, normalized_clip
from jarvis.voice import Listener, Speaker
from jarvis.assistant import Assistant


def test_device_default_avoids_recording_speaker_output():
    devices = [{"name": "Stereo Mix", "max_input_channels": 2},
               {"name": "Headset microphone", "max_input_channels": 1}]
    assert microphone_choice(devices, 0) == 1
    with pytest.raises(RuntimeError):
        microphone_choice(devices[:1], 0)


@pytest.mark.parametrize("rate", [8000, 16000, 44100, 48000])
def test_native_microphone_audio_is_resampled_to_16khz(rate):
    signal = (np.sin(np.arange(rate) * 2 * np.pi * 440 / rate) * 12000).astype(np.int16)
    converter = AudioInput(rate)
    converted = [converter.convert(chunk.tobytes()) for chunk in np.array_split(signal, 25)]
    result = np.concatenate(converted)
    assert abs(len(result) - 16000) <= 2
    assert np.max(np.abs(result)) < .4
    assert result.dtype == np.float32


def test_utterance_preserves_first_words_and_ends_at_bounded_silence():
    capture = Utterances()
    for _ in range(10):
        assert capture.feed(np.zeros(512, dtype=np.float32)) is None
    speech = np.sin(np.arange(512) * .15).astype(np.float32) * .03
    for _ in range(16):
        assert capture.feed(speech) is None
    clip = None
    for _ in range(21):
        value = capture.feed(np.zeros(512, dtype=np.float32))
        if value is not None:
            clip = value
    assert clip is not None
    assert np.count_nonzero(clip) == np.count_nonzero(speech) * 16
    assert len(clip) < 16000 * 2


def test_quiet_audio_normalization_is_bounded_and_silence_not_amplified():
    assert np.max(normalized_clip(np.array([.1, -.1], dtype=np.float32))) == pytest.approx(.4)
    assert np.max(normalized_clip(np.array([.001], dtype=np.float32))) == pytest.approx(.001)
    assert np.max(normalized_clip(np.array([2], dtype=np.float32))) == 1


def test_speaker_leaves_microphone_open_during_synthesis_and_can_interrupt(tmp_path, monkeypatch):
    import jarvis.voice as voice
    monkeypatch.setattr(voice, "IS_WINDOWS", True)
    speaker = Speaker(Store(tmp_path))
    synthesizing, cancelled = threading.Event(), threading.Event()
    def fake_speak(text, settings):
        synthesizing.set()
        while speaker.output.running():
            time.sleep(.005)
        cancelled.set()
    monkeypatch.setattr(speaker.output, "speak", fake_speak)
    speaker.say("Hello, Sarah.")
    assert not speaker.active.is_set()
    speaker.start()
    assert synthesizing.wait(1)
    assert not speaker.active.is_set()
    speaker.interrupt()
    assert cancelled.wait(1)
    speaker.stop()
    speaker.wait(1000)
    assert not speaker.isRunning()


def test_greeting_waits_for_users_existing_utterance(tmp_path):
    speaker = Speaker(Store(tmp_path))
    speaker.input_busy.set()
    thread = threading.Thread(target=lambda: speaker._playback(True))
    thread.start()
    time.sleep(.05)
    assert not speaker.active.is_set()
    speaker.input_busy.clear()
    thread.join(1)
    assert not thread.is_alive()
    assert speaker.active.is_set()
    speaker._playback(False)
    assert not speaker.active.is_set()
    speaker.stop()


def test_low_confidence_basic_speech_is_shown_without_executing(tmp_path):
    speaker = SimpleNamespace(active=threading.Event())
    listener = Listener(Store(tmp_path), speaker)
    listener.set_sleep(False)
    heard, commands, warnings = [], [], []
    listener.transcript.connect(heard.append)
    listener.command.connect(commands.append)
    listener.warning.connect(warnings.append)
    listener._text("remove task two", confidence=.2)
    assert heard == ["remove task two"]
    assert commands == []
    assert warnings
    listener._text("set volume forty", confidence=.9)
    assert commands == ["set volume forty"]


def test_cancelled_decoder_does_not_dispatch_or_consume_retry_audio(tmp_path):
    listener = Listener(Store(tmp_path), SimpleNamespace(active=threading.Event()))
    old_jobs, stopped = queue.Queue(), threading.Event()
    old_jobs.put((np.zeros(16000, dtype=np.float32), "open Chrome", .9, False, True, None))
    listener.decode_jobs = queue.Queue()
    retry_job = object()
    listener.decode_jobs.put(retry_job)
    commands = []
    listener.command.connect(commands.append)

    def transcribe(_):
        stopped.set()  # The microphone failed while this earlier phrase decoded.
        return "open Chrome"

    listener._decode_loop(SimpleNamespace(transcribe=transcribe), old_jobs, stopped)
    assert not commands
    assert listener.decode_jobs.get_nowait() is retry_job


def test_inline_wake_has_no_greeting_that_can_cut_off_command(tmp_path):
    speaker = SimpleNamespace(active=threading.Event())
    listener = Listener(Store(tmp_path), speaker)
    listener.sleeping = True
    wakes, commands = [], []
    listener.wake.connect(wakes.append)
    listener.command.connect(commands.append)
    listener._text("Hey, Jarvis, say hello to Sarah")
    assert wakes == ["voice_command"]
    assert commands == ["say hello to Sarah"]
    assert parse_command(commands[0]) == ("greet", "Sarah")


def test_greeting_repeat_and_followup_use_requested_name_and_task(tmp_path):
    assistant = Assistant(Store(tmp_path), None, SimpleNamespace(say=lambda _: None))
    assert assistant.execute(*parse_command("Can you say hello to Sarah")) == "Hello, Sarah! It's a pleasure to meet you."
    assert assistant.execute(*parse_command("say Open Chrome")) == "Open Chrome"
    action, question = assistant.resolve_command("add task")
    assert action == "say" and "What" in question
    assistant.execute(*assistant.resolve_command("Buy birthday cake for Sarah"))
    assert assistant.store.tasks[0]["text"] == "Buy birthday cake for Sarah"


def test_local_conversation_uses_loopback_token_and_supported_actions(tmp_path, monkeypatch):
    import io
    import jarvis.assistant as module
    assistant = Assistant(Store(tmp_path), None, SimpleNamespace(say=lambda _: None))
    assistant.brain = SimpleNamespace(ready=True, endpoint="http://127.0.0.1:53241/v1/chat/completions", token="test-session-only")
    answers = iter([
        {"choices": [{"message": {"role": "assistant", "tool_calls": [{"id": "t1", "type": "function", "function": {
            "name": "desktop_action", "arguments": json.dumps({"action": "greet", "argument": "Sarah"})}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "Hello, Sarah! Lovely to meet you."}}]},
    ])
    requests = []
    def respond(request, **kwargs):
        assert request.full_url.startswith("http://127.0.0.1:")
        assert request.get_header("Authorization") == "Bearer test-session-only"
        requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps(next(answers)).encode())
    def build(*handlers):
        assert handlers[0].proxies == {}
        return SimpleNamespace(open=respond)
    monkeypatch.setattr(module.urllib.request, "build_opener", build)
    assert assistant.converse("Please introduce yourself to my friend Sarah") == "Hello, Sarah! Lovely to meet you."
    assert requests[-1]["messages"][-1]["content"] == "Hello, Sarah! It's a pleasure to meet you."


def test_existing_settings_upgrade_keeps_tasks_and_enables_conversation(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"settings": {"ai_provider": "Local commands"}, "tasks": [{"id": "1", "text": "Keep me", "done": False}]}))
    store = Store(tmp_path)
    assert store.settings["ai_provider"] == "Built-in AI (local)"
    assert store.tasks[0]["text"] == "Keep me"
    store.update_settings({"ai_provider": "Local commands"})
    assert Store(tmp_path).settings["ai_provider"] == "Local commands"


def test_listen_waits_for_reply_echo_before_showing_speak_now(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from jarvis.ui import Window
    app = QApplication.instance() or QApplication([])
    window = Window(Store(tmp_path), start_workers=False)
    window.listener.ready = True
    window.speaking = True
    calls = []
    monkeypatch.setattr(window.listener, "listen_now", lambda: calls.append(time.monotonic()))
    window.listen()
    QTest.qWait(150)
    assert not calls
    QTest.qWait(200)
    assert len(calls) == 1
    assert window.activity_title.text() == "Listening"
    window.quitting = True
    window.close()
    app.processEvents()


def test_quit_cancels_pending_listen_activation(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from jarvis.ui import Window
    app = QApplication.instance() or QApplication([])
    window = Window(Store(tmp_path), start_workers=False)
    window.listener.ready = True
    window.speaking = True
    calls = []
    monkeypatch.setattr(window.listener, "listen_now", lambda: calls.append(True))
    window.listen()
    window.quitting = True
    QTest.qWait(350)
    assert calls == []
    window.close()
    app.processEvents()
