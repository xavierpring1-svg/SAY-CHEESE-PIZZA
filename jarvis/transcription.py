"""Optional local Whisper transcription after JARVIS captures an utterance."""
from __future__ import annotations

import bz2
import hashlib
import json
import os
import re
import shutil
import tarfile
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid
from pathlib import Path, PurePosixPath

from PySide6.QtCore import Signal
from .core import ROOT
from .worker import Worker

MODEL_NAME = "sherpa-onnx-whisper-tiny.en"
ASSET_NAME = MODEL_NAME + ".tar.bz2"
URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/" + ASSET_NAME
ASSET_METADATA_URL = "https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/assets/179374011"
DOWNLOAD_MB = 118
ENCODER = "tiny.en-encoder.int8.onnx"
DECODER = "tiny.en-decoder.int8.onnx"
TOKENS = "tiny.en-tokens.txt"
REQUIRED_FILES = (ENCODER, DECODER, TOKENS)
MAX_DOWNLOAD_BYTES = 160 * 1024 * 1024
MAX_EXPANDED_BYTES = 400 * 1024 * 1024
MAX_MEMBER_BYTES = 200 * 1024 * 1024
MAX_AUDIO_SECONDS = 30


def transcription_model_path(store):
    for path in [ROOT / "models" / MODEL_NAME, store.directory / "models" / MODEL_NAME]:
        try:
            if all((path / name).is_file() and (path / name).stat().st_size > 0 for name in REQUIRED_FILES):
                return path
        except OSError:
            # A background replacement may briefly rename an existing model.
            continue
    return None


class WhisperTranscriber:
    """Decode mono 16 kHz samples locally; the result has no confidence score."""

    def __init__(self, store, *, recognizer_factory=None):
        self.store = store
        self.recognizer_factory = recognizer_factory
        self.recognizer = None
        self.loaded_path = None
        self.lock = threading.Lock()

    def ready(self):
        return transcription_model_path(self.store) is not None

    def _recognizer(self):
        path = transcription_model_path(self.store)
        if path is None:
            raise RuntimeError("Enhanced listening needs its offline Whisper model. Complete voice setup first.")
        if self.recognizer is not None and self.loaded_path == path:
            return self.recognizer
        factory = self.recognizer_factory
        if factory is None:
            try:
                from sherpa_onnx import OfflineRecognizer
            except ImportError:
                raise RuntimeError("Enhanced listening needs the updated JARVIS transcription component.") from None
            factory = OfflineRecognizer.from_whisper
        self.recognizer = factory(
            encoder=str(path / ENCODER), decoder=str(path / DECODER), tokens=str(path / TOKENS),
            language="en", task="transcribe", num_threads=min(4, max(1, os.cpu_count() or 1)),
            provider="cpu", debug=False,
        )
        self.loaded_path = path
        return self.recognizer

    def transcribe(self, samples):
        import numpy as np

        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim != 1:
            raise ValueError("Enhanced listening expects mono audio sampled at 16 kHz.")
        if audio.size > MAX_AUDIO_SECONDS * 16000:
            raise ValueError("Keep each voice request under 30 seconds.")
        if not np.all(np.isfinite(audio)) or (audio.size and np.max(np.abs(audio)) > 1.0001):
            raise ValueError("Enhanced listening expects finite audio samples between -1 and 1.")
        if audio.size < 1600 or np.max(np.abs(audio), initial=0) < 1e-6:
            return ""
        with self.lock:
            recognizer = self._recognizer()
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, audio)
            recognizer.decode_stream(stream)
            text = str(stream.result.text or "").strip()
        # Whisper may annotate non-speech; annotations are not desktop commands.
        if text.casefold() in {"[blank_audio]", "[silence]", "(silence)", "[music]", "(music)"}:
            return ""
        return text


class TranscriptionDownloadCancelled(RuntimeError):
    pass


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise TranscriptionDownloadCancelled("Enhanced listening setup cancelled.")


def _published_sha256():
    """Use GitHub's published asset digest when supplied; never invent one."""
    request = urllib.request.Request(ASSET_METADATA_URL, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if not response.geturl().lower().startswith("https://"):
                raise ValueError("Whisper asset metadata requires verified HTTPS.")
            raw = response.read(64 * 1024 + 1)
            if len(raw) > 64 * 1024:
                raise ValueError("Whisper asset metadata exceeded its expected size.")
            metadata = json.loads(raw)
    except OSError:
        # The original asset predates GitHub's digest field and currently has
        # digest=null. Official HTTPS plus bzip2/tar checks still apply.
        return None
    except json.JSONDecodeError:
        raise ValueError("Whisper release metadata was not valid JSON.") from None
    if (not isinstance(metadata, dict) or metadata.get("name") != ASSET_NAME
            or metadata.get("browser_download_url") != URL):
        raise ValueError("Whisper release metadata did not match the expected official asset.")
    digest = metadata.get("digest")
    if digest is None:
        return None
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
        raise ValueError("Whisper release has an unsupported integrity digest.")
    return digest.split(":", 1)[1].lower()


def _member_path(member, temporary):
    path = PurePosixPath(member.name.replace("\\", "/"))
    if (not path.parts or path.is_absolute() or path.parts[0] != MODEL_NAME
            or not (member.isdir() or member.isreg())
            or member.size < 0 or member.size > MAX_MEMBER_BYTES
            or any(part in {".", ".."} or ":" in part or part.rstrip(" .") != part
                   or any(unicodedata.category(character) == "Cc" for character in part)
                   or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I)
                   for part in path.parts)):
        raise ValueError("Unsafe Whisper model archive.")
    target = (temporary / Path(*path.parts)).resolve()
    if not target.is_relative_to(temporary.resolve()):
        raise ValueError("Unsafe Whisper model archive.")
    return target


class _BoundedReader:
    def __init__(self, source, cancelled):
        self.source, self.cancelled = source, cancelled
        self.total = 0

    def read(self, size=-1):
        _check_cancelled(self.cancelled)
        if size < 0 or size > MAX_EXPANDED_BYTES - self.total + 1:
            size = MAX_EXPANDED_BYTES - self.total + 1
        chunk = self.source.read(size)
        self.total += len(chunk)
        if self.total > MAX_EXPANDED_BYTES:
            raise ValueError("Whisper model archive exceeded its expanded size limit.")
        return chunk


def _extract_archive(archive, temporary, progress, cancelled):
    selected = set()
    members = 0
    declared_size = 0
    # Stream every member, including ignored full-precision models. Drain the
    # decompressor afterwards so its final bzip2 CRC is checked as well.
    with bz2.BZ2File(archive, "rb") as decompressed:
        reader = _BoundedReader(decompressed, cancelled)
        with tarfile.open(fileobj=reader, mode="r|") as bundle:
            for member in bundle:
                _check_cancelled(cancelled)
                members += 1
                declared_size += member.size
                if members > 5000 or declared_size > MAX_EXPANDED_BYTES:
                    raise ValueError("Whisper model archive exceeded its expected size.")
                destination = _member_path(member, temporary)
                relative = destination.relative_to(temporary / MODEL_NAME).as_posix()
                if relative not in REQUIRED_FILES or not member.isreg():
                    continue
                if relative in selected:
                    raise ValueError("Whisper model archive contained a duplicate model file.")
                source = bundle.extractfile(member)
                if source is None:
                    raise ValueError("Whisper model archive was missing file data.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source, destination.open("wb") as output:
                    while True:
                        _check_cancelled(cancelled)
                        chunk = source.read(256 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                if destination.stat().st_size != member.size or member.size == 0:
                    raise ValueError("Whisper model file was incomplete.")
                selected.add(relative)
                progress(90 + len(selected) * 3)
        while reader.read(256 * 1024):
            pass
    if selected != set(REQUIRED_FILES):
        raise ValueError("Whisper model archive is missing required files.")


def download_transcription_model(directory, progress=lambda value: None, *, cancelled=None):
    _check_cancelled(cancelled)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (".whisper-download-" + uuid.uuid4().hex)
    temporary.mkdir()
    archive = temporary / ASSET_NAME
    digest = hashlib.sha256()
    try:
        expected_digest = _published_sha256()
        _check_cancelled(cancelled)
        with urllib.request.urlopen(URL, timeout=30) as response, archive.open("wb") as output:
            if not response.geturl().lower().startswith("https://"):
                raise ValueError("Whisper model download requires verified HTTPS.")
            total = int(response.headers.get("Content-Length", "0"))
            if total < 0 or total > MAX_DOWNLOAD_BYTES:
                raise ValueError("Whisper model download exceeded its expected size.")
            downloaded = 0
            while True:
                _check_cancelled(cancelled)
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD_BYTES:
                    raise ValueError("Whisper model download exceeded its expected size.")
                digest.update(chunk)
                output.write(chunk)
                progress(min(90, int(downloaded * 90 / total)) if total else 0)
            if total and downloaded != total:
                raise ValueError("Whisper model download was incomplete.")
        observed_digest = digest.hexdigest()
        if expected_digest is not None and observed_digest != expected_digest:
            raise ValueError("Whisper model did not match GitHub's published SHA-256 digest.")
        _extract_archive(archive, temporary, progress, cancelled)
        extracted = temporary / MODEL_NAME
        (extracted / "download.json").write_text(json.dumps({
            "source": URL, "asset_metadata": ASSET_METADATA_URL,
            "sha256": observed_digest, "published_sha256": expected_digest,
            "checksum_source": "github_asset_digest" if expected_digest else "locally_observed_download",
        }), encoding="utf-8")
        _check_cancelled(cancelled)
        target = directory / MODEL_NAME
        backup = None
        if target.exists():
            backup = directory / f"{MODEL_NAME}-recovery-{int(time.time())}-{uuid.uuid4().hex[:8]}"
            target.rename(backup)
        try:
            extracted.rename(target)
        except Exception:
            if backup is not None and not target.exists():
                backup.rename(target)
            raise
        progress(100)
        return target
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


download_transcription = download_transcription_model


class TranscriptionInstaller(Worker):
    progress = Signal(int)
    ready = Signal()
    failed = Signal(str)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        try:
            download_transcription_model(self.store.directory / "models", self.progress.emit,
                                         cancelled=self.cancelled.is_set)
            if not self.cancelled.is_set():
                self.ready.emit()
        except TranscriptionDownloadCancelled:
            pass
        except Exception:
            if not self.cancelled.is_set():
                self.failed.emit("Enhanced listening setup failed. Allow github.com, api.github.com and release-assets.githubusercontent.com, check the connection, then retry voice setup. Basic listening and typed commands still work.")
