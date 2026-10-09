from __future__ import annotations

import json
import queue
import re
import threading
import time
import numpy as np

from PySide6.QtCore import Signal
from .worker import Worker
from .core import ROOT, ClapDetector
from .windows import IS_WINDOWS, powershell
from .model import model_path
from .british_speech import SpeechCancelled, SpeechOutput
from .listening import AudioInput, Utterances, normalized_clip, microphone_choice
from .transcription import WhisperTranscriber


class Speaker(Worker):
    speaking = Signal(bool)
    preparing = Signal(bool)
    problem = Signal(str)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.queue = queue.Queue()
        self.active = threading.Event()
        self.echo_until = 0.0
        self.input_busy = threading.Event()
        self.running = True
        self.generation = 0
        self.current_generation = 0
        self.lock = threading.Lock()
        self.output = SpeechOutput(lambda: self.running and self.current_generation == self.generation,
                                   self.problem.emit, self._playback)

    def _playback(self, active):
        if active:
            # Let an already-started user utterance finish before a greeting
            # or queued reply takes the microphone out of recognition mode.
            deadline = time.monotonic() + 25
            while self.input_busy.is_set() and time.monotonic() < deadline:
                if not self.output.running():
                    raise SpeechCancelled()
                time.sleep(.02)
            if not self.output.running():
                raise SpeechCancelled()
            self.preparing.emit(False)
            self.active.set()
            self.speaking.emit(True)
        else:
            self.echo_until = time.monotonic() + .15
            time.sleep(0.15)
            self.active.clear()
            self.speaking.emit(False)

    def say(self, text):
        if not self.running or not text:
            return
        with self.lock:
            self.queue.put((self.generation, text))

    def run(self):
        while self.running:
            item = self.queue.get()
            if item is None:
                break
            generation, text = item
            with self.lock:
                if generation != self.generation:
                    continue
                self.current_generation = generation
            self.preparing.emit(True)
            try:
                if not IS_WINDOWS:
                    self.problem.emit("Speech output is available in the Windows release.")
                    continue
                self.output.speak(text, self.store.settings)
            except SpeechCancelled:
                if not self.running:
                    break
            except Exception:
                self.problem.emit("Speech output failed. Check your audio device or choose an installed Windows voice in Settings.")
            finally:
                self.preparing.emit(False)
                self.active.clear()
                self.speaking.emit(False)

    def interrupt(self):
        with self.lock:
            self.generation += 1
            self.output.stop()
        self.echo_until = time.monotonic() + .25
        self.active.clear()
        self.preparing.emit(False)
        self.speaking.emit(False)

    def stop(self):
        self.running = False
        self.interrupt()
        self.queue.put(None)


class Listener(Worker):
    wake = Signal(str)
    command = Signal(str)
    transcript = Signal(str)
    level = Signal(float)
    status = Signal(str)
    partial = Signal(str)
    state = Signal(str)
    input_device = Signal(str)
    warning = Signal(str)

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
        self.decode_jobs = queue.Queue(maxsize=3)
        self.decoder_stop = threading.Event()
        self.input_busy = threading.Event()
        self.speaker.input_busy = self.input_busy

    def listen_now(self):
        self.capture_until = time.monotonic() + 45
        self.state.emit("Listening")

    def set_sleep(self, asleep):
        self.sleeping = asleep
        self.capture_until = 0 if asleep else time.monotonic() + 45
        self.state.emit("Standby" if asleep else "Listening")

    def _awaken(self, source):
        now = time.monotonic()
        if now - self.last_wake < 2.5:
            return
        self.last_wake = now
        self.sleeping = False
        self.capture_until = now + 45
        self.wake.emit(source)

    def _text(self, text, confidence=None, captured=False):
        if not text or (self.speaker.active.is_set() and not captured):
            return
        text = text.strip()
        self.transcript.emit(text)
        settings = self.store.settings
        wake = re.search(r"^\s*hey[,\s]+(?:jarvis|jar vus|jar v is|jervis)\b", text, re.I)
        if wake and settings["wake_enabled"]:
            remainder = text[wake.end():].strip(" ,.")
            self._awaken("voice_command" if remainder else "voice")
            if remainder:
                self._emit_command(remainder, confidence)
            return
        if not self.sleeping and (captured or time.monotonic() <= self.capture_until):
            self._emit_command(text, confidence)

    def _emit_command(self, text, confidence):
        self.capture_until = time.monotonic() + 45
        if confidence is not None and confidence < self.store.settings.get("voice_confidence", 0.5):
            self.warning.emit("I wasn't sure of those words. Please repeat them, or edit Heard words and send.")
            self.state.emit("Please repeat")
            return
        self.state.emit("Processing")
        self.command.emit(text)

    def _decode_loop(self, transcriber, jobs=None, stopped=None):
        jobs = self.decode_jobs if jobs is None else jobs
        stopped = self.decoder_stop if stopped is None else stopped
        while self.running and not stopped.is_set():
            try:
                job = jobs.get(timeout=.25)
            except queue.Empty:
                continue
            if job is None:
                return
            clip, fallback, confidence, candidate, eligible, wake_position = job
            if not eligible and not candidate:
                continue
            text = fallback
            if transcriber is not None:
                try:
                    text = transcriber.transcribe(normalized_clip(clip))
                    confidence = None  # Whisper provides text, not calibrated confidence.
                except Exception:
                    self.warning.emit("Enhanced transcription failed. Using basic recognition for this phrase.")
            if not text:
                if eligible:
                    self.warning.emit("I didn't catch that. Speak toward your microphone or increase input gain.")
                continue
            if not self.running or stopped.is_set():
                return
            if candidate and self.store.settings["wake_enabled"]:
                # A constrained decoder can confuse similar names. A clear
                # alternative name in unrestricted transcription vetoes wake.
                different_name = re.match(r"^\s*hey[,\s]+(charles|travis|sarah|google|siri|alexa)\b", text, re.I)
                if different_name and not eligible:
                    continue
                wake = re.search(r"^\s*hey[,\s]+(?:jarvis|jar vus|jar v is|jervis)\b", text, re.I)
                if wake is None and wake_position is not None:
                    remainder = ""
                    if transcriber is not None:
                        tail = clip[max(0, int((wake_position - .04) * 16000)):]
                        if len(tail) > 8000 and float(np.sqrt(np.mean(tail * tail))) > .002:
                            try:
                                remainder = transcriber.transcribe(normalized_clip(tail))
                            except Exception:
                                remainder = ""
                    else:
                        remainder = re.sub(r"^.*?\b(?:jarvis|jervis)\b[,\s]*", "", fallback, flags=re.I) if re.search(r"\b(?:jarvis|jervis)\b", fallback, re.I) else ""
                    text = "Hey Jarvis" + (", " + remainder if remainder else "")
            # This clip was captured while output was quiet. A queued reply
            # beginning during decoding must not erase the user's earlier words.
            self._text(text, confidence, captured=True)

    def run(self):
        # UI retries reuse this worker. Keep each decoder tied to its own
        # queue and cancellation signal, including startup failures.
        self.chunks = queue.Queue(maxsize=60)
        self.decode_jobs = queue.Queue(maxsize=3)
        self.decoder_stop = threading.Event()
        jobs, stopped = self.decode_jobs, self.decoder_stop
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
                recorded = time.monotonic()
                output_audio = self.speaker.active.is_set() or recorded < getattr(self.speaker, "echo_until", 0)
                try:
                    self.chunks.put_nowait((recorded, bytes(data), bool(status), output_audio))
                except queue.Full:
                    try:
                        self.chunks.get_nowait()
                        self.chunks.put_nowait((recorded, bytes(data), True, output_audio))
                    except (queue.Empty, queue.Full):
                        pass

            device = self.store.settings["microphone"]
            selected_device = microphone_choice(sd.query_devices(), int(sd.default.device[0])) if device == -1 else device
            sample_rate = 16000
            try:
                sd.check_input_settings(device=selected_device, channels=1, dtype="int16", samplerate=sample_rate)
            except sd.PortAudioError:
                sample_rate = int(sd.query_devices(selected_device, "input")["default_samplerate"])
            recognizer = KaldiRecognizer(model, 16000)
            recognizer.SetWords(True)
            wake_recognizer = KaldiRecognizer(model, 16000, json.dumps(["hey jarvis", "hey jervis", "[unk]"]))
            wake_recognizer.SetWords(True)
            if hasattr(wake_recognizer, "SetPartialWords"):
                wake_recognizer.SetPartialWords(True)
            audio = AudioInput(sample_rate)
            utterances = Utterances()
            transcription = WhisperTranscriber(self.store)
            enhanced = self.store.settings.get("enhanced_transcription", True) and transcription.ready()
            if not enhanced and self.store.settings.get("enhanced_transcription", True):
                self.warning.emit("Enhanced recognition isn't installed yet. Basic voice recognition is active.")
            decoder = threading.Thread(target=self._decode_loop,
                                       args=(transcription if enhanced else None, jobs, stopped), daemon=True)
            decoder.start()
            words, confidence_words = [], []
            candidate = False
            wake_end = None
            samples_seen = 0
            utterance_eligible = False
            with sd.RawInputStream(samplerate=sample_rate, blocksize=max(256, sample_rate // 32), dtype="int16", channels=1,
                                   device=selected_device, callback=callback):
                self.ready = True
                name = sd.query_devices(selected_device, "input")["name"]
                self.input_device.emit(name)
                self.status.emit(f'Microphone ready · {name} · {"Whisper + wake detection" if enhanced else "basic recognition"}')
                self.state.emit("Standby" if self.sleeping else "Listening")
                last_level = 0
                last_warning = 0
                was_speaking = False
                while self.running:
                    try:
                        recorded, data, overflow, output_audio = self.chunks.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
                    now = time.monotonic()
                    if now - recorded > .75 or overflow:
                        recognizer.Reset()
                        wake_recognizer.Reset()
                        utterances.reset()
                        self.input_busy.clear()
                        words, confidence_words, candidate, wake_end = [], [], False, None
                        if now - last_warning > 5:
                            self.warning.emit("Audio frames were missed. Close heavy background apps or select another microphone.")
                            last_warning = now
                        if now - recorded > .75:
                            continue
                    if now - last_level > 0.08:
                        self.level.emit(float(np.sqrt(np.mean(samples * samples))))
                        last_level = now
                    if output_audio or self.speaker.active.is_set() or now < getattr(self.speaker, "echo_until", 0):
                        recognizer.Reset()
                        wake_recognizer.Reset()
                        utterances.reset()
                        self.input_busy.clear()
                        words, confidence_words, candidate, wake_end = [], [], False, None
                        was_speaking = True
                        continue
                    if was_speaking:
                        recognizer.Reset()
                        wake_recognizer.Reset()
                        self.capture_until = now + 45 if not self.sleeping else 0
                        self.state.emit("Standby" if self.sleeping else "Listening")
                        was_speaking = False
                    options = self.store.settings
                    detector.threshold = options["clap_threshold"]
                    if options["clap_enabled"] and detector.feed(samples, now):
                        self._awaken("clap")
                        recognizer.Reset()
                        wake_recognizer.Reset()
                        utterances.reset()
                        self.input_busy.clear()
                        words, confidence_words, candidate, wake_end = [], [], False, None
                        continue
                    samples16 = audio.convert(data, options.get("microphone_gain", 1.0))
                    if np.max(np.abs(samples16), initial=0) > .98 and now - last_warning > 5:
                        self.warning.emit("Microphone audio is clipping. Lower input gain or move farther from the microphone.")
                        last_warning = now
                    pcm16 = (samples16 * 32767).astype(np.int16).tobytes()
                    samples_seen += len(samples16)
                    wake_final = wake_recognizer.AcceptWaveform(pcm16)
                    wake_result = json.loads(wake_recognizer.Result() if wake_final else wake_recognizer.PartialResult())
                    wake_text = wake_result.get("text", wake_result.get("partial", ""))
                    if re.search(r"\bhey (?:jarvis|jervis)\b", wake_text):
                        candidate = True
                        tokens = wake_result.get("result", wake_result.get("partial_result", []))
                        matched = [token for token in tokens if token.get("word") in {"jarvis", "jervis"}]
                        if matched:
                            wake_end = matched[-1].get("end")
                    if recognizer.AcceptWaveform(pcm16):
                        result = json.loads(recognizer.Result())
                        words.append(result.get("text", ""))
                        confidence_words.extend(result.get("result", []))
                    elif now - last_level < .02:
                        self.partial.emit(json.loads(recognizer.PartialResult()).get("partial", ""))
                    starting = not utterances.parts
                    clip = utterances.feed(samples16)
                    self.input_busy.set() if utterances.parts else self.input_busy.clear()
                    if starting and utterances.parts:
                        utterance_eligible = not self.sleeping and now <= self.capture_until
                    if clip is not None:
                        # Short wake phrases can finish before their partial
                        # text stabilises. Finalise both decoders at silence.
                        wake_result = json.loads(wake_recognizer.FinalResult())
                        if re.search(r"\bhey (?:jarvis|jervis)\b", wake_result.get("text", "")):
                            candidate = True
                            matched = [word for word in wake_result.get("result", [])
                                       if word.get("word") in {"jarvis", "jervis"}]
                            if matched:
                                wake_end = matched[-1].get("end")
                        result = json.loads(recognizer.FinalResult())
                        words.append(result.get("text", ""))
                        confidence_words.extend(result.get("result", []))
                        fallback = " ".join(word for word in words if word)
                        confidence = (sum(word.get("conf", 0) for word in confidence_words) / len(confidence_words)
                                      if confidence_words else None)
                        eligible = not self.sleeping and (utterance_eligible or now <= self.capture_until)
                        try:
                            clip_start = samples_seen / 16000 - len(clip) / 16000
                            wake_position = max(0, wake_end - clip_start) if wake_end is not None else None
                            self.decode_jobs.put_nowait((clip, fallback, confidence, candidate, eligible, wake_position))
                        except queue.Full:
                            self.warning.emit("Please pause while I finish transcribing, then repeat that command.")
                        recognizer.Reset()
                        wake_recognizer.Reset()
                        words, confidence_words, candidate, wake_end = [], [], False, None
                        utterance_eligible = False
        except Exception as error:
            self.status.emit(f"Microphone unavailable: {error}. Typed commands still work.")
        finally:
            self.ready = False
            self.input_busy.clear()
            stopped.set()
            try:
                jobs.put_nowait(None)
            except queue.Full:
                pass

    def stop(self):
        self.running = False
        self.decoder_stop.set()
        try:
            self.decode_jobs.put_nowait(None)
        except queue.Full:
            pass


def available_voices():
    if not IS_WINDOWS:
        return []
    try:
        raw = powershell("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; @($s.GetInstalledVoices() | Where-Object Enabled | ForEach-Object {$_.VoiceInfo.Name}) | ConvertTo-Json -Compress; $s.Dispose()")
        result = json.loads(raw or "[]")
        return result if isinstance(result, list) else [result]
    except Exception:
        return []
