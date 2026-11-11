from __future__ import annotations

import json
import socket
from collections.abc import Mapping
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class JobNotificationTransport(Protocol):
    def __call__(self, payload: Mapping[str, str], *, settings) -> tuple[bool, str | None]:
        ...


def send_telegram_job_notification(
    payload: Mapping[str, str],
    *,
    settings,
    post: Callable | None = None,
) -> tuple[bool, str | None]:
    try:
        token, chat_id = settings.job_telegram_credentials()
    except Exception:
        return False, "configuration_unavailable"
    text = f"VoiceOps Studio\n{payload['title']}\n{payload['body']}"
    # Owner-approved public entrypoint only; never include job/file identifiers.
    if getattr(settings, "app_origin", "").rstrip("/") == "https://studio.cloud-nodes.net":
        text += "\nhttps://studio.cloud-nodes.net/transcriptions"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = {"chat_id": chat_id, "text": text}
    timeout = float(settings.job_telegram_timeout_seconds)
    if post is not None:
        try:
            response = post(url, json=body, timeout=timeout)
        except (TimeoutError, socket.timeout):
            return False, "transport_timeout"
        except OSError:
            return False, "transport_unavailable"
        try:
            ack = response.json()
        except (AttributeError, ValueError, TypeError):
            return False, "transport_rejected"
        return (True, None) if 200 <= int(response.status_code) < 300 and _telegram_acknowledged(ack) else (False, "transport_rejected")
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS origin
            status_code = int(response.status)
            ack = json.loads(response.read(65537))
    except HTTPError:
        return False, "transport_rejected"
    except (TimeoutError, socket.timeout):
        return False, "transport_timeout"
    except URLError as exc:
        return (False, "transport_timeout") if isinstance(exc.reason, (TimeoutError, socket.timeout)) else (False, "transport_unavailable")
    except OSError:
        return False, "transport_unavailable"
    except (ValueError, UnicodeError):
        return False, "transport_rejected"
    return (True, None) if 200 <= status_code < 300 and _telegram_acknowledged(ack) else (False, "transport_rejected")


def _telegram_acknowledged(ack) -> bool:
    result = ack.get("result") if isinstance(ack, dict) and ack.get("ok") is True else None
    message_id = result.get("message_id") if isinstance(result, dict) else None
    return type(message_id) is int and message_id > 0
