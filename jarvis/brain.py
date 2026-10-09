"""Private, local conversation server with verified first-use model acquisition.

The small CPU inference runtime and the larger Qwen model are downloaded once,
from their official publishers, into AppData. The
revision and LFS digest from official metadata are pinned before any model bytes
are accepted. No prompts, microphone audio, or server keys leave this computer.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from .core import ROOT

MODEL_REPO = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
MODEL_FILENAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_METADATA_URL = f"https://huggingface.co/api/models/{MODEL_REPO}?blobs=true"
MODEL_MAX_BYTES = 2 * 1024 ** 3
JSON_MAX_BYTES = 8 * 1024 ** 2
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
PROCESS_FLAGS = NO_WINDOW | (0x00004000 if os.name == "nt" else 0)  # Below-normal CPU priority on Windows.
RUNTIME_TAG = "b11524"
RUNTIME_FILENAME = "llama-b11524-bin-win-cpu-x64.zip"
RUNTIME_SIZE = 19_518_613
RUNTIME_SHA256 = "66aae07a0a7e37028adbc391ade7efc9693b2015c3d31ffb19fc3c8bfa8787ae"
RUNTIME_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{RUNTIME_TAG}/{RUNTIME_FILENAME}"
RUNTIME_DIGEST_SOURCE = f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{RUNTIME_TAG}"
RUNTIME_FILES = frozenset({
    "llama-server.exe", "llama-server-impl.dll", "llama-common.dll", "llama.dll",
    "ggml-base.dll", "ggml.dll", "mtmd.dll", "libomp.dll", "LICENSE-LLVM-OpenMP",
    "ggml-cpu-x64.dll", "ggml-cpu-sse42.dll", "ggml-cpu-haswell.dll",
    "ggml-cpu-alderlake.dll", "ggml-cpu-zen4.dll",
})
CRT_FILES = frozenset({"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"})
PROJECT_LICENSE = "llama.cpp-LICENSE"
PROJECT_LICENSE_URL = f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{RUNTIME_TAG}/LICENSE"
PROJECT_LICENSE_SHA256 = "94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d"


class BrainCancelled(RuntimeError):
    pass


def _file_sha256(path, check=lambda: None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        while block := file.read(1024 * 1024):
            check()
            digest.update(block)
    return digest.hexdigest()


class _RuntimeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        parsed = urllib.parse.urlparse(new_url)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.hostname not in {"github.com", "release-assets.githubusercontent.com",
                                           "objects.githubusercontent.com"}):
            raise RuntimeError("The conversation runtime redirected to an unexpected server.")
        return super().redirect_request(request, response, code, message, headers, new_url)


def runtime_valid(directory):
    directory = Path(directory)
    try:
        manifest_path = directory / "runtime-manifest.json"
        if manifest_path.stat().st_size > 128 * 1024:
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("archive_sha256") != RUNTIME_SHA256:
            return False
        records = manifest.get("files", {})
        if set(records) != RUNTIME_FILES | CRT_FILES | {PROJECT_LICENSE}:
            return False
        for name, digest in records.items():
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                return False
            if not secrets.compare_digest(_file_sha256(directory / name), digest):
                return False
        return True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def install_runtime(directory, app_runtime=None, archive=None, status=None, check=None):
    """Download a pinned official archive and copy only the server DLL closure.

    app_runtime is the already-verified portable Python/Qt runtime from the app
    package. Its matching Microsoft redistributable DLLs are reused locally.
    """
    directory = Path(directory)
    notify, check = status or (lambda _message: None), check or (lambda: None)
    if runtime_valid(directory):
        return directory
    check()
    directory.parent.mkdir(parents=True, exist_ok=True)
    archive = Path(archive) if archive else directory.parent / RUNTIME_FILENAME
    if archive.is_file() and (archive.stat().st_size != RUNTIME_SIZE
                             or _file_sha256(archive, check) != RUNTIME_SHA256):
        archive.unlink()
    if not archive.is_file():
        notify("Preparing private conversation · downloading its 19 MB CPU runtime")
        request = urllib.request.Request(RUNTIME_URL, headers={"User-Agent": "JarvisDesktop/1.2"})
        temporary = archive.with_suffix(".part")
        written = 0
        try:
            with urllib.request.build_opener(_RuntimeRedirects()).open(request, timeout=30) as response:
                with temporary.open("wb") as file:
                    while block := response.read(1024 * 1024):
                        check()
                        written += len(block)
                        if written > RUNTIME_SIZE:
                            raise RuntimeError("The conversation runtime exceeded its verified size.")
                        file.write(block)
            if written != RUNTIME_SIZE or _file_sha256(temporary, check) != RUNTIME_SHA256:
                raise RuntimeError("The conversation runtime failed its official checksum. "
                                   "It was not executed. Try again.")
            os.replace(temporary, archive)
        except (urllib.error.URLError, OSError) as error:
            raise RuntimeError("I couldn't download the private conversation runtime. "
                               "Check your internet connection and try again.") from error
        finally:
            temporary.unlink(missing_ok=True)
    notify("Verifying and preparing the private conversation runtime")
    check()
    staging = directory.with_name(directory.name + "-staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        with zipfile.ZipFile(archive) as package:
            if package.testzip() is not None:
                raise RuntimeError("The conversation runtime archive is damaged.")
            if sum(item.file_size for item in package.infolist()) > 128 * 1024 ** 2:
                raise RuntimeError("The conversation runtime archive is too large.")
            entries = {item.filename: item for item in package.infolist()}
            if not RUNTIME_FILES <= entries.keys():
                raise RuntimeError("The conversation runtime archive is incomplete.")
            for name in sorted(RUNTIME_FILES):
                check()
                (staging / name).write_bytes(package.read(entries[name]))
        app_runtime = Path(app_runtime or ROOT / "runtime")
        search_directories = [app_runtime, app_runtime / "Lib/site-packages/PySide6",
                              app_runtime / "Lib/site-packages/shiboken6",
                              app_runtime / "Lib/site-packages/winrt"]
        for name in sorted(CRT_FILES):
            source = next((candidate for folder in search_directories
                           for candidate in [folder / name, folder / name.upper()]
                           if candidate.is_file()), None)
            if source is None:
                # On a Windows case-insensitive filesystem, either spelling
                # finds the original mixed-case file. Development Linux needs
                # an explicit case-insensitive lookup in known runtime folders.
                source = next((candidate for folder in search_directories if folder.is_dir()
                               for candidate in folder.iterdir()
                               if candidate.is_file() and candidate.name.lower() == name), None)
            if source is None:
                raise RuntimeError("A Microsoft runtime DLL is missing. Extract the complete "
                                   "JARVIS download, including its runtime folder.")
            shutil.copy2(source, staging / name)
        license_source = ROOT / "third_party" / PROJECT_LICENSE
        if (not license_source.is_file()
                or _file_sha256(license_source, check) != PROJECT_LICENSE_SHA256):
            raise RuntimeError("The conversation runtime license is missing or damaged. "
                               "Extract the complete JARVIS download and try again.")
        shutil.copy2(license_source, staging / PROJECT_LICENSE)
        manifest = {"project": "ggml-org/llama.cpp", "release": RUNTIME_TAG,
                    "archive_url": RUNTIME_URL, "archive_sha256": RUNTIME_SHA256,
                    "digest_source": RUNTIME_DIGEST_SOURCE,
                    "license_url": PROJECT_LICENSE_URL, "license_sha256": PROJECT_LICENSE_SHA256,
                    "files": {name: _file_sha256(staging / name, check)
                              for name in sorted(RUNTIME_FILES | CRT_FILES | {PROJECT_LICENSE})}}
        (staging / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        check()
        if directory.exists():
            shutil.rmtree(directory)
        os.replace(staging, directory)
        return directory
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _allowed_model_url(url):
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    return (parsed.scheme == "https" and not parsed.username and not parsed.password
            and (host == "huggingface.co" or host.endswith(".huggingface.co")
                 or host.endswith(".hf.co") or host.endswith(".xethub.hf.co")))


class _ModelRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if not _allowed_model_url(new_url):
            raise RuntimeError("The model download redirected to an unexpected server.")
        return super().redirect_request(request, response, code, message, headers, new_url)


def _model_open(request, timeout=30):
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    if not _allowed_model_url(url):
        raise RuntimeError("Only the official model download is supported.")
    return urllib.request.build_opener(_ModelRedirects()).open(request, timeout=timeout)


def model_plan(metadata):
    """Extract immutable revision, size and SHA256 from official HF metadata."""
    if not isinstance(metadata, dict):
        raise RuntimeError("The official model metadata is invalid.")
    if metadata.get("id", MODEL_REPO) != MODEL_REPO:
        raise RuntimeError("The model metadata identifies an unexpected publisher.")
    revision = metadata.get("sha", "")
    if not isinstance(revision, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", revision):
        raise RuntimeError("The model's immutable revision is missing.")
    for item in metadata.get("siblings", []):
        if not isinstance(item, dict):
            continue
        filename = item.get("rfilename", "")
        if not isinstance(filename, str) or filename.lower() != MODEL_FILENAME:
            continue
        lfs = item.get("lfs") or {}
        digest, size = lfs.get("sha256"), lfs.get("size")
        if (not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest)
                or not isinstance(size, int) or isinstance(size, bool)
                or size < 4 or size > MODEL_MAX_BYTES):
            raise RuntimeError("The official model's LFS checksum or size is missing.")
        return {"repo": MODEL_REPO, "filename": filename, "revision": revision.lower(),
                "sha256": digest.lower(), "size": size}
    raise RuntimeError("The official conversation model is currently unavailable.")


def _validate_plan(plan):
    if not isinstance(plan, dict) or plan.get("repo") != MODEL_REPO:
        raise ValueError("Invalid cached model publisher")
    checked = model_plan({"id": plan["repo"], "sha": plan.get("revision"), "siblings": [
        {"rfilename": plan.get("filename"), "lfs": {
            "sha256": plan.get("sha256"), "size": plan.get("size")}}]})
    return checked


class LocalBrain:
    def __init__(self, store, status=None, runtime_directory=None):
        self.store = store
        self.status = status or (lambda _message: None)
        self.directory = Path(store.directory) / "conversation"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.model_path = self.directory / MODEL_FILENAME
        self.manifest_path = self.directory / "model-manifest.json"
        self.partial_path = self.directory / (MODEL_FILENAME + ".part")
        self.runtime_directory = Path(runtime_directory) if runtime_directory else self.directory / "runtime"
        self.endpoint = ""
        self.token = ""
        self.process = None
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._verified = None

    @property
    def downloaded(self):
        return self.model_path.is_file() and self.manifest_path.is_file()

    @property
    def ready(self):
        return self.process is not None and self.process.poll() is None and bool(self.endpoint)

    def _check(self):
        if self._cancelled.is_set():
            raise BrainCancelled("Conversation setup stopped.")

    def _notify(self, message):
        self.status(message)

    def _read_plan(self):
        try:
            if self.manifest_path.stat().st_size > JSON_MAX_BYTES:
                return None
            return _validate_plan(json.loads(self.manifest_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            return None

    def _fetch_plan(self):
        self._check()
        self._notify("Preparing private conversation · checking the official Qwen model")
        request = urllib.request.Request(MODEL_METADATA_URL, headers={"User-Agent": "JarvisDesktop/1.2"})
        try:
            with _model_open(request, timeout=25) as response:
                data = response.read(JSON_MAX_BYTES + 1)
            if len(data) > JSON_MAX_BYTES:
                raise RuntimeError("The model metadata is too large.")
            plan = model_plan(json.loads(data))
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise RuntimeError("Conversation needs a one-time model download. I couldn't reach "
                               "Hugging Face. Check your internet connection and try again; "
                               "desktop commands still work.") from error
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        os.replace(temporary, self.manifest_path)
        return plan

    def _hash_model(self, path, plan):
        if not path.is_file() or path.stat().st_size != plan["size"]:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as file:
            if file.read(4) != b"GGUF":
                return False
            file.seek(0)
            while block := file.read(1024 * 1024):
                self._check()
                digest.update(block)
        return secrets.compare_digest(digest.hexdigest(), plan["sha256"])

    def _download_model(self, plan):
        self._check()
        size = plan["size"]
        offset = self.partial_path.stat().st_size if self.partial_path.exists() else 0
        if offset > size:
            self.partial_path.unlink()
            offset = 0
        required = max(0, size - offset) + 64 * 1024 ** 2
        if shutil.disk_usage(self.directory).free < required:
            raise RuntimeError("There isn't enough free disk space for the conversation model. "
                               "Free at least 1.5 GB and try again.")
        url = (f"https://huggingface.co/{MODEL_REPO}/resolve/{plan['revision']}/"
               + urllib.parse.quote(plan["filename"], safe="") + "?download=true")
        headers = {"User-Agent": "JarvisDesktop/1.2", "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        self._notify(f"Downloading conversation model · {offset * 100 // size}% "
                     f"({size / 1024 ** 3:.1f} GB once, then offline)")
        try:
            with _model_open(urllib.request.Request(url, headers=headers), timeout=30) as response:
                status = getattr(response, "status", 200)
                if status == 206:
                    content_range = response.headers.get("Content-Range", "")
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                    if (not match or int(match[1]) != offset or int(match[3]) != size
                            or int(match[2]) != size - 1):
                        raise RuntimeError("The resumed model download has an invalid byte range.")
                elif status == 200:
                    offset = 0  # The CDN ignored Range; safely restart the partial file.
                else:
                    raise RuntimeError("The official model server refused the download.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isdigit() or int(length) != size - offset):
                    raise RuntimeError("The conversation model download has an unexpected size.")
                written, last_percent = offset, -1
                with self.partial_path.open("ab" if offset else "wb") as file:
                    while block := response.read(1024 * 1024):
                        self._check()
                        written += len(block)
                        if written > size:
                            raise RuntimeError("The conversation model exceeded its verified size.")
                        file.write(block)
                        percent = written * 100 // size
                        if percent != last_percent:
                            self._notify(f"Downloading conversation model · {percent}%")
                            last_percent = percent
                if written != size:
                    raise RuntimeError("The conversation model download was interrupted. "
                                       "Try again to resume it.")
        except (urllib.error.URLError, OSError) as error:
            raise RuntimeError("Conversation model download paused. Check your connection "
                               "and try again; it will resume where possible.") from error
        self._notify("Verifying the conversation model's official SHA256 checksum")
        if not self._hash_model(self.partial_path, plan):
            self.partial_path.unlink(missing_ok=True)
            raise RuntimeError("The conversation model failed checksum verification. "
                               "It was not loaded. Try the download again.")
        os.replace(self.partial_path, self.model_path)
        stat = self.model_path.stat()
        self._verified = (plan["sha256"], stat.st_size, stat.st_mtime_ns)

    def ensure_model(self):
        """Blocking; call on a worker, never the UI or microphone capture thread."""
        self._check()
        plan = self._read_plan()
        if plan is None:
            self.partial_path.unlink(missing_ok=True)
            plan = self._fetch_plan()
        stat = self.model_path.stat() if self.model_path.exists() else None
        signature = (plan["sha256"], stat.st_size, stat.st_mtime_ns) if stat else None
        if signature and signature == self._verified:
            return self.model_path
        if self.model_path.exists():
            self._notify("Checking the private conversation model")
            if self._hash_model(self.model_path, plan):
                self._verified = signature
                return self.model_path
            self.model_path.unlink()
        if self.partial_path.exists() and self.partial_path.stat().st_size == plan["size"]:
            self._notify("Verifying the downloaded conversation model")
            if self._hash_model(self.partial_path, plan):
                os.replace(self.partial_path, self.model_path)
                stat = self.model_path.stat()
                self._verified = (plan["sha256"], stat.st_size, stat.st_mtime_ns)
                return self.model_path
            self.partial_path.unlink()
        self._download_model(plan)
        return self.model_path

    def ensure_ready(self):
        """Start a token-protected, loopback-only server owned by this app."""
        with self._lock:
            self._check()
            if self.ready:
                return self.endpoint
            if os.name == "nt":
                install_runtime(self.runtime_directory, status=self.status, check=self._check)
            binary = self.runtime_directory / ("llama-server.exe" if os.name == "nt" else "llama-server")
            if not binary.is_file():
                raise RuntimeError("The private conversation runtime is missing. Use the "
                                   "complete Windows 64-bit JARVIS download.")
            model = self.ensure_model()
            self._check()
            self._notify("Starting private conversation · loading the model into memory")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as temporary_socket:
                temporary_socket.bind(("127.0.0.1", 0))
                port = temporary_socket.getsockname()[1]
            token = secrets.token_urlsafe(32)
            command = [str(binary), "--model", str(model), "--host", "127.0.0.1",
                       "--port", str(port), "--api-key", token, "--alias", "jarvis-local",
                       "--ctx-size", "4096", "--parallel", "1", "--threads", str(min(8, max(2, (os.cpu_count() or 2) // 2))),
                       "--n-gpu-layers", "0", "--jinja", "--no-webui"]
            try:
                process = subprocess.Popen(command, cwd=self.runtime_directory,
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, creationflags=PROCESS_FLAGS)
            except OSError as error:
                raise RuntimeError("The private conversation runtime could not start. "
                                   "Use the complete Windows 64-bit download and check available memory.") from error
            self.process = process
            base = f"http://127.0.0.1:{port}"
            try:
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    self._check()
                    if process.poll() is not None:
                        raise RuntimeError("The private conversation runtime stopped while loading. "
                                           "Close other heavy apps, then try again.")
                    request = urllib.request.Request(base + "/health", headers={"Authorization": "Bearer " + token})
                    try:
                        # Avoid proxy settings: this request never leaves loopback.
                        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2) as response:
                            body = json.loads(response.read(4096))
                        if isinstance(body, dict) and body.get("status") == "ok":
                            self._check()
                            self.endpoint, self.token = base + "/v1/chat/completions", token
                            self._notify("Private conversation ready · running on this computer")
                            return self.endpoint
                    except (urllib.error.URLError, OSError, ValueError):
                        pass
                    self._cancelled.wait(0.25)
                raise RuntimeError("The conversation model took too long to start. "
                                   "Close other heavy apps and try again.")
            except BaseException:
                self._terminate(process)
                self.process = None
                self.endpoint = self.token = ""
                raise

    @staticmethod
    def _terminate(process):
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

    def stop(self):
        self._cancelled.set()
        process = self.process
        self.endpoint = self.token = ""
        self._terminate(process)
        self.process = None
