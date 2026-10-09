import hashlib
import io
import json
import stat
import struct
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import jarvis.model as models


def archive_for(key="compact", members=None):
    buffer = io.BytesIO()
    name = models.MODELS[key].name
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        if members is None:
            members = {name + "/am/final.mdl": b"test-model", name + "/conf/model.conf": b"test-config"}
        for filename, content in members.items():
            archive.writestr(filename, content)
    return buffer.getvalue()


def serve(monkeypatch, content, *, length=None, on_read=None, response_url=None):
    requests = []

    class Response(io.BytesIO):
        def __init__(self):
            super().__init__(content)
            self.headers = {"Content-Length": str(len(content) if length is None else length)}

        def read(self, size=-1):
            if on_read:
                on_read()
            return super().read(size)

        def geturl(self):
            return response_url or models.URL

    def open_url(url, timeout):
        requests.append((url, timeout))
        return Response()

    monkeypatch.setattr(models.urllib.request, "urlopen", open_url)
    return requests


def fake_store(directory, selected="accurate"):
    return SimpleNamespace(directory=directory, settings={"recognition_model": selected})


def create_model(directory, key):
    path = directory / "models" / models.MODELS[key].name
    (path / "am").mkdir(parents=True)
    (path / "conf").mkdir()
    (path / "am/final.mdl").write_bytes(b"test-model")
    (path / "conf/model.conf").write_text("test-config")
    return path


def test_compact_install_does_not_satisfy_accurate_model_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "ROOT", tmp_path / "empty-checkout")
    compact = create_model(tmp_path, "compact")
    store = fake_store(tmp_path)
    assert models.model_path(store) is None
    assert models.model_path(store, "compact") == compact
    accurate = create_model(tmp_path, "accurate")
    assert models.model_path(store) == accurate
    store.settings["recognition_model"] = "compact"
    assert models.model_path(store) == compact


def test_default_model_is_accurate_and_invalid_saved_preference_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "ROOT", tmp_path / "empty-checkout")
    accurate = create_model(tmp_path, "accurate")
    store = fake_store(tmp_path)
    store.settings = {}
    assert models.model_path(store) == accurate
    store.settings["recognition_model"] = "obsolete-setting"
    assert models.model_path(store) == accurate
    with pytest.raises(ValueError, match="accurate or compact"):
        models.model_path(store, "unknown")


@pytest.mark.parametrize("key", ["accurate", "compact"])
def test_selected_model_install_is_complete_and_digest_is_streamed(tmp_path, monkeypatch, key):
    content = archive_for(key)
    requests = serve(monkeypatch, content)
    progress = []

    def forbid_read_bytes(self):
        raise AssertionError("Whole archive must not be loaded to calculate its digest.")

    monkeypatch.setattr(Path, "read_bytes", forbid_read_bytes)
    installed = models.download_model(tmp_path, progress.append, model_key=key)
    assert installed == tmp_path / models.MODELS[key].name
    assert (installed / "am/final.mdl").is_file()
    assert (installed / "conf/model.conf").is_file()
    metadata = json.loads((installed / "download.json").read_text())
    assert metadata == {
        "source": models.MODELS[key].url, "model_key": key,
        "sha256": hashlib.sha256(content).hexdigest(),
        "checksum_source": "locally_observed_download",
    }
    assert requests == [(models.MODELS[key].url, 30)]
    assert progress[-1] == 100
    assert not list(tmp_path.glob(".download-*"))


def test_direct_download_default_preserves_original_compact_model_api(tmp_path, monkeypatch):
    serve(monkeypatch, archive_for())
    installed = models.download_model(tmp_path)
    assert installed.name == models.NAME
    assert models.URL == models.MODELS["compact"].url


def test_selected_model_archive_cannot_silently_install_the_other_model(tmp_path, monkeypatch):
    serve(monkeypatch, archive_for("compact"))
    with pytest.raises(ValueError, match="Unsafe"):
        models.download_model(tmp_path, model_key="accurate")
    assert not (tmp_path / models.MODELS["accurate"].name).exists()
    assert not list(tmp_path.glob(".download-*"))


@pytest.mark.parametrize("filename", [
    "../../escape.txt", "/absolute/file", "C:/outside/file",
    "vosk-model-small-en-us-0.15/../../escape.txt",
    "vosk-model-small-en-us-0.15\\..\\..\\escape.txt",
    "vosk-model-small-en-us-0.15/am/final.mdl:stream",
    "vosk-model-small-en-us-0.15/am/NUL.txt",
    "vosk-model-small-en-us-0.15/am/unsafe. ",
])
def test_unsafe_archive_paths_are_rejected_and_cleaned(tmp_path, monkeypatch, filename):
    serve(monkeypatch, archive_for(members={filename: b"unsafe"}))
    with pytest.raises(ValueError, match="Unsafe"):
        models.download_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_archive_symbolic_links_are_rejected(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        link = zipfile.ZipInfo(models.NAME + "/am/final.mdl")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "outside")
    serve(monkeypatch, buffer.getvalue())
    with pytest.raises(ValueError, match="Unsafe"):
        models.download_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_crc_corruption_fails_before_installing_a_model(tmp_path, monkeypatch):
    content = bytearray(archive_for())
    # First ZIP local file header: name and extra-field lengths at offsets26/28.
    name_length, extra_length = struct.unpack_from("<HH", content, 26)
    first_data = 30 + name_length + extra_length
    content[first_data] ^= 1
    serve(monkeypatch, bytes(content))
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        models.download_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_oversized_download_header_is_refused(tmp_path, monkeypatch):
    serve(monkeypatch, b"", length=models.MODELS["compact"].max_download_bytes + 1)
    with pytest.raises(ValueError, match="expected size"):
        models.download_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_download_cannot_follow_a_redirect_to_unverified_http(tmp_path, monkeypatch):
    serve(monkeypatch, archive_for(), response_url="http://alphacephei.com/insecure.zip")
    with pytest.raises(ValueError, match="verified HTTPS"):
        models.download_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_oversized_stream_without_header_is_refused(tmp_path, monkeypatch):
    monkeypatch.setitem(models.MODELS, "compact", replace(models.MODELS["compact"], max_download_bytes=8))
    serve(monkeypatch, b"too-much-data", length=0)
    with pytest.raises(ValueError, match="expected size"):
        models.download_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_expanded_archive_size_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setitem(models.MODELS, "compact", replace(models.MODELS["compact"], max_expanded_bytes=8))
    serve(monkeypatch, archive_for())
    with pytest.raises(ValueError, match="archive exceeded"):
        models.download_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_incomplete_download_is_refused(tmp_path, monkeypatch):
    content = archive_for()
    serve(monkeypatch, content, length=len(content) + 1)
    with pytest.raises(ValueError, match="incomplete"):
        models.download_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_cancelled_download_preserves_existing_model(tmp_path, monkeypatch):
    old = create_model(tmp_path, "accurate")
    cancelled = []
    serve(monkeypatch, archive_for("accurate"), on_read=lambda: cancelled.append(True))
    with pytest.raises(models.ModelDownloadCancelled):
        models.download_model(tmp_path / "models", model_key="accurate", cancelled=lambda: bool(cancelled))
    assert (old / "am/final.mdl").read_bytes() == b"test-model"
    assert not list((tmp_path / "models").glob(".download-*"))
    assert not list((tmp_path / "models").glob("*-recovery-*"))


def test_installer_captures_selection_before_background_start(tmp_path, monkeypatch):
    store = fake_store(tmp_path, "accurate")
    installer = models.ModelInstaller(store)
    store.settings["recognition_model"] = "compact"
    calls, ready = [], []

    def install(directory, progress, model_key, cancelled):
        calls.append((directory, model_key, cancelled()))

    monkeypatch.setattr(models, "download_model", install)
    installer.ready.connect(lambda: ready.append(True))
    installer.run()
    assert installer.model_key == "accurate"
    assert calls == [(tmp_path / "models", "accurate", False)]
    assert ready == [True]


def test_cancelled_installer_does_not_emit_ready_or_failed(tmp_path, monkeypatch):
    installer = models.ModelInstaller(fake_store(tmp_path))
    ready, failed = [], []
    installer.ready.connect(lambda: ready.append(True))
    installer.failed.connect(failed.append)
    installer.cancel()
    installer.run()
    assert not ready
    assert not failed
    assert not (tmp_path / "models").exists()


def test_replacement_preserves_old_model_in_recovery_directory(tmp_path, monkeypatch):
    old = create_model(tmp_path, "compact")
    (old / "am/final.mdl").write_bytes(b"older-model")
    serve(monkeypatch, archive_for())
    installed = models.download_model(tmp_path / "models")
    assert (installed / "am/final.mdl").read_bytes() == b"test-model"
    recovery = list((tmp_path / "models").glob(models.NAME + "-recovery-*"))
    assert len(recovery) == 1
    assert (recovery[0] / "am/final.mdl").read_bytes() == b"older-model"


def test_failed_final_install_restores_the_existing_model(tmp_path, monkeypatch):
    old = create_model(tmp_path, "compact")
    (old / "am/final.mdl").write_bytes(b"older-model")
    serve(monkeypatch, archive_for())
    original_rename = Path.rename

    def fail_new_model_rename(self, target):
        if self.name == models.NAME and self.parent.name.startswith(".download-"):
            raise OSError("Simulated unavailable destination")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_new_model_rename)
    with pytest.raises(OSError, match="unavailable destination"):
        models.download_model(tmp_path / "models")
    assert (old / "am/final.mdl").read_bytes() == b"older-model"
    assert not list((tmp_path / "models").glob(".download-*"))
    assert not list((tmp_path / "models").glob("*-recovery-*"))


def test_missing_required_model_files_are_never_installed(tmp_path, monkeypatch):
    serve(monkeypatch, archive_for(members={models.NAME + "/am/final.mdl": b"model-only"}))
    with pytest.raises(ValueError, match="missing required files"):
        models.download_model(tmp_path)
    assert not list(tmp_path.iterdir())
