"""Model identities admitted by the personal local execution protocol."""
import json

from .nemotron_local_result import NEMOTRON_MODEL
from .transcription_metadata import stored_model

PARAKEET_MODEL = "parakeet-tdt-0.6b-v3.q8_0"
MODEL_REVISIONS = {
    NEMOTRON_MODEL: "dbd06c5cad7a2f33c8e06be2fb3ef814dbd9aa59",
    PARAKEET_MODEL: "541d1f99c6b0c3cd0b11a95167540bb8edefd82b",
}
# NVIDIA documents this upper bound for full attention. Resource availability
# on the actual CPU is still checked separately.
PARAKEET_MAX_DURATION_SECONDS = 24 * 60


def job_model_identity(options_json):
    try:
        options = json.loads(options_json or "{}")
        model, revision = stored_model(options_json), options.get("_local_model_revision")
        expected = MODEL_REVISIONS.get(model)
    except (TypeError, ValueError, AttributeError):
        return None, None
    if expected and (revision == expected or (revision is None and model == NEMOTRON_MODEL)):
        return model, expected
    return None, None
