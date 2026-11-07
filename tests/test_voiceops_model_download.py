"""Only validated pinned bytes can become an installed profile."""
import hashlib
import io
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from local_worker import model_download as models
from local_worker.model_profiles import ModelFile, ModelProfile
from local_worker.protocol import WorkerError


def test_remove_retained_profile_is_retryable_and_does_not_touch_promoted_version(tmp_path, monkeypatch):
    profile_id = "synthetic"
    original, promoted = "a" * 40, "b" * 40
    specs = tuple(ModelFile(name, 4, hashlib.sha256(b"test").hexdigest()) for name in ("decoder.gguf", "encoder.gguf"))
    monkeypatch.setitem(models.PROFILES, profile_id, ModelProfile("New", "nvidia/test", promoted, specs))
    monkeypatch.setitem(models.RETAINED_PROFILES, (profile_id, original), ModelProfile("Old", "nvidia/test", original, specs))
    directory = tmp_path / "VoiceOpsModels" / profile_id
    old_files, new_files = directory / original, directory / promoted
    old_files.mkdir(parents=True)
    new_files.mkdir()
    # Retry after the decoder was already removed and the encoder remained.
    (old_files / "encoder.gguf").write_bytes(b"test")
    for spec in specs:
        (new_files / spec.name).write_bytes(b"test")
    models.remove_managed_profile(profile_id, tmp_path, old_files / "decoder.gguf", check=lambda: None, revision=original)
    assert list(old_files.iterdir()) == []
    assert all((new_files / spec.name).read_bytes() == b"test" for spec in specs)


def test_resumed_profile_requires_correct_range_and_digest(tmp_path, monkeypatch):
    content = b"correct-model-fixture"
    profile_id = "synthetic"
    spec = ModelFile("test.gguf", len(content), hashlib.sha256(content).hexdigest())
    monkeypatch.setitem(models.PROFILES, profile_id, ModelProfile(
        "Synthetic", "nvidia/test", "a" * 40, (spec,)))
    directory = tmp_path / "VoiceOpsModels" / profile_id / ("a" * 40)
    directory.mkdir(parents=True)
    partial = directory / "test.gguf.part"
    partial.write_bytes(content[:5])

    class Reply(io.BytesIO):
        status = 206
        headers = {"Content-Range": f"bytes 5-{len(content)-1}/{len(content)}", "Content-Length": str(len(content)-5)}

        def geturl(self):
            return "https://cas-bridge.xethub.hf.co/synthetic"

    class Opener:
        def open(self, request, *, timeout):
            assert request.get_header("Range") == "bytes=5-"
            assert "a" * 40 in request.full_url
            return Reply(content[5:])

    monkeypatch.setattr(models, "build_opener", lambda _redirect: Opener())
    progress = []
    result = models.install_profile(profile_id, tmp_path, check=lambda: None, progress=lambda *args: progress.append(args))
    assert result == directory and (result / spec.name).read_bytes() == content
    assert progress[-1] == (len(content), len(content)) and not partial.exists()

    (result / spec.name).write_bytes(b"X" * len(content))
    with pytest.raises(WorkerError, match="local_model_file_invalid"):
        models.install_profile(profile_id, tmp_path, check=lambda: None, progress=lambda *_: None)


def test_repeated_corrupt_downloads_leave_a_fresh_retry(tmp_path, monkeypatch):
    content = b"model-good"
    first_corrupt = b"model-bad1"
    second_corrupt = b"model-bad2"
    spec = ModelFile("test.gguf", len(content), hashlib.sha256(content).hexdigest())
    revision = "a" * 40
    monkeypatch.setitem(models.PROFILES, "synthetic", ModelProfile(
        "Synthetic", "nvidia/test", revision, (spec,)))
    directory = tmp_path / "VoiceOpsModels" / "synthetic" / revision
    replies = iter((first_corrupt, second_corrupt, content))
    calls = []

    class Reply(io.BytesIO):
        status = 200
        headers = {"Content-Length": str(len(content))}

        def geturl(self):
            return "https://cas-bridge.xethub.hf.co/synthetic"

    class Opener:
        def open(self, request, *, timeout):
            calls.append(request.get_header("Range"))
            return Reply(next(replies))

    monkeypatch.setattr(models, "build_opener", lambda _redirect: Opener())
    partial = directory / "test.gguf.part"
    rejected = directory / "test.gguf.invalid"
    for _ in range(2):
        with pytest.raises(WorkerError, match="local_model_file_invalid"):
            models.install_profile("synthetic", tmp_path, check=lambda: None, progress=lambda *_: None)
        assert not partial.exists()
        assert rejected.read_bytes() == first_corrupt

    assert models.install_profile("synthetic", tmp_path, check=lambda: None, progress=lambda *_: None) == directory
    assert (directory / spec.name).read_bytes() == content
    assert rejected.read_bytes() == first_corrupt
    assert calls == [None, None, None]


@pytest.mark.parametrize("url", ["http://huggingface.co/test", "https://evil.example/test",
                                 "https://huggingface.co@evil.example/test", "https://huggingface.co:444/test"])
def test_model_download_rejects_untrusted_redirects(url):
    assert not models._trusted_download(url)
