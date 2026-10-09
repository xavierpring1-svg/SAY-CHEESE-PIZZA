"""British speech output with a cancellable Windows offline fallback.

Only the text being spoken is sent to the online speech service. Audio is held
in a temporary directory and removed after playback; microphone audio stays in
the independent offline recogniser.
"""
from __future__ import annotations

import asyncio
import base64
import ctypes
import json
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .windows import NO_WINDOW


NEURAL_VOICE = "en-GB-RyanNeural"
NEURAL_RETRY_DELAY = 60


class SpeechCancelled(Exception):
    """The app is closing; do not retry through another speech engine."""


def neural_options(settings):
    """Translate the existing Windows rate and volume controls to SSML values."""
    rate = max(-10, min(10, int(settings.get("speech_rate", -1)))) * 10
    volume = max(0, min(100, int(settings.get("speech_volume", 90)))) - 100
    return {"voice": NEURAL_VOICE, "rate": f"{rate:+d}%", "volume": f"{volume:+d}%"}


class _MciPlayer:
    """Use the Windows MP3 decoder without starting a visible media player."""

    def __init__(self, library=None):
        self.library = library or ctypes.WinDLL("winmm")
        if library is None:
            self.library.mciSendStringW.argtypes = [
                ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p,
            ]
            self.library.mciSendStringW.restype = ctypes.c_uint

    def _command(self, command, answer=False):
        buffer = ctypes.create_unicode_buffer(256) if answer else None
        result = self.library.mciSendStringW(command, buffer, 256 if answer else 0, None)
        if result:
            raise RuntimeError("Windows could not play the speech audio.")
        return buffer.value if buffer is not None else ""

    def play(self, path, running):
        alias = "jarvisspeech_" + uuid.uuid4().hex
        opened = False
        try:
            if not running():
                raise SpeechCancelled()
            # The path is created by TemporaryDirectory, never supplied by a command.
            self._command(f'open "{path}" type mpegvideo alias {alias}')
            opened = True
            self._command(f"set {alias} time format milliseconds")
            length = int(self._command(f"status {alias} length", answer=True))
            self._command(f"play {alias} from 0")
            deadline = time.monotonic() + min(180, max(5, length / 1000 + 5))
            while True:
                if not running():
                    raise SpeechCancelled()
                if self._command(f"status {alias} mode", answer=True) != "playing":
                    return
                if time.monotonic() > deadline:
                    raise RuntimeError("Speech playback timed out.")
                time.sleep(0.05)
        finally:
            if opened:
                # Closing the alias stops playback even when synthesis is cancelled.
                try:
                    self._command(f"close {alias}")
                except RuntimeError:
                    pass


class SpeechOutput:
    def __init__(self, running, report):
        self.running = running
        self.report = report
        self.lock = threading.Lock()
        self.process = None
        self.loop = None
        self.task = None
        self.online_failed = False
        self.retry_online_after = 0.0
        self.missing_british_reported = False

    def speak(self, text, settings):
        if not self.running():
            raise SpeechCancelled()
        if (settings.get("speech_engine", "neural") != "windows"
                and time.monotonic() >= self.retry_online_after):
            try:
                self._neural_speak(text[:5000], settings)
                if self.online_failed:
                    self.report("The British neural voice is available again.")
                self.online_failed = False
                self.retry_online_after = 0.0
                return
            except SpeechCancelled:
                raise
            except Exception:
                if not self.running():
                    raise SpeechCancelled() from None
                if not self.online_failed:
                    self.report("The online British voice is unavailable. Using Windows speech; "
                                "install an English (United Kingdom) voice for a British offline accent.")
                self.online_failed = True
                # An offline connection should delay only the first reply, not
                # every utterance. Try the service again after a short cooldown.
                self.retry_online_after = time.monotonic() + NEURAL_RETRY_DELAY
        self._windows_speak(text[:5000], settings)

    def _neural_speak(self, text, settings):
        with tempfile.TemporaryDirectory(prefix="jarvis-speech-") as directory:
            path = Path(directory) / "response.mp3"
            asyncio.run(self._synthesise(text, settings, path))
            if not self.running():
                raise SpeechCancelled()
            _MciPlayer().play(path, self.running)

    async def _synthesise(self, text, settings, path):
        import edge_tts

        # edge-tts retains TLS certificate verification. No credentials are saved.
        communicator = edge_tts.Communicate(text, **neural_options(settings),
                                           connect_timeout=10, receive_timeout=20)
        task = asyncio.create_task(communicator.save(str(path)))
        with self.lock:
            if not self.running():
                task.cancel()
            self.loop = asyncio.get_running_loop()
            self.task = task
        try:
            await asyncio.wait_for(task, timeout=35)
        except asyncio.CancelledError:
            raise SpeechCancelled() from None
        finally:
            with self.lock:
                self.loop = None
                self.task = None

    def _windows_speak(self, text, settings):
        payload = base64.b64encode(json.dumps({
            "text": text, "voice": settings.get("voice", ""),
            "rate": max(-10, min(10, int(settings.get("speech_rate", -1)))),
            "volume": max(0, min(100, int(settings.get("speech_volume", 90)))),
        }).encode("utf-8")).decode("ascii")
        script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        script += "$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "')) | ConvertFrom-Json; "
        script += "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Speech; "
        script += "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; try { "
        script += "if($p.voice){$s.SelectVoice($p.voice)}else{ "
        script += "$v=$s.GetInstalledVoices() | Where-Object {$_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'en-GB'} "
        script += "| Sort-Object @{Expression={$_.VoiceInfo.Gender -ne [System.Speech.Synthesis.VoiceGender]::Male}} "
        script += "| Select-Object -First 1; if($v){$s.SelectVoice($v.VoiceInfo.Name)}}; "
        script += "$s.Rate=[int]$p.rate; $s.Volume=[int]$p.volume; $s.Speak([string]$p.text); "
        script += "@{culture=$s.Voice.Culture.Name} | ConvertTo-Json -Compress } finally {$s.Dispose()}"
        with self.lock:
            if not self.running():
                raise SpeechCancelled()
            self.process = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW,
            )
            process = self.process
        try:
            try:
                output, _ = process.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=2)
                raise RuntimeError("Windows speech timed out.") from None
            if not self.running():
                raise SpeechCancelled()
            if process.returncode:
                raise RuntimeError("Windows speech synthesis failed.")
            metadata = json.loads(output.decode("utf-8-sig") or "{}")
            if (not settings.get("voice") and metadata.get("culture") != "en-GB"
                    and not self.missing_british_reported):
                self.report("No British Windows voice is installed. Add English (United Kingdom) "
                            "speech in Windows Settings, or use the online British voice.")
                self.missing_british_reported = True
        finally:
            with self.lock:
                self.process = None

    def stop(self):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                try:
                    self.process.terminate()
                except OSError:
                    pass
            if self.loop is not None and self.task is not None:
                try:
                    self.loop.call_soon_threadsafe(self.task.cancel)
                except RuntimeError:
                    pass
