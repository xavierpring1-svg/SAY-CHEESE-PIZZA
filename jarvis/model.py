"""First-run download from Vosk's official HTTPS model distribution."""
import hashlib
import json
import shutil
import stat
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

from PySide6.QtCore import Signal
from .core import ROOT
from .worker import Worker

NAME = "vosk-model-small-en-us-0.15"
URL = "https://alphacephei.com/vosk/models/" + NAME + ".zip"


def model_path(store):
    candidates = [ROOT / "models" / NAME, store.directory / "models" / NAME]
    for path in candidates:
        if (path / "am/final.mdl").is_file() and (path / "conf/model.conf").is_file():
            return path
    return None


def download_model(directory, progress=lambda value: None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (".download-" + uuid.uuid4().hex)
    temporary.mkdir()
    archive = temporary / "model.zip"
    try:
        with urllib.request.urlopen(URL, timeout=30) as response, archive.open("wb") as output:
            total = int(response.headers.get("Content-Length", "0"))
            downloaded = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if downloaded > 100 * 1024 * 1024:
                    raise ValueError("Voice model download exceeded the expected size.")
                progress(min(95, int(downloaded * 95 / total)) if total else 0)
            if total and downloaded != total:
                raise ValueError("Voice model download was incomplete.")
        with zipfile.ZipFile(archive) as bundle:
            if sum(info.file_size for info in bundle.infolist()) > 250 * 1024 * 1024:
                raise ValueError("Voice model archive exceeded the expected size.")
            for info in bundle.infolist():
                target = (temporary / info.filename).resolve()
                if not target.is_relative_to(temporary.resolve()) or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError("Unsafe voice model archive.")
            corrupt = bundle.testzip()
            if corrupt:
                raise ValueError("Voice model archive failed its integrity check.")
            bundle.extractall(temporary)
        extracted = temporary / NAME
        if not (extracted / "am/final.mdl").is_file() or not (extracted / "conf/model.conf").is_file():
            raise ValueError("Voice model is missing required files.")
        target = directory / NAME
        if target.exists():
            target.rename(directory / f"{NAME}-recovery-{int(time.time())}")
        extracted.rename(target)
        (target / "download.json").write_text(json.dumps({"source": URL, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}))
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

    def run(self):
        try:
            download_model(self.store.directory / "models", self.progress.emit)
            self.ready.emit()
        except Exception:
            self.failed.emit("Voice model download failed. Check your internet connection and allow alphacephei.com, then click Retry voice setup. Typed commands still work.")
