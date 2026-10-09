import asyncio
import base64
import json
import re
import ssl
import sys
from types import SimpleNamespace

import pytest

from jarvis.british_speech import (NEURAL_VOICE, SpeechCancelled, SpeechOutput, _MciPlayer,
                                 neural_options, spoken_text)


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
            async def stream(self):
                entered.set()
                await asyncio.Event().wait()
                yield {"type": "audio", "data": b"never reached"}
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
    assert options["connect_timeout"] == 5
    assert options["receive_timeout"] == 8


class FakeMci:
    def __init__(self, mode="stopped", position=2500, fail_on=""):
        self.commands = []
        self.mode = mode
        self.position = position
        self.fail_on = fail_on
    def mciSendStringW(self, command, answer, size, handle):
        self.commands.append(command)
        if self.fail_on and self.fail_on in command:
            return 1
        if answer is not None:
            answer.value = ("2500" if command.endswith(" length") else
                            str(self.position) if command.endswith(" position") else self.mode)
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
    def fail_playback(self, path, running, playback=None):
        raise RuntimeError("output disconnected")
    monkeypatch.setattr(output, "_synthesise", synthesise)
    monkeypatch.setattr("jarvis.british_speech._MciPlayer.__init__", lambda self: None)
    monkeypatch.setattr("jarvis.british_speech._MciPlayer.play", fail_playback)
    with pytest.raises(RuntimeError):
        output._neural_speak("Hello", {})
    assert files and not files[0].exists()
    assert not files[0].parent.exists()


def test_windows_fallback_prefers_british_male_and_reports_missing_voice(monkeypatch, tmp_path):
    scripts, reports = [], []
    class Process:
        returncode = 0
        def __init__(self, command, **kwargs):
            scripts.append(command[-1])
        def communicate(self, timeout):
            return b'{"culture":"en-US"}', None
    monkeypatch.setattr("jarvis.british_speech.subprocess.Popen", Process)
    output = SpeechOutput(lambda: True, reports.append)
    output._windows_synthesise("Private text", {}, tmp_path / "voice.wav")
    output._windows_synthesise("Again", {}, tmp_path / "voice.wav")
    assert "-eq 'en-GB'" in scripts[0]
    assert "VoiceGender]::Male" in scripts[0]
    assert "$s.SetOutputToWaveFile" in scripts[0]
    payload = re.search(r"FromBase64String\('([^']+)'\)", scripts[0]).group(1)
    assert json.loads(base64.b64decode(payload))["text"] == "Private text"
    assert "Private text" not in scripts[0]
    assert len(reports) == 1
    assert "No British Windows voice" in reports[0]


def test_spoken_markdown_becomes_readable_prose_without_code_or_urls():
    raw = ('## Ready\n**Task added**, boss. Visit [Spotify](https://spotify.com).\n'
           '```python\nprint("do not read this code")\n```\n'
           '- First item\n- _Second_ item\nhttps://example.com/long?token=secret')
    result = spoken_text(raw)
    assert "Ready." in result
    assert "Task added, boss." in result
    assert "Visit Spotify." in result
    assert "I've put the code on screen." in result
    assert "First item Second item" in result
    assert all(part not in result for part in ("**", "```", "print", "https://", "token=", "_Second_"))


def test_spoken_long_response_stops_at_sentence_and_points_to_full_text():
    result = spoken_text("A complete sentence. " * 60, maximum=150)
    assert len(result) <= 150
    assert result.endswith(". The full answer is on screen.")
    assert result.count("A complete sentence.") < 60


def test_sanitizer_keeps_ui_text_intact_and_applies_to_both_engines(monkeypatch):
    raw, spoken = "**Hello**, boss. Read https://example.com/very-long.", []
    output = SpeechOutput(lambda: True, lambda text: None)
    monkeypatch.setattr(output, "_neural_speak", lambda text, options: spoken.append(text))
    monkeypatch.setattr(output, "_windows_speak", lambda text, options: spoken.append(text))
    output.speak(raw, {})
    output.speak(raw, {"speech_engine": "windows"})
    assert spoken == [spoken_text(raw), spoken_text(raw)]
    assert raw.startswith("**Hello**")


class SequencedMci(FakeMci):
    def __init__(self, states):
        super().__init__()
        self.states = states
        self.index = 0
    def mciSendStringW(self, command, answer, size, handle):
        state = self.states[min(self.index, len(self.states) - 1)]
        self.mode, self.position = state
        result = super().mciSendStringW(command, answer, size, handle)
        if command.endswith(" position"):
            self.index += 1
        return result


def test_mci_does_not_discard_audio_during_initial_stopped_race(monkeypatch, tmp_path):
    library = SequencedMci([("stopped", 0), ("stopped", 0), ("playing", 100),
                            ("playing", 2300), ("stopped", 2500)])
    clock, playback = [100.0], []
    monkeypatch.setattr("jarvis.british_speech.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("jarvis.british_speech.time.sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    _MciPlayer(library).play(tmp_path / "response.mp3", lambda: True, playback.append)
    assert library.index == 5
    assert playback == [True, False]
    assert library.commands[-1].startswith("close ")


def test_mci_detects_audio_that_never_starts_and_releases_microphone(monkeypatch, tmp_path):
    library = FakeMci(position=0)
    clock, playback = [100.0], []
    monkeypatch.setattr("jarvis.british_speech.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("jarvis.british_speech.time.sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    with pytest.raises(RuntimeError, match="did not start"):
        _MciPlayer(library).play(tmp_path / "response.mp3", lambda: True, playback.append)
    assert clock[0] >= 102
    assert playback == [True, False]
    assert library.commands[-1].startswith("close ")


def test_mci_detects_premature_stop_instead_of_claiming_success(monkeypatch, tmp_path):
    library = SequencedMci([("playing", 100), ("stopped", 200)])
    clock = [100.0]
    monkeypatch.setattr("jarvis.british_speech.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("jarvis.british_speech.time.sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    with pytest.raises(RuntimeError, match="before the response finished"):
        _MciPlayer(library).play(tmp_path / "response.mp3", lambda: True)


def test_offline_synthesis_does_not_mute_mic_before_wav_playback(monkeypatch):
    playback, paths = [], []
    output = SpeechOutput(lambda: True, lambda text: None, playback.append)
    def synthesise(text, settings, path):
        assert playback == []
        path.write_bytes(b"wav")
        paths.append(path)
    def play(self, path, running, callback):
        assert path.is_file()
        assert path.suffix == ".wav"
        callback(True)
        callback(False)
    monkeypatch.setattr(output, "_windows_synthesise", synthesise)
    monkeypatch.setattr("jarvis.british_speech._MciPlayer.__init__", lambda self: None)
    monkeypatch.setattr("jarvis.british_speech._MciPlayer.play", play)
    output.speak("Hello, boss.", {"speech_engine": "windows"})
    assert playback == [True, False]
    assert not paths[0].exists()


def test_no_first_audio_uses_fallback_promptly_without_muting_mic(monkeypatch):
    playback, spoken, timeouts = [], [], []
    class Communicator:
        def __init__(self, text, **kwargs):
            pass
        async def stream(self):
            await asyncio.Event().wait()
            yield {"type": "audio", "data": b"unreachable"}
    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=Communicator))
    real_wait_for = asyncio.wait_for
    async def wait_for(awaitable, timeout):
        timeouts.append(timeout)
        if timeout <= 8:
            awaitable.close()
            raise TimeoutError()
        return await real_wait_for(awaitable, timeout)
    monkeypatch.setattr("jarvis.british_speech.asyncio.wait_for", wait_for)
    output = SpeechOutput(lambda: True, lambda text: None, playback.append)
    monkeypatch.setattr(output, "_windows_speak", lambda text, settings: spoken.append(text))
    output.speak("Hello, boss.", {})
    assert spoken == ["Hello, boss."]
    assert playback == []
    assert timeouts[0] == 20
    assert 0 < timeouts[1] <= 8


def test_neural_stream_saves_audio_chunks_and_ignores_metadata(monkeypatch, tmp_path):
    class Communicator:
        def __init__(self, text, **kwargs):
            pass
        async def stream(self):
            yield {"type": "WordBoundary", "text": "Hello"}
            yield {"type": "audio", "data": b"first"}
            yield {"type": "audio", "data": b"second"}
    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=Communicator))
    playback = []
    output = SpeechOutput(lambda: True, lambda text: None, playback.append)
    path = tmp_path / "speech.mp3"
    asyncio.run(output._synthesise("Hello", {}, path))
    assert path.read_bytes() == b"firstsecond"
    assert not playback


def test_windows_speech_process_is_terminated_when_stopped():
    calls = []
    output = SpeechOutput(lambda: False, lambda text: None)
    output.process = SimpleNamespace(poll=lambda: None, terminate=lambda: calls.append("terminated"))
    output.stop()
    assert calls == ["terminated"]
