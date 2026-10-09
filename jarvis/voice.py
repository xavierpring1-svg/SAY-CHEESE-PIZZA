from __future__ import annotations

import json
import queue
import re
import threading
import time

from PySide6.QtCore import Signal
from .worker import Worker
from .core import ROOT, ClapDetector
from .windows import IS_WINDOWS, powershell
from .model import model_path
from .british_speech import SpeechCancelled, SpeechOutput


class Speaker(Worker):
    speaking = Signal(bool)
    problem = Signal(str)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.queue = queue.Queue()
        self.active = threading.Event()
        self.running = True
        self.output = SpeechOutput(lambda: self.running, self.problem.emit)

    def say(self, text):
        if not self.running or not text:
            return
        # Mark busy before starting TTS so playback never feeds commands back in.
        self.active.set()
        self.queue.put(text)

    def run(self):
        while self.running:
            text = self.queue.get()
            if text is None:
                break
            self.active.set()
            self.speaking.emit(True)
            try:
                if not IS_WINDOWS:
                    self.problem.emit("Speech output is available in the Windows release.")
                    continue
                self.output.speak(text, self.store.settings)
            except SpeechCancelled:
                break
            except Exception:
                self.problem.emit("Speech output failed. Check your audio device or choose an installed Windows voice in Settings.")
            finally:
                time.sleep(0.25)
                if self.queue.empty():
                    self.active.clear()
                    self.speaking.emit(False)

    def stop(self):
        self.running = False
        self.output.stop()
        self.active.clear()
        self.queue.put(None)


class Listener(Worker):
    wake = Signal(str)
    command = Signal(str)
    transcript = Signal(str)
    level = Signal(float)
    status = Signal(str)

    def __init__(self, store, speaker):
        super().__init__()
        self.store = store
        self.speaker = speaker
        self.running = True
        self.sleeping = store.settings["start_sleeping"]
        self.ready = False
        self.chunks = queue.Queue(maxsize=60)
        self.capture_until = 0.0
        self.last_wake = 0.0

    def listen_now(self):
        self.capture_until = time.monotonic() + 25

    def set_sleep(self, asleep):
        self.sleeping = asleep
        self.capture_until = 0 if asleep else time.monotonic() + 25

    def _awaken(self, source):
        now = time.monotonic()
        if now - self.last_wake < 2.5:
            return
        self.last_wake = now
        self.sleeping = False
        self.capture_until = now + 25
        self.wake.emit(source)

    def _text(self, text):
        if not text or self.speaker.active.is_set():
            return
        self.transcript.emit(text)
        settings = self.store.settings
        # Vosk can split the proper name into phonetic English words.
        wake = re.search(r"\bhey\s+(?:jarvis|jar vus|jar v is|jervis|service|travis)\b", text, re.I)
        if wake and settings["wake_enabled"]:
            self._awaken("voice")
            remainder = text[wake.end():].strip(" ,.")
            if remainder:
                self.command.emit(remainder)
            return
        if not self.sleeping and time.monotonic() <= self.capture_until:
            self.capture_until = time.monotonic() + 25
            self.command.emit(text)

    def run(self):
        try:
            import numpy as np
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer, SetLogLevel
            path = model_path(self.store)
            if not path:
                self.status.emit("Voice model missing. Run Setup JARVIS.cmd to install the bundled model.")
                return
            SetLogLevel(-1)
            self.status.emit("Loading offline voice model…")
            model = Model(str(path))
            detector = ClapDetector(self.store.settings["clap_threshold"])

            def callback(data, frames, timing, status):
                try:
                    self.chunks.put_nowait(bytes(data))
                except queue.Full:
                    pass

            device = self.store.settings["microphone"]
            selected_device = None if device == -1 else device
            sample_rate = 16000
            try:
                sd.check_input_settings(device=selected_device, channels=1, dtype="int16", samplerate=sample_rate)
            except sd.PortAudioError:
                sample_rate = int(sd.query_devices(selected_device, "input")["default_samplerate"])
            recognizer = KaldiRecognizer(model, sample_rate)
            with sd.RawInputStream(samplerate=sample_rate, blocksize=max(256, sample_rate // 32), dtype="int16", channels=1,
                                   device=selected_device, callback=callback):
                self.ready = True
                self.status.emit('Microphone ready · say “Hey Jarvis” or clap twice')
                last_level = 0
                was_speaking = False
                while self.running:
                    try:
                        data = self.chunks.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
                    now = time.monotonic()
                    if now - last_level > 0.08:
                        self.level.emit(float(np.sqrt(np.mean(samples * samples))))
                        last_level = now
                    if self.speaker.active.is_set():
                        recognizer.Reset()
                        was_speaking = True
                        continue
                    if was_speaking:
                        recognizer.Reset()
                        self.capture_until = now + 25 if not self.sleeping else 0
                        was_speaking = False
                    options = self.store.settings
                    detector.threshold = options["clap_threshold"]
                    if options["clap_enabled"] and detector.feed(samples, now):
                        self._awaken("clap")
                        recognizer.Reset()
                    if recognizer.AcceptWaveform(data):
                        self._text(json.loads(recognizer.Result()).get("text", ""))
        except Exception as error:
            self.status.emit(f"Microphone unavailable: {error}. Typed commands still work.")
        finally:
            self.ready = False

    def stop(self):
        self.running = False


def available_voices():
    if not IS_WINDOWS:
        return []
    try:
        raw = powershell("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; @($s.GetInstalledVoices() | Where-Object Enabled | ForEach-Object {$_.VoiceInfo.Name}) | ConvertTo-Json -Compress; $s.Dispose()")
        result = json.loads(raw or "[]")
        return result if isinstance(result, list) else [result]
    except Exception:
        return []
