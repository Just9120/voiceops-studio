"""Download only the files and revisions that ship as Studio profiles."""
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .native import DECODER_SHA256, ENCODER_SHA256
from .protocol import MODEL, MODEL_REVISIONS, PARAKEET_BYTES, PARAKEET_MODEL, PARAKEET_SHA256, WorkerError, file_sha256


@dataclass(frozen=True)
class ModelFile:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelProfile:
    name: str
    repo: str
    revision: str
    files: tuple[ModelFile, ...]


PROFILES = {
    "nemotron-transcribe-iq4-nl": ModelProfile(
        "Nemotron 3.5 Transcribe IQ4_NL", "AtomicChat/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-GGUF",
        MODEL_REVISIONS[MODEL], (
            ModelFile("NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-AD-IQ4_NL.gguf", 19678656672, DECODER_SHA256),
            ModelFile("NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-Encoder-F16.gguf", 1670410080, ENCODER_SHA256),
        ),
    ),
    "parakeet-tdt-v3-q8": ModelProfile(
        "Parakeet TDT 0.6B v3 Q8", "nvidia/parakeet-tdt-0.6b-v3",
        MODEL_REVISIONS[PARAKEET_MODEL], (
            ModelFile("parakeet-tdt-0.6b-v3.q8_0.gguf", PARAKEET_BYTES, PARAKEET_SHA256),
        ),
    ),
}


def _trusted_download(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    return (parsed.scheme == "https" and parsed.username is None and parsed.password is None
            and parsed.port in {None, 443} and (
                host == "huggingface.co" or host.endswith((".hf.co", ".huggingface.co"))))


class _ModelRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _trusted_download(newurl):
            raise WorkerError("local_model_download_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _size_if_regular(path):
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise WorkerError("local_model_file_invalid")
    if not path.exists():
        return 0
    if not path.is_file():
        raise WorkerError("local_model_file_invalid")
    return path.stat().st_size


def _download(opener, url, temporary, expected, offset, *, check, progress):
    if offset == expected:
        return
    headers = {"Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    try:
        with opener.open(Request(url, headers=headers), timeout=30) as response:
            total = expected - offset
            content_range = response.headers.get("Content-Range", "")
            if (not _trusted_download(response.geturl()) or response.headers.get("Content-Encoding", "identity") != "identity"
                    or (offset and (response.status != 206 or content_range != f"bytes {offset}-{expected - 1}/{expected}"))
                    or (not offset and response.status != 200)
                    or response.headers.get("Content-Length") != str(total)):
                raise WorkerError("local_model_download_range_invalid")
            with temporary.open("ab") as stream:
                if stream.tell() != offset:
                    raise WorkerError("local_model_file_invalid")
                while offset < expected:
                    check()
                    block = response.read(min(1024 * 1024, expected - offset))
                    if not block:
                        raise WorkerError("local_model_download_interrupted")
                    stream.write(block)
                    offset += len(block)
                    progress(offset)
    except (OSError, URLError) as exc:
        raise WorkerError("local_model_download_interrupted") from exc


def install_profile(profile_id, root, *, check, progress):
    profile = PROFILES[profile_id]
    directory = Path(root) / "VoiceOpsModels" / profile_id / profile.revision
    for path in (directory.parent.parent, directory.parent, directory):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise WorkerError("local_model_file_invalid")
        path.mkdir(exist_ok=True)
    files = []
    for spec in profile.files:
        final = directory / spec.name
        partial = final.with_suffix(".gguf.part")
        present = _size_if_regular(final)
        offset = _size_if_regular(partial)
        if (final.exists() and present != spec.size) or offset > spec.size:
            raise WorkerError("local_model_file_invalid")
        files.append((spec, final, partial, offset))

    remaining = sum(spec.size - offset for spec, final, _, offset in files if not final.exists())
    if remaining and shutil.disk_usage(directory).free < remaining + 16 * 1024 * 1024:
        raise WorkerError("local_model_disk_space")
    total = sum(spec.size for spec, *_ in files)
    opener = build_opener(_ModelRedirect())
    completed = 0
    for spec, final, partial, offset in files:
        check()
        if not final.exists():
            _download(opener, f"https://huggingface.co/{profile.repo}/resolve/{profile.revision}/{spec.name}",
                      partial, spec.size, offset, check=check, progress=lambda current: progress(completed + current, total))
            if file_sha256(partial, check) != spec.sha256:
                # Retain at most one rejected download. Every bad partial must
                # leave the resumable slot free for the next attempt.
                rejected = partial.with_suffix(".invalid")
                if rejected.exists() or rejected.is_symlink():
                    partial.unlink()
                else:
                    partial.rename(rejected)
                raise WorkerError("local_model_file_invalid")
            partial.rename(final)
        elif file_sha256(final, check) != spec.sha256:
            raise WorkerError("local_model_file_invalid")
        completed += spec.size
        progress(completed, total)
    return directory


def remove_managed_profile(profile_id, root, selected_decoder, *, check):
    profile = PROFILES[profile_id]
    directory = Path(root).resolve(strict=True) / "VoiceOpsModels" / profile_id / profile.revision
    if directory.resolve(strict=True) != directory or directory != Path(selected_decoder).parent:
        raise WorkerError("local_model_file_invalid")
    files = [directory / spec.name for spec in profile.files]
    for spec, target in zip(profile.files, files, strict=True):
        if _size_if_regular(target) != spec.size or file_sha256(target, check) != spec.sha256:
            raise WorkerError("local_model_file_invalid")
    check()
    for target in files:
        target.unlink()
