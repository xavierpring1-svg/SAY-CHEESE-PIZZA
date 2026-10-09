import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import jarvis.transcription as transcription


def store_with_model(tmp_path, monkeypatch):
    monkeypatch.setattr(transcription, "ROOT", tmp_path / "empty-checkout")
    store = SimpleNamespace(directory=tmp_path)
    model = tmp_path / "models" / transcription.MODEL_NAME
    model.mkdir(parents=True)
    for name in transcription.REQUIRED_FILES:
        (model / name).write_bytes(b"test-model")
    return store, model


def test_native_adapter_decodes_16khz_and_caches_recognizer(tmp_path, monkeypatch):
    store, model = store_with_model(tmp_path, monkeypatch)
    factories, accepted, decoded = [], [], []
    text = 'Play "Hello" by Adele'

    class Stream:
        result = SimpleNamespace(text=text)

        def accept_waveform(self, sample_rate, samples):
            accepted.append((sample_rate, samples.dtype, len(samples)))

    class Recognizer:
        def create_stream(self):
            return Stream()

        def decode_stream(self, stream):
            decoded.append(stream)

    def factory(**kwargs):
        factories.append(kwargs)
        return Recognizer()

    engine = transcription.WhisperTranscriber(store, recognizer_factory=factory)
    assert engine.ready()
    assert engine.transcribe(np.full(16000, 0.02)) == text
    assert engine.transcribe(np.full(16000, 0.02)) == text
    assert len(factories) == 1
    assert factories[0]["encoder"] == str(model / transcription.ENCODER)
    assert factories[0]["decoder"] == str(model / transcription.DECODER)
    assert factories[0]["tokens"] == str(model / transcription.TOKENS)
    assert factories[0]["language"] == "en"
    assert factories[0]["task"] == "transcribe"
    assert factories[0]["provider"] == "cpu"
    assert 1 <= factories[0]["num_threads"] <= 4
    assert accepted == [(16000, np.dtype("float32"), 16000)] * 2
    assert len(decoded) == 2


def test_missing_or_incomplete_model_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(transcription, "ROOT", tmp_path / "empty-checkout")
    engine = transcription.WhisperTranscriber(SimpleNamespace(directory=tmp_path))
    assert not engine.ready()
    with pytest.raises(RuntimeError, match="offline Whisper model"):
        engine.transcribe(np.full(16000, 0.02))
    store, model = store_with_model(tmp_path, monkeypatch)
    (model / transcription.TOKENS).write_bytes(b"")
    assert not transcription.WhisperTranscriber(store).ready()


def test_silence_and_too_short_audio_never_load_or_decode_models(tmp_path):
    def factory(**kwargs):
        raise AssertionError("Silence cannot trigger inference")

    engine = transcription.WhisperTranscriber(SimpleNamespace(directory=tmp_path), recognizer_factory=factory)
    assert engine.transcribe(np.zeros(16000)) == ""
    assert engine.transcribe(np.full(1500, 0.1)) == ""
    assert engine.transcribe([]) == ""


@pytest.mark.parametrize("samples", [
    np.zeros((1000, 2)), np.full(16000, np.nan), np.full(16000, np.inf),
    np.full(16000, 3), np.zeros(30 * 16000 + 1),
])
def test_invalid_or_oversized_audio_is_refused(samples, tmp_path):
    engine = transcription.WhisperTranscriber(SimpleNamespace(directory=tmp_path))
    with pytest.raises(ValueError):
        engine.transcribe(samples)


def make_archive(members=None):
    output = io.BytesIO()
    if members is None:
        members = {transcription.MODEL_NAME + "/" + name: b"model" for name in transcription.REQUIRED_FILES}
        members[transcription.MODEL_NAME + "/tiny.en-decoder.onnx"] = b"unused-full-precision"
    with tarfile.open(fileobj=output, mode="w:bz2") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            if isinstance(data, tarfile.TarInfo):
                archive.addfile(data)
                continue
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


def serve(monkeypatch, content, *, published=None, url=None, length=None, on_read=None):
    monkeypatch.setattr(transcription, "_published_sha256", lambda: published)

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(content) if length is None else length)}

        def geturl(self):
            return url or transcription.URL

        def read(self, size=-1):
            if on_read:
                on_read()
            return super().read(size)

    monkeypatch.setattr(transcription.urllib.request, "urlopen", lambda *args, **kwargs: Response(content))


def test_installer_keeps_only_int8_runtime_models_and_records_observed_digest(tmp_path, monkeypatch):
    content = make_archive()
    serve(monkeypatch, content)
    progress = []
    installed = transcription.download_transcription_model(tmp_path, progress.append)
    assert installed.name == transcription.MODEL_NAME
    assert {path.name for path in installed.iterdir()} == set(transcription.REQUIRED_FILES) | {"download.json"}
    metadata = json.loads((installed / "download.json").read_text())
    assert metadata["sha256"] == hashlib.sha256(content).hexdigest()
    assert metadata["published_sha256"] is None
    assert metadata["checksum_source"] == "locally_observed_download"
    assert progress[-1] == 100
    assert not list(tmp_path.glob(".whisper-download-*"))


def test_published_github_digest_is_verified_and_recorded(tmp_path, monkeypatch):
    content = make_archive()
    expected = hashlib.sha256(content).hexdigest()
    serve(monkeypatch, content, published=expected)
    installed = transcription.download_transcription_model(tmp_path)
    metadata = json.loads((installed / "download.json").read_text())
    assert metadata["published_sha256"] == expected
    assert metadata["checksum_source"] == "github_asset_digest"


def test_published_digest_mismatch_never_installs_artifacts(tmp_path, monkeypatch):
    serve(monkeypatch, make_archive(), published="0" * 64)
    with pytest.raises(ValueError, match="published SHA-256"):
        transcription.download_transcription_model(tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", [
    "../../escape", "/absolute/path", "C:/outside/file",
    transcription.MODEL_NAME + "/../../escape",
    transcription.MODEL_NAME + "\\..\\..\\escape",
    transcription.MODEL_NAME + "/tokens.txt:stream",
    transcription.MODEL_NAME + "/NUL.txt",
])
def test_unsafe_archive_paths_are_rejected_before_install(tmp_path, monkeypatch, name):
    serve(monkeypatch, make_archive({name: b"unsafe"}))
    with pytest.raises(ValueError, match="Unsafe"):
        transcription.download_transcription_model(tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_archive_links_and_special_files_are_rejected(tmp_path, monkeypatch, kind):
    name = transcription.MODEL_NAME + "/" + transcription.ENCODER
    link = tarfile.TarInfo(name)
    link.type = kind
    link.linkname = "../../outside"
    serve(monkeypatch, make_archive({name: link}))
    with pytest.raises(ValueError, match="Unsafe"):
        transcription.download_transcription_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_http_download_redirect_is_refused(tmp_path, monkeypatch):
    serve(monkeypatch, make_archive(), url="http://github.com/insecure")
    with pytest.raises(ValueError, match="verified HTTPS"):
        transcription.download_transcription_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_bzip2_crc_corruption_is_rejected(tmp_path, monkeypatch):
    content = bytearray(make_archive())
    content[-8] ^= 1
    serve(monkeypatch, bytes(content))
    with pytest.raises((OSError, EOFError, tarfile.ReadError)):
        transcription.download_transcription_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_download_and_expanded_sizes_are_bounded(tmp_path, monkeypatch):
    serve(monkeypatch, make_archive(), length=transcription.MAX_DOWNLOAD_BYTES + 1)
    with pytest.raises(ValueError, match="expected size"):
        transcription.download_transcription_model(tmp_path)
    monkeypatch.setattr(transcription, "MAX_MEMBER_BYTES", 2)
    serve(monkeypatch, make_archive())
    with pytest.raises(ValueError, match="Unsafe"):
        transcription.download_transcription_model(tmp_path)
    assert not list(tmp_path.iterdir())


def test_cancelled_download_preserves_existing_files_and_cleans_temporary_data(tmp_path, monkeypatch):
    store, installed = store_with_model(tmp_path, monkeypatch)
    cancellation = []
    serve(monkeypatch, make_archive(), on_read=lambda: cancellation.append(True))
    with pytest.raises(transcription.TranscriptionDownloadCancelled):
        transcription.download_transcription_model(tmp_path / "models", cancelled=lambda: bool(cancellation))
    assert (installed / transcription.ENCODER).read_bytes() == b"test-model"
    assert not list((tmp_path / "models").glob(".whisper-download-*"))


def test_cancelled_worker_emits_no_completion_or_failure(tmp_path):
    worker = transcription.TranscriptionInstaller(SimpleNamespace(directory=tmp_path))
    ready, failed = [], []
    worker.ready.connect(lambda: ready.append(True))
    worker.failed.connect(failed.append)
    worker.cancel()
    worker.run()
    assert not ready and not failed
    assert not (tmp_path / "models").exists()


@pytest.mark.parametrize("digest", [None, "sha256:" + "a" * 64])
def test_official_metadata_accepts_only_matching_asset_and_optional_digest(monkeypatch, digest):
    metadata = {"name": transcription.ASSET_NAME, "browser_download_url": transcription.URL, "digest": digest}

    class Response(io.BytesIO):
        def geturl(self):
            return transcription.ASSET_METADATA_URL

    monkeypatch.setattr(transcription.urllib.request, "urlopen", lambda *args, **kwargs: Response(json.dumps(metadata).encode()))
    assert transcription._published_sha256() == ("a" * 64 if digest else None)


def test_official_metadata_cannot_substitute_another_asset(monkeypatch):
    metadata = {"name": "different.tar.bz2", "browser_download_url": transcription.URL, "digest": None}

    class Response(io.BytesIO):
        def geturl(self):
            return transcription.ASSET_METADATA_URL

    monkeypatch.setattr(transcription.urllib.request, "urlopen", lambda *args, **kwargs: Response(json.dumps(metadata).encode()))
    with pytest.raises(ValueError, match="expected official asset"):
        transcription._published_sha256()
