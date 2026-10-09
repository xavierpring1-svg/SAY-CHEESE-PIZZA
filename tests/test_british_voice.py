import asyncio
import base64
import json
import re
import ssl
import sys
from types import SimpleNamespace

import pytest

from jarvis.british_speech import NEURAL_VOICE, SpeechCancelled, SpeechOutput, _MciPlayer, neural_options


def test_default_neural_voice_is_male_british_and_uses_existing_controls():
    assert neural_options({}) == {"voice": "en-GB-RyanNeural", "rate": "-10%", "volume": "-10%"}
    assert neural_options({"speech_rate": 99, "speech_volume": -1}) == {
        "voice": NEURAL_VOICE, "rate": "+100%", "volume": "-100%",
    }


def test_neural_success_does_not_start_windows_fallback(monkeypatch):
    reports, spoken = [], []
    output = SpeechOutput(lambda: True, reports.append)
    monkeypatch.setattr(output, "_neural_speak", lambda text, options: spoken.append(text))
    monkeypatch.setattr(output, "_windows_speak", lambda *args: pytest.fail("unnecessary fallback"))
    output.speak("Good morning, boss.", {})
    assert spoken == ["Good morning, boss."]
    assert not reports


def test_tls_failure_uses_offline_voice_and_reports_no_private_text(monkeypatch):
    reports, spoken = [], []
    output = SpeechOutput(lambda: True, reports.append)
    def unavailable(*args):
        raise ssl.SSLCertVerificationError("private phrase in an upstream exception")
    monkeypatch.setattr(output, "_neural_speak", unavailable)
    monkeypatch.setattr(output, "_windows_speak", lambda text, options: spoken.append(text))
    output.speak("A private reminder", {})
    output.speak("Another reminder", {})
    assert spoken == ["A private reminder", "Another reminder"]
    assert len(reports) == 1
    assert "Windows speech" in reports[0]
    assert "private" not in reports[0].lower()


def test_offline_selection_never_sends_text_online(monkeypatch):
    spoken = []
    output = SpeechOutput(lambda: True, lambda text: None)
    monkeypatch.setattr(output, "_neural_speak", lambda *args: pytest.fail("offline mode used network"))
    monkeypatch.setattr(output, "_windows_speak", lambda text, options: spoken.append((text, options["voice"])))
    output.speak("Hello, boss.", {"speech_engine": "windows", "voice": "Microsoft George"})
    assert spoken == [("Hello, boss.", "Microsoft George")]


def test_shutdown_cancellation_never_starts_fallback(monkeypatch):
    output = SpeechOutput(lambda: True, lambda text: None)
    def cancelled(*args):
        raise SpeechCancelled()
    monkeypatch.setattr(output, "_neural_speak", cancelled)
    monkeypatch.setattr(output, "_windows_speak", lambda *args: pytest.fail("shutdown restarted speech"))
    with pytest.raises(SpeechCancelled):
        output.speak("Hello", {})


def test_online_recovery_is_reported_once(monkeypatch):
    reports = []
    output = SpeechOutput(lambda: True, reports.append)
    output.online_failed = True
    monkeypatch.setattr(output, "_neural_speak", lambda *args: None)
    output.speak("Hello", {})
    output.speak("Again", {})
    assert reports == ["The British neural voice is available again."]


def test_offline_cooldown_skips_network_until_retry_then_recovers(monkeypatch):
    clock, calls, reports = [100.0], [], []
    monkeypatch.setattr("jarvis.british_speech.time.monotonic", lambda: clock[0])
    output = SpeechOutput(lambda: True, reports.append)
    def neural(text, options):
        calls.append(("online", text))
        if text == "First reply":
            raise TimeoutError()
    monkeypatch.setattr(output, "_neural_speak", neural)
    monkeypatch.setattr(output, "_windows_speak", lambda text, options: calls.append(("offline", text)))
    output.speak("First reply", {})
    clock[0] = 159.9
    output.speak("Immediate offline reply", {})
    clock[0] = 160.0
    output.speak("Online recovery", {})
    assert calls == [("online", "First reply"), ("offline", "First reply"),
                     ("offline", "Immediate offline reply"), ("online", "Online recovery")]
    assert len(reports) == 2
    assert reports[-1] == "The British neural voice is available again."
    assert not output.online_failed
    assert output.retry_online_after == 0


def test_explicit_windows_mode_ignores_expired_online_cooldown(monkeypatch):
    output = SpeechOutput(lambda: True, lambda text: None)
    output.online_failed = True
    output.retry_online_after = 1
    monkeypatch.setattr("jarvis.british_speech.time.monotonic", lambda: 100)
    monkeypatch.setattr(output, "_neural_speak", lambda *args: pytest.fail("offline setting ignored"))
    monkeypatch.setattr(output, "_windows_speak", lambda *args: None)
    output.speak("Stay offline", {"speech_engine": "windows"})


def test_neural_download_has_bounded_timeouts_and_is_cancellable(monkeypatch, tmp_path):
    options = {}
    async def scenario():
        entered = asyncio.Event()
        class Communicator:
            def __init__(self, text, **kwargs):
                options.update(kwargs)
            async def save(self, path):
                entered.set()
                await asyncio.Event().wait()
        monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=Communicator))
        output = SpeechOutput(lambda: True, lambda text: None)
        task = asyncio.create_task(output._synthesise("Hello", {}, tmp_path / "voice.mp3"))
        await entered.wait()
        output.stop()
        with pytest.raises(SpeechCancelled):
            await asyncio.wait_for(task, timeout=1)
        assert output.task is None
        assert output.loop is None
    asyncio.run(scenario())
    assert options["voice"] == NEURAL_VOICE
    assert options["connect_timeout"] == 10
    assert options["receive_timeout"] == 20


class FakeMci:
    def __init__(self, mode="stopped", fail_on=""):
        self.commands = []
        self.mode = mode
        self.fail_on = fail_on
    def mciSendStringW(self, command, answer, size, handle):
        self.commands.append(command)
        if self.fail_on and self.fail_on in command:
            return 1
        if answer is not None:
            answer.value = "2500" if command.endswith(" length") else self.mode
        return 0


def test_windows_mp3_player_uses_unicode_filename_and_closes_alias(tmp_path):
    library = FakeMci()
    path = tmp_path / "英国 voice.mp3"
    _MciPlayer(library).play(path, lambda: True)
    assert str(path) in library.commands[0]
    assert library.commands[0].startswith("open ")
    assert library.commands[-1].startswith("close ")


def test_windows_mp3_player_stops_on_shutdown(monkeypatch, tmp_path):
    library = FakeMci(mode="playing")
    running = [True]
    monkeypatch.setattr("jarvis.british_speech.time.sleep", lambda seconds: running.__setitem__(0, False))
    with pytest.raises(SpeechCancelled):
        _MciPlayer(library).play(tmp_path / "voice.mp3", lambda: running[0])
    assert library.commands[-1].startswith("close ")


def test_windows_mp3_player_closes_alias_after_codec_error(tmp_path):
    library = FakeMci(fail_on="play ")
    with pytest.raises(RuntimeError):
        _MciPlayer(library).play(tmp_path / "voice.mp3", lambda: True)
    assert library.commands[-1].startswith("close ")


def test_neural_temporary_audio_is_deleted_after_playback_failure(monkeypatch):
    files = []
    output = SpeechOutput(lambda: True, lambda text: None)
    async def synthesise(text, options, path):
        files.append(path)
        path.write_bytes(b"mp3")
    def fail_playback(self, path, running):
        raise RuntimeError("output disconnected")
    monkeypatch.setattr(output, "_synthesise", synthesise)
    monkeypatch.setattr("jarvis.british_speech._MciPlayer.__init__", lambda self: None)
    monkeypatch.setattr("jarvis.british_speech._MciPlayer.play", fail_playback)
    with pytest.raises(RuntimeError):
        output._neural_speak("Hello", {})
    assert files and not files[0].exists()
    assert not files[0].parent.exists()


def test_windows_fallback_prefers_british_male_and_reports_missing_voice(monkeypatch):
    scripts, reports = [], []
    class Process:
        returncode = 0
        def __init__(self, command, **kwargs):
            scripts.append(command[-1])
        def communicate(self, timeout):
            return b'{"culture":"en-US"}', None
    monkeypatch.setattr("jarvis.british_speech.subprocess.Popen", Process)
    output = SpeechOutput(lambda: True, reports.append)
    output._windows_speak("Private text", {})
    output._windows_speak("Again", {})
    assert "-eq 'en-GB'" in scripts[0]
    assert "VoiceGender]::Male" in scripts[0]
    payload = re.search(r"FromBase64String\('([^']+)'\)", scripts[0]).group(1)
    assert json.loads(base64.b64decode(payload))["text"] == "Private text"
    assert "Private text" not in scripts[0]
    assert len(reports) == 1
    assert "No British Windows voice" in reports[0]


def test_windows_speech_process_is_terminated_when_stopped():
    calls = []
    output = SpeechOutput(lambda: False, lambda text: None)
    output.process = SimpleNamespace(poll=lambda: None, terminate=lambda: calls.append("terminated"))
    output.stop()
    assert calls == ["terminated"]
