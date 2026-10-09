"""Install a selected offline recognizer from Vosk's official HTTPS source."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from PySide6.QtCore import Signal
from .core import ROOT
from .worker import Worker

@dataclass(frozen=True)
class ModelSpec:
    name: str
    label: str
    download_mb: int
    max_download_bytes: int
    max_expanded_bytes: int

    @property
    def url(self):
        return "https://alphacephei.com/vosk/models/" + self.name + ".zip"


# Names and sizes are from https://alphacephei.com/vosk/models. Its benchmarks
# describe US English datasets, not a guarantee for every person's voice.
MODELS = {
    "accurate": ModelSpec("vosk-model-en-us-0.22-lgraph", "Accurate English", 128,
                          200 * 1024 * 1024, 800 * 1024 * 1024),
    "compact": ModelSpec("vosk-model-small-en-us-0.15", "Compact English", 40,
                         100 * 1024 * 1024, 250 * 1024 * 1024),
}
DEFAULT_MODEL_KEY = "accurate"

# Keep compact-model constants and the direct-call download default compatible.
NAME = MODELS["compact"].name
URL = MODELS["compact"].url


def selected_model_key(store):
    key = store.settings.get("recognition_model", DEFAULT_MODEL_KEY)
    return key if isinstance(key, str) and key in MODELS else DEFAULT_MODEL_KEY


def model_path(store, model_key=None):
    key = selected_model_key(store) if model_key is None else model_key
    if key not in MODELS:
        raise ValueError("Choose the accurate or compact English recognition model.")
    name = MODELS[key].name
    candidates = [ROOT / "models" / name, store.directory / "models" / name]
    for path in candidates:
        if (path / "am/final.mdl").is_file() and (path / "conf/model.conf").is_file():
            return path
    return None


class ModelDownloadCancelled(RuntimeError):
    pass


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise ModelDownloadCancelled("Voice model download cancelled.")


def _member_path(info, temporary, model_name):
    # Check both path separator conventions even when tests run on Linux.
    name = info.filename.replace("\\", "/")
    path = PurePosixPath(name)
    mode = info.external_attr >> 16
    if (not path.parts or path.is_absolute() or path.parts[0] != model_name
            or any(part in {".", ".."} or ":" in part or part.rstrip(" .") != part
                   or any(unicodedata.category(character) == "Cc" for character in part)
                   or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I)
                   for part in path.parts)
            or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
        raise ValueError("Unsafe voice model archive.")
    target = (temporary / Path(*path.parts)).resolve()
    if not target.is_relative_to(temporary.resolve()):
        raise ValueError("Unsafe voice model archive.")
    return target


def download_model(directory, progress=lambda value: None, model_key="compact", *, cancelled=None):
    if model_key not in MODELS:
        raise ValueError("Choose the accurate or compact English recognition model.")
    spec = MODELS[model_key]
    _check_cancelled(cancelled)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (".download-" + uuid.uuid4().hex)
    temporary.mkdir()
    archive = temporary / "model.zip"
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(spec.url, timeout=30) as response, archive.open("wb") as output:
            final_url = getattr(response, "geturl", lambda: spec.url)()
            if urllib.parse.urlsplit(final_url).scheme.lower() != "https":
                raise ValueError("Voice model download must use a verified HTTPS connection.")
            total = int(response.headers.get("Content-Length", "0"))
            if total < 0 or total > spec.max_download_bytes:
                raise ValueError("Voice model download exceeded the expected size.")
            downloaded = 0
            while True:
                _check_cancelled(cancelled)
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > spec.max_download_bytes:
                    raise ValueError("Voice model download exceeded the expected size.")
                output.write(chunk)
                digest.update(chunk)
                progress(min(90, int(downloaded * 90 / total)) if total else 0)
            if total and downloaded != total:
                raise ValueError("Voice model download was incomplete.")
        _check_cancelled(cancelled)
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            total_expanded = sum(info.file_size for info in members)
            if len(members) > 6000 or total_expanded > spec.max_expanded_bytes:
                raise ValueError("Voice model archive exceeded the expected size.")
            targets = [(info, _member_path(info, temporary, spec.name)) for info in members]
            expanded = 0
            # ZipExtFile verifies each CRC at EOF. Streaming once avoids the
            # extra decompression pass of testzip() on the larger model.
            for info, destination in targets:
                _check_cancelled(cancelled)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, destination.open("wb") as output:
                    while True:
                        _check_cancelled(cancelled)
                        chunk = source.read(256 * 1024)
                        if not chunk:
                            break
                        expanded += len(chunk)
                        if expanded > spec.max_expanded_bytes:
                            raise ValueError("Voice model archive exceeded the expected size.")
                        output.write(chunk)
                        progress(90 + min(9, int(expanded * 9 / total_expanded)) if total_expanded else 90)
        extracted = temporary / spec.name
        if not (extracted / "am/final.mdl").is_file() or not (extracted / "conf/model.conf").is_file():
            raise ValueError("Voice model is missing required files.")
        # Record the received digest without presenting it as an official
        # checksum: the public Vosk catalog provides no reference SHA-256.
        (extracted / "download.json").write_text(json.dumps({
            "source": spec.url, "model_key": model_key,
            "sha256": digest.hexdigest(), "checksum_source": "locally_observed_download",
        }), encoding="utf-8")
        _check_cancelled(cancelled)
        target = directory / spec.name
        backup = None
        if target.exists():
            backup = directory / f"{spec.name}-recovery-{int(time.time())}-{uuid.uuid4().hex[:8]}"
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


class ModelInstaller(Worker):
    progress = Signal(int)
    ready = Signal()
    failed = Signal(str)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.model_key = selected_model_key(store)
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        try:
            download_model(self.store.directory / "models", self.progress.emit,
                           model_key=self.model_key, cancelled=self.cancelled.is_set)
            if not self.cancelled.is_set():
                self.ready.emit()
        except ModelDownloadCancelled:
            pass
        except Exception:
            if not self.cancelled.is_set():
                self.failed.emit("Voice model download failed. Check your internet connection and allow alphacephei.com, then click Retry voice setup. Typed commands still work.")
