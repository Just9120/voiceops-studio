"""Model identities admitted by the personal local execution protocol."""
import json

from .nemotron_local_result import NEMOTRON_MODEL
from .transcription_metadata import stored_model

PARAKEET_MODEL = "parakeet-tdt-0.6b-v3.q8_0"
LEGACY_NEMOTRON_REVISION = "dbd06c5cad7a2f33c8e06be2fb3ef814dbd9aa59"
INITIAL_MODEL_REVISIONS = {
    NEMOTRON_MODEL: LEGACY_NEMOTRON_REVISION,
    PARAKEET_MODEL: "541d1f99c6b0c3cd0b11a95167540bb8edefd82b",
}
# A catalog promotion can change the default without retiring a revision
# referenced by existing jobs or an installed companion.
MODEL_REVISIONS = INITIAL_MODEL_REVISIONS.copy()
SUPPORTED_MODEL_REVISIONS = {
    model: frozenset((revision,)) for model, revision in INITIAL_MODEL_REVISIONS.items()
}
# NVIDIA documents this upper bound for full attention. Resource availability
# on the actual CPU is still checked separately.
PARAKEET_MAX_DURATION_SECONDS = 24 * 60


def is_supported_model_revision(model, revision):
    return (isinstance(model, str) and isinstance(revision, str)
            and revision in SUPPORTED_MODEL_REVISIONS.get(model, ()))


def job_model_identity(options_json):
    try:
        options = json.loads(options_json or "{}")
        model, revision = stored_model(options_json), options.get("_local_model_revision")
    except (TypeError, ValueError, AttributeError):
        return None, None
    if revision is None and model == NEMOTRON_MODEL:
        revision = LEGACY_NEMOTRON_REVISION
    if is_supported_model_revision(model, revision):
        return model, revision
    return None, None
