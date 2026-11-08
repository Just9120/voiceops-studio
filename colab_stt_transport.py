"""Batch STT HTTP transport using an interpreter with locked dependencies."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import NamedTemporaryFile

import requests


_POST_IN_CHILD = """
import json
import sys

payload = json.load(sys.stdin)
if payload["url"] not in (
    "https://api.elevenlabs.io/v1/speech-to-text",
    "https://api.openai.com/v1/audio/transcriptions",
):
    raise SystemExit(2)

import requests

try:
    with open(payload["path"], "rb") as audio:
        response = requests.post(
            payload["url"], headers=payload["headers"], data=payload["data"],
            files={"file": (payload["name"], audio, payload["mime_type"])},
            timeout=tuple(payload["timeout"]), allow_redirects=False,
        )
    if 300 <= response.status_code < 400:
        result = {"error": "redirect"}
    else:
        result = {"status": response.status_code, "text": response.text}
except requests.exceptions.SSLError:
    result = {"error": "tls"}
except (OSError, requests.exceptions.RequestException):
    result = {"error": "request"}
json.dump(result, sys.stdout)
"""


@contextmanager
def _audio_path(fileobj):
    name = getattr(fileobj, "name", None)
    if isinstance(name, (str, Path)):
        path = Path(name).resolve()
        if path.is_file():
            yield path
            return
    with NamedTemporaryFile(prefix="voiceops-colab-stt-", delete=False) as temp:
        path = Path(temp.name)
        try:
            shutil.copyfileobj(fileobj, temp)
        except BaseException:
            temp.close()
            path.unlink(missing_ok=True)
            raise
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def post_with_interpreter(interpreter, url, *, headers, files, data, timeout):
    name, audio, mime_type = files["file"]
    with _audio_path(audio) as path:
        payload = {
            "url": url, "headers": headers, "data": data, "timeout": timeout,
            "path": str(path), "name": name, "mime_type": mime_type,
        }
        try:
            child = subprocess.run(
                [str(interpreter), "-I", "-X", "utf8", "-c", _POST_IN_CHILD],
                input=json.dumps(payload), capture_output=True, encoding="utf-8",
                timeout=sum(timeout) + 30, check=True,
            )
            result = json.loads(child.stdout)
            if not isinstance(result, dict):
                raise ValueError("Invalid child response")
        except (OSError, subprocess.SubprocessError, ValueError):
            raise requests.exceptions.RequestException("Изолированный HTTP-клиент не завершил запрос") from None
    error = result.get("error")
    if error == "tls":
        raise requests.exceptions.SSLError("Изолированный HTTP-клиент сообщил об ошибке TLS")
    if error:
        raise requests.exceptions.RequestException("Изолированный HTTP-клиент отклонил запрос")
    status, body = result.get("status"), result.get("text")
    if type(status) is not int or not 100 <= status <= 599 or not isinstance(body, str):
        raise requests.exceptions.RequestException("Изолированный HTTP-клиент вернул некорректный ответ")
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.encoding = "utf-8"
    response._content = body.encode("utf-8")
    return response
