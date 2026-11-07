"""Reviewed model snapshots shared by downloads, local verification and execution."""
from dataclasses import dataclass

MODEL = "NVIDIA-Nemotron-3.5-Transcribe-30B-A4B"
PARAKEET_MODEL = "parakeet-tdt-0.6b-v3.q8_0"
INITIAL_MODEL_REVISIONS = {
    MODEL: "dbd06c5cad7a2f33c8e06be2fb3ef814dbd9aa59",
    PARAKEET_MODEL: "541d1f99c6b0c3cd0b11a95167540bb8edefd82b",
}


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
    model: str = MODEL


PROFILES = {
    "nemotron-transcribe-iq4-nl": ModelProfile(
        "Nemotron 3.5 Transcribe IQ4_NL", "AtomicChat/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-GGUF",
        INITIAL_MODEL_REVISIONS[MODEL], (
            ModelFile("NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-AD-IQ4_NL.gguf", 19678656672,
                      "0c47d4ab6c783e7606ec03714b354fab0b2052027a7ea1991e7e2d3009c345ad"),
            ModelFile("NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-Encoder-F16.gguf", 1670410080,
                      "4221029c8a565c4a80c507ffa760c716e595acf663f9f4273ce69910050e7ba2"),
        ),
    ),
    "parakeet-tdt-v3-q8": ModelProfile(
        "Parakeet TDT 0.6B v3 Q8", "nvidia/parakeet-tdt-0.6b-v3",
        INITIAL_MODEL_REVISIONS[PARAKEET_MODEL], (
            ModelFile("parakeet-tdt-0.6b-v3.q8_0.gguf", 713975456,
                      "e3880d0aaaaf2c308ea2c35016b2b895c423eb3fda924c1b463d1c19b7f4d32e"),
        ), PARAKEET_MODEL,
    ),
}

# When promoting a default, keep the previously reviewed profile here while
# its installed copies and pinned jobs are still supported.
RETAINED_PROFILES: dict[tuple[str, str], ModelProfile] = {}


def model_profile(model, revision):
    return next((profile for profile in (*PROFILES.values(), *RETAINED_PROFILES.values())
                 if profile.model == model and profile.revision == revision), None)
