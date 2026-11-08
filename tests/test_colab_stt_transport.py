import io
import json
from pathlib import Path
import subprocess
import sys

import pytest
import requests

from colab_stt_transport import post_with_interpreter
import colab_stt_transport


def test_isolated_child_preserves_file_fields_and_http_error(monkeypatch, tmp_path):
    audio = tmp_path / "synthetic.wav"
    audio.write_bytes(b"synthetic PCM")
    fake = """
from types import SimpleNamespace
def mock_post(url, *, headers, data, files, timeout, allow_redirects):
    assert headers == {"xi-api-key": "synthetic-key"}
    assert "synthetic-key" not in sys.argv
    assert data == [["keyterms", "первый"], ["keyterms", "второй"]]
    name, audio, mime = files["file"]
    assert name == "тест.wav" and mime == "audio/wav"
    assert audio.read() == b"synthetic PCM"
    assert timeout == (1, 2) and allow_redirects is False
    return type("Response", (), {"status_code": 422, "text": '{"message":"проверка"}'})()
requests = SimpleNamespace(post=mock_post)
"""
    monkeypatch.setattr(colab_stt_transport, "_POST_IN_CHILD",
                        colab_stt_transport._POST_IN_CHILD.replace("import requests", fake, 1))
    with audio.open("rb") as handle:
        response = post_with_interpreter(
            sys.executable, "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": "synthetic-key"},
            files={"file": ("тест.wav", handle, "audio/wav")},
            data=[("keyterms", "первый"), ("keyterms", "второй")], timeout=(1, 2),
        )
    assert response.status_code == 422
    assert response.json() == {"message": "проверка"}
    with pytest.raises(requests.HTTPError):
        response.raise_for_status()


def test_child_rejects_unapproved_destination_before_network():
    with pytest.raises(requests.RequestException, match="не завершил запрос"):
        post_with_interpreter(
            sys.executable, "https://example.test/forbidden", headers={},
            files={"file": ("test.wav", io.BytesIO(b"synthetic"), "audio/wav")},
            data=[], timeout=(1, 2),
        )


def test_temporary_input_is_cleaned_after_child_failure(monkeypatch):
    observed = []

    def fail(_command, *, input, **_kwargs):
        path = Path(json.loads(input)["path"])
        assert path.read_bytes() == b"synthetic"
        observed.append(path)
        raise subprocess.TimeoutExpired("child", 1)

    monkeypatch.setattr(colab_stt_transport.subprocess, "run", fail)
    with pytest.raises(requests.RequestException, match="не завершил запрос"):
        post_with_interpreter(
            sys.executable, "https://api.openai.com/v1/audio/transcriptions", headers={},
            files={"file": ("test.wav", io.BytesIO(b"synthetic"), "audio/wav")},
            data=[], timeout=(1, 2),
        )
    assert len(observed) == 1 and not observed[0].exists()
