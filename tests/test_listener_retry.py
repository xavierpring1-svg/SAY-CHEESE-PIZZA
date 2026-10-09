"""Retry a failed microphone startup through the actual capture/decoder loops."""
import json
import os
import sys
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_CACHE_HOME", "/workspace/.cache")

import numpy as np
from PySide6.QtWidgets import QApplication

from jarvis.core import Store
from jarvis.voice import Listener
import jarvis.voice as voice


def test_microphone_startup_retry_decodes_audio_and_stops_cleanly(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    store = Store(tmp_path)
    store.update_settings({"enhanced_transcription": False, "clap_enabled": False,
                           "microphone": -1, "start_sleeping": False})
    speaker = SimpleNamespace(active=threading.Event(), echo_until=0)
    listener = Listener(store, speaker)
    statuses, commands = [], []
    listener.status.connect(statuses.append)
    listener.command.connect(commands.append)

    # The first failure occurs before a decoder thread exists, precisely where
    # the previous implementation left a shutdown sentinel for the next run.
    queries = []
    microphone = {"name": "Mock physical microphone", "max_input_channels": 1,
                  "default_samplerate": 16000}

    def query_devices(*args):
        queries.append(args)
        if len(queries) == 1:
            raise RuntimeError("No microphone connected")
        return microphone if args else [microphone]

    opened, closed = threading.Event(), threading.Event()

    class InputStream:
        def __init__(self, **options):
            self.callback = options["callback"]

        def __enter__(self):
            opened.set()
            # Feed real int16 microphone buffers through AudioInput and the
            # real silence boundary detector: enough speech, then a pause.
            speech = np.full(512, 3277, dtype=np.int16).tobytes()
            silence = np.zeros(512, dtype=np.int16).tobytes()
            for frame in [speech] * 8 + [silence] * 23:
                self.callback(frame, 512, None, False)
            return self

        def __exit__(self, *args):
            closed.set()

    sounddevice = SimpleNamespace(
        query_devices=query_devices,
        default=SimpleNamespace(device=(0, -1)),
        check_input_settings=lambda **options: None,
        RawInputStream=InputStream,
        PortAudioError=type("PortAudioError", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)

    class Recognizer:
        def __init__(self, *args):
            self.wake_only = len(args) > 2

        def SetWords(self, enabled):
            pass

        def SetPartialWords(self, enabled):
            pass

        def AcceptWaveform(self, audio):
            return False

        def PartialResult(self):
            return json.dumps({"partial": ""})

        def FinalResult(self):
            if self.wake_only:
                return json.dumps({"text": ""})
            return json.dumps({"text": "add task retry works", "result": [
                {"word": word, "conf": .99} for word in "add task retry works".split()]})

        def Reset(self):
            pass

    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(
        Model=lambda path: object(), KaldiRecognizer=Recognizer, SetLogLevel=lambda level: None))
    monkeypatch.setattr(voice, "model_path", lambda store: tmp_path)
    monkeypatch.setattr(voice, "WhisperTranscriber", lambda store: SimpleNamespace(ready=lambda: False))

    decoder_started, decoder_finished = threading.Event(), threading.Event()
    decode_loop = listener._decode_loop

    def tracked_decoder(*args, **kwargs):
        decoder_started.set()
        try:
            return decode_loop(*args, **kwargs)
        finally:
            decoder_finished.set()

    monkeypatch.setattr(listener, "_decode_loop", tracked_decoder)
    listener.run()
    assert any("No microphone connected" in status for status in statuses)
    assert not opened.is_set()
    assert not decoder_started.is_set()
    assert listener.running and not listener.ready

    listener.listen_now()
    listener.start()
    try:
        deadline = time.monotonic() + 3
        while not commands and time.monotonic() < deadline:
            qt.processEvents()
            time.sleep(.005)
        assert opened.is_set()
        assert decoder_started.is_set()
        assert commands == ["add task retry works"]
        assert listener.ready
    finally:
        listener.stop()
        listener.wait(1000)
        qt.processEvents()

    assert not listener.isRunning()
    assert decoder_finished.wait(1), "The retry decoder did not shut down"
    assert closed.is_set()
    assert not listener.ready
