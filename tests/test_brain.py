import hashlib
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import urllib.error
import urllib.request
import zipfile

import pytest

from jarvis import brain


MODEL_BYTES = b"GGUF" + b"a verified tiny model fixture" * 5


def metadata(data=MODEL_BYTES):
    return {"id": brain.MODEL_REPO, "sha": "a" * 40, "siblings": [
        {"rfilename": brain.MODEL_FILENAME,
         "lfs": {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}}]}


def cached_plan(service, data=MODEL_BYTES):
    plan = brain.model_plan(metadata(data))
    service.manifest_path.write_text(json.dumps(plan))
    return plan


class Response(io.BytesIO):
    def __init__(self, content, status=200, headers=None):
        super().__init__(content)
        self.status = status
        self.headers = headers if headers is not None else {"Content-Length": str(len(content))}


def service(tmp_path, **kwargs):
    return brain.LocalBrain(SimpleNamespace(directory=tmp_path), **kwargs)


def test_model_revision_and_lfs_checksum_are_pinned():
    plan = brain.model_plan(metadata())
    assert plan["revision"] == "a" * 40
    assert plan["sha256"] == hashlib.sha256(MODEL_BYTES).hexdigest()
    assert plan["repo"] == brain.MODEL_REPO


@pytest.mark.parametrize("change", [
    lambda d: d.update(id="attacker/replacement"),
    lambda d: d.update(sha="main"),
    lambda d: d["siblings"][0]["lfs"].update(sha256="bad"),
    lambda d: d["siblings"][0]["lfs"].update(size=brain.MODEL_MAX_BYTES + 1),
    lambda d: d["siblings"][0].update(rfilename="../" + brain.MODEL_FILENAME),
])
def test_reject_unverifiable_model_metadata(change):
    data = metadata()
    change(data)
    with pytest.raises(RuntimeError):
        brain.model_plan(data)


@pytest.mark.parametrize("url", [
    "http://huggingface.co/model", "https://huggingface.co.attacker.com/model",
    "https://user:secret@huggingface.co/model", "https://localhost/model",
    "https://127.0.0.1/model", "file:///tmp/model",
])
def test_model_redirects_cannot_leave_publisher_cdns(url):
    handler = brain._ModelRedirects()
    request = urllib.request.Request(brain.MODEL_METADATA_URL)
    with pytest.raises(RuntimeError):
        handler.redirect_request(request, None, 302, "Moved", {}, url)


def test_accept_official_https_model_cdn():
    assert brain._allowed_model_url("https://cas-bridge.xethub.hf.co/a?signature=test")
    assert brain._allowed_model_url("https://cdn-lfs.huggingface.co/model")


def test_model_download_uses_immutable_revision_and_verifies_digest(tmp_path, monkeypatch):
    messages, requests = [], []
    local = service(tmp_path, status=messages.append)

    def opened(request, timeout):
        requests.append(request)
        if "/api/models/" in request.full_url:
            return Response(json.dumps(metadata()).encode())
        return Response(MODEL_BYTES)

    monkeypatch.setattr(brain, "_model_open", opened)
    result = local.ensure_model()
    assert result.read_bytes() == MODEL_BYTES
    assert "/resolve/" + "a" * 40 + "/" in requests[-1].full_url
    assert local.downloaded
    assert any("100%" in message for message in messages)
    assert not local.partial_path.exists()
    assert not local.ready


def test_model_can_resume_checked_range(tmp_path, monkeypatch):
    local = service(tmp_path)
    cached_plan(local)
    local.partial_path.write_bytes(MODEL_BYTES[:20])

    def opened(request, timeout):
        assert request.get_header("Range") == "bytes=20-"
        return Response(MODEL_BYTES[20:], 206, {
            "Content-Length": str(len(MODEL_BYTES) - 20),
            "Content-Range": f"bytes 20-{len(MODEL_BYTES)-1}/{len(MODEL_BYTES)}"})

    monkeypatch.setattr(brain, "_model_open", opened)
    assert local.ensure_model().read_bytes() == MODEL_BYTES


def test_model_resume_ignored_by_cdn_restarts_safely(tmp_path, monkeypatch):
    local = service(tmp_path)
    cached_plan(local)
    local.partial_path.write_bytes(b"bad partial")
    monkeypatch.setattr(brain, "_model_open", lambda *_args, **_kwargs: Response(MODEL_BYTES))
    assert local.ensure_model().read_bytes() == MODEL_BYTES


def test_complete_partial_is_verified_before_promotion_without_network(tmp_path, monkeypatch):
    local = service(tmp_path)
    cached_plan(local)
    local.partial_path.write_bytes(MODEL_BYTES)
    monkeypatch.setattr(brain, "_model_open", lambda *_a, **_k: pytest.fail("no download needed"))
    assert local.ensure_model().read_bytes() == MODEL_BYTES


def test_wrong_range_rejected_and_not_promoted(tmp_path, monkeypatch):
    local = service(tmp_path)
    cached_plan(local)
    local.partial_path.write_bytes(MODEL_BYTES[:20])
    monkeypatch.setattr(brain, "_model_open", lambda *_a, **_k: Response(MODEL_BYTES, 206, {
        "Content-Range": f"bytes 0-{len(MODEL_BYTES)-1}/{len(MODEL_BYTES)}"}))
    with pytest.raises(RuntimeError, match="byte range"):
        local.ensure_model()
    assert not local.model_path.exists()


def test_bad_model_checksum_never_loaded(tmp_path, monkeypatch):
    local = service(tmp_path)
    cached_plan(local)
    monkeypatch.setattr(brain, "_model_open", lambda *_a, **_k: Response(b"GGUF" + b"x" * (len(MODEL_BYTES) - 4)))
    with pytest.raises(RuntimeError, match="checksum"):
        local.ensure_model()
    assert not local.model_path.exists()
    assert not local.partial_path.exists()


def test_cached_model_checked_without_network(tmp_path, monkeypatch):
    local = service(tmp_path)
    cached_plan(local)
    local.model_path.write_bytes(MODEL_BYTES)
    monkeypatch.setattr(brain, "_model_open", lambda *_a, **_k: pytest.fail("offline model"))
    assert local.ensure_model() == local.model_path


def test_interrupted_download_preserves_verified_plan_and_partial(tmp_path, monkeypatch):
    local = service(tmp_path)
    cached_plan(local)
    monkeypatch.setattr(brain, "_model_open", lambda *_a, **_k: Response(MODEL_BYTES[:20], headers={}))
    with pytest.raises(RuntimeError, match="interrupted"):
        local.ensure_model()
    assert local.partial_path.read_bytes() == MODEL_BYTES[:20]
    assert local.manifest_path.exists()


def test_model_is_cancelled_without_hitting_network(tmp_path, monkeypatch):
    local = service(tmp_path)
    local.stop()
    monkeypatch.setattr(brain, "_model_open", lambda *_a, **_k: pytest.fail("cancelled"))
    with pytest.raises(brain.BrainCancelled):
        local.ensure_model()


def test_metadata_connection_failure_explains_one_time_download(tmp_path, monkeypatch):
    local = service(tmp_path)

    def failure(*_a, **_k):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(brain, "_model_open", failure)
    with pytest.raises(RuntimeError, match="one-time model download"):
        local.ensure_model()


def make_runtime(tmp_path, monkeypatch):
    archive = tmp_path / "native.zip"
    with zipfile.ZipFile(archive, "w") as package:
        for name in brain.RUNTIME_FILES:
            package.writestr(name, b"verified native binary fixture " + name.encode())
        package.writestr("unneeded-cli.exe", b"leave this out")
    monkeypatch.setattr(brain, "RUNTIME_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    monkeypatch.setattr(brain, "RUNTIME_SIZE", archive.stat().st_size)
    app_runtime = tmp_path / "portable-runtime"
    qt = app_runtime / "Lib/site-packages/PySide6"
    qt.mkdir(parents=True)
    for name in brain.CRT_FILES:
        (qt / name).write_bytes(b"verified bundled CRT fixture " + name.encode())
    return archive, app_runtime


def test_native_runtime_archive_checksum_and_dll_closure(tmp_path, monkeypatch):
    archive, app_runtime = make_runtime(tmp_path, monkeypatch)
    installed = brain.install_runtime(tmp_path / "brain-runtime", app_runtime, archive)
    assert brain.runtime_valid(installed)
    assert not (installed / "unneeded-cli.exe").exists()
    manifest = json.loads((installed / "runtime-manifest.json").read_text())
    assert manifest["digest_source"].startswith("https://api.github.com/")
    assert set(manifest["files"]) == brain.RUNTIME_FILES | brain.CRT_FILES | {brain.PROJECT_LICENSE}
    assert (installed / brain.PROJECT_LICENSE).read_text().startswith("MIT License")
    assert manifest["license_sha256"] == brain.PROJECT_LICENSE_SHA256


def test_native_tampering_invalidates_cache(tmp_path, monkeypatch):
    archive, app_runtime = make_runtime(tmp_path, monkeypatch)
    installed = brain.install_runtime(tmp_path / "brain-runtime", app_runtime, archive)
    (installed / "llama-server.exe").write_bytes(b"damaged")
    assert not brain.runtime_valid(installed)


def test_native_missing_crt_is_reported_and_staging_removed(tmp_path, monkeypatch):
    archive, _app_runtime = make_runtime(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="Microsoft runtime DLL"):
        brain.install_runtime(tmp_path / "brain-runtime", tmp_path / "missing", archive)
    assert not (tmp_path / "brain-runtime-staging").exists()


def test_native_project_license_is_required(tmp_path, monkeypatch):
    archive, app_runtime = make_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(brain, "ROOT", tmp_path / "missing-license")
    with pytest.raises(RuntimeError, match="runtime license"):
        brain.install_runtime(tmp_path / "brain-runtime", app_runtime, archive)
    assert not (tmp_path / "brain-runtime-staging").exists()


@pytest.mark.parametrize("url", [
    "https://attacker.com/native.zip", "http://github.com/native.zip", "https://github.com.attacker.com/file",
])
def test_native_redirect_security(url):
    with pytest.raises(RuntimeError):
        brain._RuntimeRedirects().redirect_request(urllib.request.Request(brain.RUNTIME_URL), None, 302, "Moved", {}, url)


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


def test_server_binds_loopback_random_key_and_stops(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "llama-server").write_text("test")
    local = service(tmp_path, runtime_directory=runtime)
    cached_plan(local)
    local.model_path.write_bytes(MODEL_BYTES)
    process = FakeProcess()
    invocations, health_requests = [], []

    def popen(command, **kwargs):
        invocations.append((command, kwargs))
        return process

    class Opener:
        def open(self, request, timeout):
            health_requests.append(request)
            return Response(b'{"status":"ok"}')

    monkeypatch.setattr(brain.subprocess, "Popen", popen)
    monkeypatch.setattr(brain.urllib.request, "build_opener", lambda *_a: Opener())
    endpoint = local.ensure_ready()
    assert endpoint.startswith("http://127.0.0.1:") and endpoint.endswith("/v1/chat/completions")
    command, kwargs = invocations[0]
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--api-key") + 1] == local.token
    assert len(local.token) >= 40
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["creationflags"] == brain.PROCESS_FLAGS
    assert health_requests[0].get_header("Authorization") == "Bearer " + local.token
    assert local.ready
    assert local.ensure_ready() == endpoint
    assert len(invocations) == 1
    assert local.token not in local.manifest_path.read_text()
    local.stop()
    assert process.terminated and not local.ready and not local.token


def test_crashed_server_is_cleared(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "llama-server").write_text("test")
    local = service(tmp_path, runtime_directory=runtime)
    cached_plan(local)
    local.model_path.write_bytes(MODEL_BYTES)
    monkeypatch.setattr(brain.subprocess, "Popen", lambda *_a, **_k: FakeProcess(1))
    with pytest.raises(RuntimeError, match="stopped while loading"):
        local.ensure_ready()
    assert local.process is None and not local.endpoint and not local.token
