"""VoiceOps Studio experimental LIVE-COLAB-01 realtime Colab runtime.

This file is intentionally standalone and does not import the batch Colab
runtime. It creates an ElevenLabs realtime Scribe single-use token Python-side,
then renders a lightweight browser UI that sends captured PCM audio chunks over
an ElevenLabs realtime WebSocket.

Prototype boundaries:
- no Google Docs/Drive writes;
- no manifest reads/writes;
- no speaker project integration;
- no transcript/audio/secrets persistence;
- browser receives only a short-lived realtime token, never the main API key.
"""

from __future__ import annotations

import html
import importlib.util
import json
import os
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse, urlencode, urldefrag
from urllib.request import Request, urlopen


REALTIME_TOKEN_URL = "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe"
REALTIME_WS_ENDPOINT = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
REALTIME_MODEL_ID = "scribe_v2_realtime"
REALTIME_AUDIO_FORMAT = "pcm_16000"
REALTIME_COMMIT_STRATEGY = "vad"
ELEVENLABS_API_KEY_NAMES = ("ELEVEN_API_KEY", "ELEVENLABS_API_KEY")
ELEVENLABS_API_KEY_NOT_FOUND_MESSAGE = (
    "ElevenLabs API key not found. Add ELEVEN_API_KEY to Colab Secrets, "
    "or use ELEVENLABS_API_KEY as a compatibility alias."
)

_REALTIME_PROXY_SERVERS: list[ThreadingHTTPServer] = []


KNOWN_ERROR_MESSAGES_RU = {
    "auth": "Ошибка авторизации ElevenLabs realtime. Проверьте основной ключ API и срок действия одноразового токена realtime.",
    "authentication": "Ошибка авторизации ElevenLabs realtime. Проверьте основной ключ API и срок действия одноразового токена realtime.",
    "unauthorized": "Ошибка авторизации ElevenLabs realtime. Проверьте основной ключ API и срок действия одноразового токена realtime.",
    "quota": "Квота ElevenLabs исчерпана или недоступна для realtime-распознавания.",
    "quota_exceeded": "Квота ElevenLabs исчерпана или недоступна для realtime-распознавания.",
    "rate_limit": "Превышен лимит запросов ElevenLabs realtime. Подождите и попробуйте снова.",
    "rate_limited": "Превышен лимит запросов ElevenLabs realtime. Подождите и попробуйте снова.",
    "queue_overflow": "Очередь realtime-аудио переполнена. Остановите запись и попробуйте снова с меньшей нагрузкой.",
    "session_time_limit": "Достигнут лимит длительности realtime-сессии. Остановите запись и начните новую сессию.",
    "session_time_limit_exceeded": "Достигнут лимит длительности realtime-сессии. Остановите запись и начните новую сессию.",
    "chunk_size": "Некорректный размер аудиофрагмента. Остановите запись и попробуйте снова.",
    "input_audio_chunk": "Ошибка входного аудиофрагмента. Остановите запись и попробуйте снова.",
    "invalid_audio": "Некорректный аудиовход. Проверьте источник звука и попробуйте снова.",
}


class _JsonResponse:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, Any]:
        return json.loads(self._body.decode("utf-8"))


def _urllib_post_json(url: str, *, headers: dict[str, str], timeout: int) -> _JsonResponse:
    request = Request(url, data=b"", headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return _JsonResponse(getattr(response, "status", 200), response.read())


class RealtimeTokenError(RuntimeError):
    """Raised when a realtime single-use token cannot be obtained safely."""


def _get_colab_userdata() -> Any | None:
    """Return Colab userdata when available, otherwise None."""

    if (
        importlib.util.find_spec("google") is None
        or importlib.util.find_spec("google.colab") is None
    ):
        return None
    from google.colab import userdata

    return userdata


def get_elevenlabs_api_key() -> str:
    """Load the ElevenLabs API key from Colab Secrets/userdata or environment."""

    userdata = _get_colab_userdata()
    for name in ELEVENLABS_API_KEY_NAMES:
        if userdata is not None:
            try:
                key = (userdata.get(name) or "").strip()
            except Exception:
                key = ""
            if key:
                return key

        key = os.environ.get(name, "").strip()
        if key:
            return key

    raise RealtimeTokenError(ELEVENLABS_API_KEY_NOT_FOUND_MESSAGE)


def extract_realtime_token(payload: dict[str, Any]) -> str:
    """Validate ElevenLabs single-use-token response shape and return the token."""

    for field in ("token", "single_use_token", "singleUseToken"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise RealtimeTokenError(
        "ElevenLabs single-use token response did not contain a non-empty token field."
    )


def create_realtime_single_use_token(
    api_key: str,
    *,
    post: Callable[..., Any] | None = None,
    timeout: int = 20,
) -> str:
    """Create a single-use realtime Scribe token without exposing the main API key."""

    if not isinstance(api_key, str) or not api_key.strip():
        raise RealtimeTokenError("ElevenLabs API key is empty.")
    post_fn = post or _urllib_post_json
    response = post_fn(
        REALTIME_TOKEN_URL,
        headers={"xi-api-key": api_key.strip(), "Accept": "application/json"},
        timeout=timeout,
    )
    if getattr(response, "status_code", 0) >= 400:
        raise RealtimeTokenError(
            f"ElevenLabs single-use token request failed with HTTP {response.status_code}."
        )
    return extract_realtime_token(response.json())


def build_realtime_websocket_url(
    token: str,
    *,
    model_id: str = REALTIME_MODEL_ID,
    audio_format: str = REALTIME_AUDIO_FORMAT,
    commit_strategy: str = REALTIME_COMMIT_STRATEGY,
) -> str:
    """Build the ElevenLabs realtime WebSocket URL used by browser JavaScript."""

    if not isinstance(token, str) or not token.strip():
        raise ValueError("token is required")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("model_id is required")
    if not isinstance(commit_strategy, str) or not commit_strategy.strip():
        raise ValueError("commit_strategy is required")
    query = urlencode(
        {
            "model_id": model_id.strip(),
            "token": token.strip(),
            "audio_format": audio_format,
            "commit_strategy": commit_strategy.strip(),
        }
    )
    return f"{REALTIME_WS_ENDPOINT}?{query}"


def realtime_error_message_ru(code_or_event: Any) -> str:
    """Map known realtime error events/codes to concise Russian messages."""

    text = str(code_or_event or "").lower()
    for key, message in KNOWN_ERROR_MESSAGES_RU.items():
        if key in text:
            return message
    return "Ошибка WebSocket realtime-распознавания. Проверьте соединение, источник аудио и попробуйте снова."


def create_realtime_colab_root_id() -> str:
    """Return a unique DOM root id for one Colab realtime UI render."""

    return f"el-realtime-root-{uuid.uuid4().hex}"


def _validate_realtime_colab_root_id(root_id: str) -> str:
    """Validate a generated DOM root id before embedding it in HTML/JS."""

    if not isinstance(root_id, str) or not root_id.strip():
        raise ValueError("root_id is required")
    root_id = root_id.strip()
    if not root_id.startswith("el-realtime-root-"):
        raise ValueError("root_id must be an el-realtime-root-* id")
    if not all(char.isalnum() or char == "-" for char in root_id):
        raise ValueError("root_id contains unsupported characters")
    return root_id


def build_realtime_colab_html_shell(root_id: str) -> str:
    """Return the static DOM/CSS shell for the Colab output cell."""

    root_id = _validate_realtime_colab_root_id(root_id)

    return f"""
<div id="{root_id}" data-el-realtime-root style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.45;max-width:960px;border:1px solid #d8dee9;border-radius:14px;padding:18px;margin:8px 0;background:#fff;color:#17202a;box-shadow:0 1px 3px rgba(15,23,42,0.06);">
  <style>
    #{root_id} .el-title {{ margin:0 0 6px;color:#111827;font-size:22px;line-height:1.25;font-weight:700; }}
    #{root_id} .el-subtitle {{ margin:0;color:#4b5563;max-width:860px; }}
    #{root_id} .el-panel {{ border:1px solid #e5e7eb;border-radius:12px;padding:12px;margin:14px 0;background:#fafafa; }}
    #{root_id} .el-field {{ margin:0 0 12px; }}
    #{root_id} .el-label {{ display:block;margin:0 0 6px;color:#1f2937;font-weight:700; }}
    #{root_id} .el-hint {{ margin:6px 0 0;color:#4b5563;font-size:13px; }}
    #{root_id} .el-warning {{ margin:8px 0 0;padding:8px 10px;border:1px solid #f59e0b;border-radius:10px;background:#fffbeb;color:#92400e;font-weight:700; }}
    #{root_id} select {{ display:block;width:min(100%,420px);padding:7px 9px;border:1px solid #cbd5e1;border-radius:8px;background:#fff;color:#111827; }}
    #{root_id} .el-controls {{ display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:4px; }}
    #{root_id} button {{ padding:8px 14px;border:1px solid #cbd5e1;border-radius:8px;background:#f8fafc;color:#111827;cursor:pointer; }}
    #{root_id} button:disabled {{ color:#94a3b8;cursor:not-allowed;background:#f1f5f9; }}
    #{root_id} [data-el="status"] {{ padding:9px 11px;background:#eef6ff;border:1px solid #bfdbfe;border-radius:10px;margin:12px 0 8px;color:#1e3a8a;font-weight:700; }}
    #{root_id} [data-el="diagnostics-wrap"] {{ margin:8px 0 16px;border:1px solid #e5e7eb;border-radius:10px;background:#f9fafb; }}
    #{root_id} [data-el="diagnostics-wrap"] summary {{ padding:8px 10px;cursor:pointer;font-weight:700;color:#374151; }}
    #{root_id} .el-diagnostics-placeholder {{ padding:0 10px 10px;color:#6b7280;font-size:13px; }}
    #{root_id} [data-el="diagnostics"] {{ white-space:pre-wrap;background:#263238;color:#eef2f7;border-radius:8px;padding:9px 10px;margin:0 10px 10px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;line-height:1.45;max-height:160px;overflow:auto; }}
    #{root_id} .el-section-title {{ margin:14px 0 6px;color:#111827;font-size:16px; }}
    #{root_id} .el-session-header {{ border:1px solid #dbeafe;border-radius:12px 12px 0 0;padding:10px 12px;background:#eff6ff;color:#1e3a8a; }}
    #{root_id} .el-live-title {{ font-weight:800;color:#111827; }}
    #{root_id} .el-source-summary, #{root_id} .el-format-id {{ margin-top:3px;font-size:13px;color:#475569; }}
    #{root_id} [data-el="committed"] {{ min-height:180px;max-height:360px;overflow:auto;border:1px solid #cbd5e1;border-top:0;border-radius:0 0 12px 12px;padding:12px;background:#fbfbfb; }}
    #{root_id} .el-committed-empty {{ margin:0;color:#64748b;font-style:italic; }}
    #{root_id} .el-committed-segment {{ margin:0 0 10px;padding:10px 12px;border:1px solid #e2e8f0;border-radius:10px;background:#fff;font-size:17px;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word; }}
    #{root_id} .el-committed-segment:last-child {{ margin-bottom:0; }}
  </style>
  <h2 class="el-title">LIVE-COLAB-01: прототип realtime-распознавания</h2>
  <p class="el-subtitle">Экспериментальный Colab-прототип: без сохранения в Google Docs, без manifest, без проектов спикеров. Основной ключ API остаётся на стороне Python; браузер получает только одноразовый токен realtime.</p>
  <div class="el-panel" aria-label="Элементы управления realtime-распознаванием">
    <div class="el-field">
      <label class="el-label" for="{root_id}-display-audio">Аудио вкладки / экрана</label>
      <select id="{root_id}-display-audio" data-el="display-audio">
        <option value="off">Выключено</option>
        <option value="on">Вкладка браузера / экран со звуком</option>
      </select>
      <p class="el-hint">При выборе вкладки включите передачу звука. При захвате экрана браузер может не передать аудио.</p>
    </div>
    <div class="el-field">
      <label class="el-label" for="{root_id}-input-device">Микрофон / аудиовход</label>
      <select id="{root_id}-input-device" data-el="input-device">
        <option value="off">Выключено</option>
        <option value="">Устройство по умолчанию</option>
      </select>
      <p class="el-hint">Для звука приложений выберите здесь виртуальное или loopback-устройство, если оно доступно в системе.</p>
    </div>
    <div class="el-controls">
      <button data-el="refresh-devices" type="button">Обновить список устройств</button>
      <button data-el="start" disabled>Начать</button>
      <button data-el="stop" disabled>Остановить</button>
      <button data-el="copy" disabled>Скопировать текст</button>
      <button data-el="download" disabled>Скачать .txt</button>
      <button data-el="clear" disabled>Очистить подтверждённый текст</button>
    </div>
    <p class="el-hint" data-el="source-required">Включите аудио вкладки / экрана или микрофон / аудиовход.</p>
    <p class="el-warning" data-el="mix-warning" hidden>Микрофон может повторно захватывать звук вкладки. Для чистого результата используйте наушники.</p>
  </div>
  <div data-el="status" data-js-ready-marker="pending">Статус: HTML iframe загружен; JavaScript ещё не подключён</div>
  <details data-el="diagnostics-wrap">
    <summary>Диагностика</summary>
    <div data-el="diagnostics-placeholder" class="el-diagnostics-placeholder">Диагностика появится после запуска realtime-сессии.</div>
    <pre data-el="diagnostics" hidden></pre>
  </details>
  <h3 class="el-section-title">Предварительный текст</h3>
  <div data-el="partial" style="min-height:56px;border:1px dashed #a7b3c4;border-radius:10px;padding:12px;background:#fcfcff;"></div>
  <h3 class="el-section-title">Подтверждённый текст</h3>
  <div class="el-session-header" data-el="session-header"><div class="el-live-title">Живой подтверждённый текст</div><div class="el-source-summary" data-el="source-summary">Источник: не выбран</div><div class="el-format-id">Формат: realtime_live_transcript_v1</div></div>
  <div data-el="committed" data-schema="realtime_live_transcript_v1" aria-live="polite"></div>
</div>
"""


def _build_realtime_app_javascript(root_id: str, config_setup_js: str, *, async_boot: bool = False) -> str:
    """Return shared realtime frontend JavaScript with deterministic config setup."""

    root_id = _validate_realtime_colab_root_id(root_id)
    iife_head = "async ()" if async_boot else "()"

    return f"""
({iife_head} => {{
{config_setup_js}
  const RENDER_ROOT_ID = '{root_id}';
  const root = document.getElementById(RENDER_ROOT_ID);
  if (!root) {{
    console.error('LIVE-COLAB-01 root not found for current render:', RENDER_ROOT_ID);
    return;
  }}
  const byEl = (name) => root.querySelector(`[data-el="${{name}}"]`);
  const displayAudioEl = byEl('display-audio');
  const inputDeviceEl = byEl('input-device');
  const refreshDevicesBtn = byEl('refresh-devices');
  const startBtn = byEl('start');
  const stopBtn = byEl('stop');
  const copyBtn = byEl('copy');
  const downloadBtn = byEl('download');
  const clearBtn = byEl('clear');
  const sourceRequiredEl = byEl('source-required');
  const mixWarningEl = byEl('mix-warning');
  const statusEl = byEl('status');
  const diagWrapEl = byEl('diagnostics-wrap');
  const diagPlaceholderEl = byEl('diagnostics-placeholder');
  const diagEl = byEl('diagnostics');
  const partialEl = byEl('partial');
  const committedEl = byEl('committed');
  const sourceSummaryEl = byEl('source-summary');

  let currentAttempt = null;
  let attemptGeneration = 0;
  let finalTranscript = '';
  let committedSegmentCount = 0;
  let isRunning = false;

  const STATUS = {{ready:'Готово', starting:'Запуск…', websocketOpen:'Соединение установлено', sessionStarted:'Сессия распознавания запущена', stopped:'Остановлено', closed:'Соединение закрыто'}};
  const WEBSOCKET_OPEN_TIMEOUT_MS = 15000;
  const SESSION_CONFIG_TIMEOUT_MS = 15000;
  const MAX_WEBSOCKET_BUFFERED_BYTES = 1024 * 1024;
  function setStatus(text) {{ statusEl.textContent = 'Статус: ' + text; }}
  function hasDisplayAudio() {{ return displayAudioEl.value === 'on'; }}
  function hasInputAudio() {{ return inputDeviceEl.value !== 'off'; }}
  function updateTranscriptButtons() {{ const hasText = finalTranscript.length > 0; copyBtn.disabled = !hasText; downloadBtn.disabled = !hasText; clearBtn.disabled = !hasText; }}
  function selectedSourceSummary() {{
    if (hasDisplayAudio() && hasInputAudio()) return 'Аудио вкладки / экрана + микрофон / аудиовход';
    if (hasDisplayAudio()) return 'Только аудио вкладки / экрана';
    if (hasInputAudio()) return 'Только микрофон / аудиовход';
    return 'Источник не выбран';
  }}
  function updateSourceSummary() {{ if (sourceSummaryEl) sourceSummaryEl.textContent = 'Источник: ' + selectedSourceSummary(); }}
  function renderCommittedEmptyState() {{
    committedEl.replaceChildren();
    const empty = document.createElement('p');
    empty.className = 'el-committed-empty';
    empty.textContent = 'Пока нет подтверждённых фрагментов. Текст появится после события commit от провайдера.';
    committedEl.appendChild(empty);
  }}
  function appendCommittedSegment(text) {{
    const segment = document.createElement('p');
    segment.className = 'el-committed-segment';
    segment.dataset.segmentIndex = String(committedSegmentCount + 1);
    segment.textContent = text;
    if (committedSegmentCount === 0) committedEl.replaceChildren();
    committedEl.appendChild(segment);
    committedSegmentCount += 1;
  }}
  function clearCommittedSegments() {{ finalTranscript = ''; committedSegmentCount = 0; renderCommittedEmptyState(); updateTranscriptButtons(); }}
  function updateSourceUi() {{
    const anySource = hasDisplayAudio() || hasInputAudio();
    startBtn.disabled = isRunning || !anySource;
    stopBtn.disabled = !isRunning;
    sourceRequiredEl.hidden = anySource;
    mixWarningEl.hidden = !(hasDisplayAudio() && hasInputAudio() && !isRunning);
    updateSourceSummary();
  }}
  function setSourceControlsDisabled(disabled) {{ displayAudioEl.disabled = disabled; inputDeviceEl.disabled = disabled; refreshDevicesBtn.disabled = disabled; }}
  function markJsReady() {{ root.dataset.jsReady = 'true'; statusEl.dataset.jsReadyMarker = 'attached'; setStatus(STATUS.ready); renderCommittedEmptyState(); updateSourceUi(); updateTranscriptButtons(); }}
  function log(text) {{
    const line = '[' + new Date().toLocaleTimeString() + '] ' + text;
    diagPlaceholderEl.hidden = true; diagEl.hidden = false; diagWrapEl.open = true;
    diagEl.textContent = (diagEl.textContent ? diagEl.textContent + '\\n' : '') + line;
  }}
  function knownErrorMessage(value) {{
    const lower = String(value || '').toLowerCase();
    for (const [key, message] of Object.entries(CONFIG.messages)) {{ if (lower.includes(key)) return message; }}
    return 'Ошибка WebSocket realtime-распознавания. Проверьте соединение, источник аудио и попробуйте снова.';
  }}

  // frontend state/session lifecycle
  function createAttempt() {{ return {{id: ++attemptGeneration, ws: null, audioContext: null, processor: null, sourceNodes: [], mediaStreams: [], trackEndListeners: [], cleanupDone: false, cancelled: false, userStopRequested: false, websocketCreated: false, websocketOpenTimer: null, sessionConfigAbortController: null, sourceEndHandled: false}}; }}
  function ownsCurrentUi(attempt) {{ return currentAttempt && currentAttempt.id === attempt.id; }}
  function isAttemptActive(attempt) {{ return ownsCurrentUi(attempt) && !attempt.cancelled && !attempt.cleanupDone; }}
  function assertAttemptActive(attempt) {{ if (!isAttemptActive(attempt)) throw new Error('STALE_ATTEMPT'); }}
  function stopStream(stream) {{ if (stream) stream.getTracks().forEach(track => track.stop()); }}
  function stopStreams(streams) {{ streams.forEach(stopStream); }}
  function resetUiAfterAttempt() {{ isRunning = false; partialEl.textContent = ''; setSourceControlsDisabled(false); updateSourceUi(); }}
  function initializeAttemptUi(attempt) {{
    currentAttempt = attempt;
    isRunning = true;
    setSourceControlsDisabled(true);
    updateSourceUi();
    partialEl.textContent = '';
    setStatus(STATUS.starting);
  }}
  function cleanupAttempt(attempt, {{closeSocket = false, socketCloseReason = 'Завершение сессии', finalStatus = null, logMessage = null}} = {{}}) {{
    const current = ownsCurrentUi(attempt);
    const shouldCloseSocket = closeSocket && attempt.ws && (attempt.ws.readyState === WebSocket.OPEN || attempt.ws.readyState === WebSocket.CONNECTING);
    if (attempt.cleanupDone) {{ if (shouldCloseSocket) {{ try {{ attempt.ws.close(1000, socketCloseReason); }} catch (e) {{}} }} if (current && finalStatus) setStatus(finalStatus); return; }}
    attempt.cleanupDone = true;
    if (attempt.websocketOpenTimer) clearTimeout(attempt.websocketOpenTimer); attempt.websocketOpenTimer = null;
    if (attempt.sessionConfigAbortController) attempt.sessionConfigAbortController.abort(); attempt.sessionConfigAbortController = null;
    try {{ if (attempt.processor) attempt.processor.disconnect(); }} catch (e) {{}}
    attempt.processor = null;
    attempt.sourceNodes.forEach(node => {{ try {{ node.disconnect(); }} catch (e) {{}} }}); attempt.sourceNodes = [];
    attempt.trackEndListeners.forEach((item) => {{ try {{ item.track.removeEventListener('ended', item.listener); }} catch (e) {{}} }}); attempt.trackEndListeners = [];
    stopStreams(attempt.mediaStreams); attempt.mediaStreams = [];
    if (shouldCloseSocket) {{ try {{ attempt.ws.close(1000, socketCloseReason); }} catch (e) {{}} }}
    attempt.ws = null;
    if (attempt.audioContext && attempt.audioContext.state !== 'closed') attempt.audioContext.close();
    attempt.audioContext = null;
    if (current) {{ resetUiAfterAttempt(); if (finalStatus) setStatus(finalStatus); if (logMessage) log(logMessage); }}
  }}

  // live transcript presentation
  function appendCommitted(text) {{ if (!text) return; finalTranscript += (finalTranscript && !finalTranscript.endsWith('\\n') ? '\\n' : '') + text; appendCommittedSegment(text); updateTranscriptButtons(); }}
  function pickTranscriptText(data) {{ return data.text || data.transcript || data.partial_transcript || data.committed_transcript || data.final_transcript || data.message || ''; }}
  function handleRealtimeEvent(data) {{
    const eventType = String(data.type || data.event || data.message_type || data.status || '').toLowerCase();
    if (eventType.includes('session_started') || eventType.includes('session started')) {{ setStatus(STATUS.sessionStarted); log('ElevenLabs session_started'); return; }}
    if (eventType.includes('error') || data.error || data.error_code) {{ const code = data.error_code || data.code || data.error || eventType; log(knownErrorMessage(code)); return; }}
    const text = pickTranscriptText(data);
    if (!text) {{ log('Событие realtime без текста: ' + eventType); return; }}
    if (eventType.includes('partial') || data.is_final === false) {{ partialEl.textContent = text; return; }}
    if (eventType.includes('commit') || eventType.includes('final') || data.is_final === true) {{ partialEl.textContent = ''; appendCommitted(text); return; }}
    partialEl.textContent = text;
  }}
  function floatTo16BitPcmBase64(float32) {{
    const buffer = new ArrayBuffer(float32.length * 2); const view = new DataView(buffer);
    for (let i = 0; i < float32.length; i++) {{ const s = Math.max(-1, Math.min(1, float32[i])); view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true); }}
    const bytes = new Uint8Array(buffer); let binary = ''; const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {{ binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk)); }}
    return btoa(binary);
  }}
  function downsampleMono(input, inputRate, outputRate) {{
    if (inputRate === outputRate) return input; const ratio = inputRate / outputRate; const newLength = Math.round(input.length / ratio); const result = new Float32Array(newLength); let offsetResult = 0; let offsetBuffer = 0;
    while (offsetResult < result.length) {{ const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio); let accum = 0; let count = 0; for (let i = offsetBuffer; i < nextOffsetBuffer && i < input.length; i++) {{ accum += input[i]; count++; }} result[offsetResult] = count ? accum / count : 0; offsetResult++; offsetBuffer = nextOffsetBuffer; }}
    return result;
  }}

  // browser capture and mixing
  async function populateInputDevices(attempt = null) {{
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    const current = inputDeviceEl.value;
    const devices = await navigator.mediaDevices.enumerateDevices();
    if (attempt) assertAttemptActive(attempt);
    const audioInputs = devices.filter(device => device.kind === 'audioinput');
    inputDeviceEl.innerHTML = '<option value="off">Выключено</option><option value="">Устройство по умолчанию</option>';
    audioInputs.forEach((device, index) => {{
      const option = document.createElement('option'); option.value = device.deviceId;
      option.textContent = device.label || ('Аудиовход ' + (index + 1)); inputDeviceEl.appendChild(option);
    }});
    if ([...inputDeviceEl.options].some(option => option.value === current)) inputDeviceEl.value = current;
    updateSourceUi();
  }}
  function refreshInputDevicesPassively(reason) {{ populateInputDevices().catch(err => log(reason + (err && err.message ? err.message : String(err)))); }}
  function refreshInputDevicesAfterPermission(attempt) {{
    return populateInputDevices(attempt).catch((err) => {{ if (String(err && err.message) !== 'STALE_ATTEMPT') log('Не удалось обновить список аудиоустройств после разрешения браузера.'); }});
  }}
  function microphoneConstraints() {{
    const audio = {{echoCancellation: {{ideal: true}}, noiseSuppression: {{ideal: true}}, autoGainControl: {{ideal: true}}, channelCount: {{ideal: 1}}}};
    if (inputDeviceEl.value) audio.deviceId = {{exact: inputDeviceEl.value}};
    return {{audio}};
  }}
  async function getDisplayAudioStream(attempt) {{
    const stream = await navigator.mediaDevices.getDisplayMedia({{video: true, audio: true}});
    if (!isAttemptActive(attempt)) {{ stopStream(stream); throw new Error('STALE_ATTEMPT'); }}
    if (stream.getAudioTracks().length === 0) {{ stopStream(stream); throw new Error('Браузер не передал аудиодорожку для выбранной вкладки/экрана. Попробуйте вкладку с включённой передачей звука или другой источник.'); }}
    return stream;
  }}
  async function getInputAudioStream(attempt) {{
    const stream = await navigator.mediaDevices.getUserMedia(microphoneConstraints());
    if (!isAttemptActive(attempt)) {{ stopStream(stream); throw new Error('STALE_ATTEMPT'); }}
    return stream;
  }}
  function handleCapturedTrackEnded(attempt, sourceLabel) {{
    if (!isAttemptActive(attempt) || attempt.sourceEndHandled) return;
    attempt.sourceEndHandled = true;
    attempt.cancelled = true;
    cleanupAttempt(attempt, {{closeSocket: true, finalStatus: STATUS.closed, logMessage: sourceLabel + ' завершил передачу. Все медиадорожки освобождены; нажмите «Начать» для новой сессии.'}});
  }}
  async function buildCaptureStream(attempt) {{
    const streams = [];
    function registerCapturedStream(stream, sourceLabel) {{
      if (!isAttemptActive(attempt)) {{ stopStream(stream); throw new Error('STALE_ATTEMPT'); }}
      stream.getTracks().forEach((track) => {{
        const listener = () => handleCapturedTrackEnded(attempt, sourceLabel);
        track.addEventListener('ended', listener, {{once: true}});
        attempt.trackEndListeners.push({{track, listener}});
        if (track.readyState === 'ended') queueMicrotask(listener);
      }});
      attempt.mediaStreams.push(stream); streams.push(stream); return stream;
    }}
    try {{
      if (hasDisplayAudio()) registerCapturedStream(await getDisplayAudioStream(attempt), 'Аудио вкладки / экрана');
      if (hasInputAudio()) registerCapturedStream(await getInputAudioStream(attempt), 'Микрофон / аудиовход');
      await refreshInputDevicesAfterPermission(attempt);
      assertAttemptActive(attempt);
      if (streams.length === 1) return streams[0];
      if (streams.length > 1) {{
        const ctx = new AudioContext(); attempt.audioContext = ctx; const destination = ctx.createMediaStreamDestination();
        streams.forEach(stream => {{ const source = ctx.createMediaStreamSource(stream); source.connect(destination); attempt.sourceNodes.push(source); }});
        log('Смешивание источников: аудио вкладки / экрана + микрофон / аудиовход. Возможен повторный захват звука микрофоном.');
        return destination.stream;
      }}
    }} catch (err) {{ stopStreams(streams); throw err; }}
    throw new Error('Включите аудио вкладки / экрана или микрофон / аудиовход.');
  }}
  function isPermissionCancellation(err) {{ return ['NotAllowedError', 'PermissionDeniedError', 'AbortError'].includes(err && err.name); }}

  // WebSocket send/receive lifecycle
  function handleWebSocketOpen(attempt) {{
    if (!isAttemptActive(attempt)) return;
    if (attempt.websocketOpenTimer) clearTimeout(attempt.websocketOpenTimer);
    attempt.websocketOpenTimer = null;
    setStatus(STATUS.websocketOpen);
    log('WebSocket открыт; используется ' + CONFIG.modelId + ' / ' + CONFIG.audioFormat + ' / commit_strategy=' + CONFIG.commitStrategy);
  }}
  function handleWebSocketError(attempt) {{ if (!isAttemptActive(attempt)) return; log('Ошибка WebSocket. Проверьте сеть, одноразовый токен realtime и доступ к ElevenLabs realtime.'); }}
  async function loadRealtimeSessionConfig(attempt) {{
    assertAttemptActive(attempt);
    const controller = new AbortController();
    attempt.sessionConfigAbortController = controller;
    const timeout = setTimeout(() => controller.abort(), SESSION_CONFIG_TIMEOUT_MS);
    try {{
      const launchCapability = new URLSearchParams(window.location.hash.slice(1)).get('launch') || '';
      const response = await fetch('/session-config.json', {{method: 'POST', headers: {{'X-Realtime-Launch': launchCapability}}, cache: 'no-store', signal: controller.signal}});
      assertAttemptActive(attempt);
      if (!response.ok) {{
        throw new Error('Не удалось подготовить новую realtime-сессию. Проверьте ключ API и попробуйте ещё раз.');
      }}
      const sessionConfig = await response.json();
      assertAttemptActive(attempt);
      if (!sessionConfig || typeof sessionConfig.wsUrl !== 'string' || !sessionConfig.wsUrl) {{
        throw new Error('Не удалось подготовить новую realtime-сессию. Попробуйте ещё раз.');
      }}
      return sessionConfig;
    }} catch (error) {{
      if (isAttemptActive(attempt) && error && error.name === 'AbortError') {{
        throw new Error('Превышено время ожидания подготовки realtime-сессии. Нажмите «Начать» для новой попытки.');
      }}
      throw error;
    }} finally {{
      clearTimeout(timeout);
      if (attempt.sessionConfigAbortController === controller) attempt.sessionConfigAbortController = null;
    }}
  }}
  function handleWebSocketClose(attempt, event) {{
    if (!ownsCurrentUi(attempt)) return;
    if (!isAttemptActive(attempt) && !attempt.userStopRequested) return;
    const expected = attempt.userStopRequested;
    log((expected ? 'WebSocket закрыт после команды пользователя: ' : 'Неожиданное закрытие WebSocket: ') + 'code=' + event.code + ', reason=' + (event.reason || ''));
    cleanupAttempt(attempt, {{finalStatus: expected ? STATUS.stopped : STATUS.closed, logMessage: expected ? null : 'Соединение закрыто не по команде пользователя; медиадорожки освобождены.'}});
  }}
  function handleWebSocketMessage(attempt, event) {{
    if (!isAttemptActive(attempt)) return;
    try {{ handleRealtimeEvent(JSON.parse(event.data)); }} catch (err) {{ log('Получено не-JSON сообщение realtime; оно пропущено.'); }}
  }}
  function attachWebSocket(attempt, wsUrl) {{
    assertAttemptActive(attempt);
    attempt.websocketCreated = true;
    attempt.ws = new WebSocket(wsUrl);
    attempt.websocketOpenTimer = setTimeout(() => {{
      if (!isAttemptActive(attempt) || !attempt.ws || attempt.ws.readyState === WebSocket.OPEN) return;
      attempt.cancelled = true;
      cleanupAttempt(attempt, {{closeSocket: true, finalStatus: STATUS.closed, logMessage: 'Превышено время ожидания WebSocket. Медиадорожки освобождены; нажмите «Начать» для новой сессии.'}});
    }}, WEBSOCKET_OPEN_TIMEOUT_MS);
    attempt.ws.onopen = () => handleWebSocketOpen(attempt);
    attempt.ws.onerror = () => handleWebSocketError(attempt);
    attempt.ws.onclose = (event) => handleWebSocketClose(attempt, event);
    attempt.ws.onmessage = (event) => handleWebSocketMessage(attempt, event);
  }}
  function sendAudioProcessChunk(attempt, event) {{
    if (!isAttemptActive(attempt) || !attempt.ws || attempt.ws.readyState !== WebSocket.OPEN) return;
    if (attempt.ws.bufferedAmount > MAX_WEBSOCKET_BUFFERED_BYTES) {{
      attempt.cancelled = true;
      cleanupAttempt(attempt, {{closeSocket: true, finalStatus: STATUS.closed, logMessage: 'WebSocket не успевает отправлять аудио. Сессия безопасно остановлена; проверьте сеть и начните новую.'}});
      return;
    }}
    const mono = event.inputBuffer.getChannelData(0);
    const pcm16k = downsampleMono(mono, attempt.audioContext.sampleRate, 16000);
    const payload = floatTo16BitPcmBase64(pcm16k);
    attempt.ws.send(JSON.stringify({{message_type: 'input_audio_chunk', audio_base_64: payload, sample_rate: 16000}}));
  }}
  function connectAudioProcessor(attempt, stream) {{
    const source = attempt.audioContext.createMediaStreamSource(stream); attempt.sourceNodes.push(source);
    attempt.processor = attempt.audioContext.createScriptProcessor(4096, 1, 1);
    attempt.processor.onaudioprocess = (event) => sendAudioProcessChunk(attempt, event);
    source.connect(attempt.processor); attempt.processor.connect(attempt.audioContext.destination);
  }}
  function handleStartFailure(attempt, err) {{
    if (!ownsCurrentUi(attempt)) {{ cleanupAttempt(attempt); return; }}
    if (!isAttemptActive(attempt) || String(err && err.message) === 'STALE_ATTEMPT') {{ cleanupAttempt(attempt); return; }}
    const message = isPermissionCancellation(err) ? 'Разрешение на захват аудио отменено или отклонено в браузере. Выберите источник и нажмите «Начать» для повторной попытки.' : (err && err.message ? err.message : String(err));
    log(message);
    cleanupAttempt(attempt, {{finalStatus: STATUS.ready, logMessage: attempt.websocketCreated ? null : 'Запуск остановлен до создания WebSocket; состояние готово к повторной попытке.'}});
  }}

  async function start() {{
    if (isRunning || (!hasDisplayAudio() && !hasInputAudio())) return;
    const attempt = createAttempt(); initializeAttemptUi(attempt);
    try {{
      if (!navigator.mediaDevices) throw new Error('MediaDevices API недоступен в этом окружении браузера.');
      const stream = await buildCaptureStream(attempt); assertAttemptActive(attempt);
      if (!attempt.audioContext) attempt.audioContext = new AudioContext();
      await attempt.audioContext.resume(); assertAttemptActive(attempt);
      const sessionConfig = await loadRealtimeSessionConfig(attempt); assertAttemptActive(attempt);
      attachWebSocket(attempt, sessionConfig.wsUrl);
      connectAudioProcessor(attempt, stream);
      log('Захват аудио запущен. Для аудио вкладки / экрана требуется поддержка браузера и выбранная передача звука.');
    }} catch (err) {{
      handleStartFailure(attempt, err);
    }}
  }}
  function stop(closeSocket = true) {{
    const attempt = currentAttempt;
    if (!attempt) {{ isRunning = false; partialEl.textContent = ''; setSourceControlsDisabled(false); updateSourceUi(); setStatus(STATUS.stopped); return; }}
    attempt.userStopRequested = true;
    attempt.cancelled = true;
    cleanupAttempt(attempt, {{closeSocket, socketCloseReason: 'Остановлено пользователем', finalStatus: STATUS.stopped, logMessage: closeSocket ? 'Остановлено: медиадорожки освобождены; закрытие WebSocket запрошено.' : null}});
  }}
  startBtn.addEventListener('click', start);
  stopBtn.addEventListener('click', () => stop(true));
  refreshDevicesBtn.addEventListener('click', () => refreshInputDevicesPassively('Не удалось обновить список устройств: '));
  displayAudioEl.addEventListener('change', updateSourceUi); inputDeviceEl.addEventListener('change', updateSourceUi);
  copyBtn.addEventListener('click', async () => {{ if (!finalTranscript) return; await navigator.clipboard.writeText(finalTranscript); log('Подтверждённый текст скопирован в буфер обмена.'); }});
  downloadBtn.addEventListener('click', () => {{ if (!finalTranscript) return; const blob = new Blob([finalTranscript], {{type: 'text/plain;charset=utf-8'}}); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'elevenlabs-realtime-transcript.txt'; a.click(); URL.revokeObjectURL(url); }});
  clearBtn.addEventListener('click', () => {{
    if (!finalTranscript) return;
    const confirmed = window.confirm('Будет очищен только подтверждённый текст в текущей вкладке. Google Docs, manifest, предварительный текст и текущая сессия не будут затронуты.');
    if (!confirmed) return;
    clearCommittedSegments(); log('Подтверждённый текст очищен в текущей вкладке. Предварительный текст, диагностика, аудио и WebSocket не затронуты.');
  }});
  markJsReady(); populateInputDevices().catch(() => {{ log('Список устройств пока недоступен: браузер может скрывать названия до разрешения.'); }});
  if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) navigator.mediaDevices.addEventListener('devicechange', () => refreshInputDevicesPassively('Не удалось обновить список устройств после devicechange: '));
}})();
"""

def build_realtime_colab_javascript(token: str, root_id: str) -> str:
    """Return executable JavaScript for the current Colab realtime UI render."""

    config_json = json.dumps(
        {
            "wsUrl": build_realtime_websocket_url(token),
            "modelId": REALTIME_MODEL_ID,
            "audioFormat": REALTIME_AUDIO_FORMAT,
            "commitStrategy": REALTIME_COMMIT_STRATEGY,
            "messages": KNOWN_ERROR_MESSAGES_RU,
        },
        ensure_ascii=False,
    )
    return _build_realtime_app_javascript(root_id, f"  const CONFIG = {config_json};")


def build_realtime_colab_iframe_srcdoc(token: str, root_id: str | None = None) -> str:
    """Return the complete realtime app document executed inside a Colab iframe."""

    root_id = _validate_realtime_colab_root_id(root_id or create_realtime_colab_root_id())
    shell = build_realtime_colab_html_shell(root_id)
    javascript = build_realtime_colab_javascript(token, root_id)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VoiceOps Studio — realtime Colab</title>
</head>
<body style="margin:0;padding:0;background:#fff;">
{shell}
<script>
{javascript}
</script>
</body>
</html>
"""


def build_realtime_colab_iframe_html(token: str) -> str:
    """Return outer Colab HTML containing only a sandboxed srcdoc iframe."""

    srcdoc = build_realtime_colab_iframe_srcdoc(token)
    escaped_srcdoc = html.escape(srcdoc, quote=True)
    return f'''
<iframe
  title="LIVE-COLAB-01 прототип realtime-распознавания"
  srcdoc="{escaped_srcdoc}"
  allow="microphone; display-capture; clipboard-write"
  sandbox="allow-scripts allow-same-origin allow-downloads"
  style="width:100%;min-height:760px;border:0;border-radius:14px;display:block;"
></iframe>
'''


def build_realtime_colab_html(token: str) -> str:
    """Return the iframe-based Colab HTML launcher for the realtime app."""

    return build_realtime_colab_iframe_html(token)


def build_realtime_frontend_config() -> dict[str, Any]:
    """Build static browser config for a standalone page without secrets or token URLs."""

    return {
        "modelId": REALTIME_MODEL_ID,
        "audioFormat": REALTIME_AUDIO_FORMAT,
        "commitStrategy": REALTIME_COMMIT_STRATEGY,
        "messages": KNOWN_ERROR_MESSAGES_RU,
        "bridge": "LIVE-COLAB-PROXY-01",
    }


def build_realtime_session_config(token: str) -> dict[str, str]:
    """Build one short-lived browser session config from a fresh single-use token."""

    return {"wsUrl": build_realtime_websocket_url(token)}


def build_realtime_frontend_javascript(token: str | None, root_id: str) -> str:
    """Return external frontend JavaScript for the standalone Colab proxy page."""

    # The token argument is intentionally not embedded in this executable asset.
    # LIVE-COLAB-PROXY-01 serves browser configuration through /config.json so
    # the standalone HTML can avoid inline script execution under Colab proxy CSPs.
    del token
    root_id = _validate_realtime_colab_root_id(root_id)
    config_setup_js = f'''  async function loadRealtimeConfig() {{
    const response = await fetch('/config.json', {{cache: 'no-store'}});
    if (!response.ok) {{
      throw new Error('HTTP ' + response.status + ' при загрузке /config.json');
    }}
    return response.json();
  }}
  function markConfigLoadError(err) {{
    const root = document.getElementById('{root_id}');
    const statusEl = root ? root.querySelector('[data-el="status"]') : null;
    const message = err && err.message ? err.message : String(err);
    if (statusEl) {{
      statusEl.textContent = 'Статус: ошибка загрузки config.json — ' + message;
      statusEl.dataset.jsReadyMarker = 'config-error';
    }}
    console.error('LIVE-COLAB-PROXY-01 config load failed:', err);
  }}
  let CONFIG;
  try {{
    CONFIG = await loadRealtimeConfig();
  }} catch (err) {{
    markConfigLoadError(err);
    return;
  }}'''
    return _build_realtime_app_javascript(root_id, config_setup_js, async_boot=True)


def build_realtime_frontend_html(token: str | None = None, root_id: str | None = None) -> str:
    """Return a standalone realtime browser page for Colab proxy/new-tab use."""

    root_id = _validate_realtime_colab_root_id(root_id or create_realtime_colab_root_id())
    shell = build_realtime_colab_html_shell(root_id)
    shell = shell.replace(
        "LIVE-COLAB-01: прототип realtime-распознавания",
        "LIVE-COLAB-PROXY-01: отдельная realtime-страница realtime-распознавания",
    )
    shell = shell.replace(
        "Экспериментальный Colab-прототип: без сохранения в Google Docs, без manifest, без проектов спикеров. Основной ключ API остаётся на стороне Python; браузер получает только одноразовый токен realtime.",
        "Экспериментальная отдельная realtime-страница через Colab proxy/new tab: без сохранения в Google Docs, без manifest, без проектов спикеров. Браузер получает только одноразовый токен realtime; launcher/proxy Colab остаётся заменяемой инфраструктурой для будущей PWA.",
    )
    shell = shell.replace(
        "Статус: HTML iframe загружен; JavaScript ещё не подключён",
        "Статус: страница загружена",
    )
    del token
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VoiceOps Studio — realtime Colab</title>
</head>
<body style="margin:0;padding:16px;background:#f8fafc;">
{shell}
<script src="/realtime.js" defer></script>
</body>
</html>
"""


class _RealtimeFrontendRequestHandler(BaseHTTPRequestHandler):
    """Serve the standalone realtime page from the Colab runtime only."""

    server_version = "ElevenLabsRealtimeColabProxy/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return

    def _send_bytes(self, body: bytes, *, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler method
        if not self._browser_request_allowed(check_fetch_site=False):
            self._send_bytes(b"forbidden", content_type="text/plain", status=403)
            return
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = self.server.frontend_html.encode("utf-8")  # type: ignore[attr-defined]
            self._send_bytes(body, content_type="text/html; charset=utf-8")
            return
        if path == "/realtime.js":
            body = self.server.frontend_javascript.encode("utf-8")  # type: ignore[attr-defined]
            self._send_bytes(body, content_type="application/javascript; charset=utf-8")
            return
        if path == "/config.json":
            body = json.dumps(self.server.frontend_config, ensure_ascii=False).encode("utf-8")  # type: ignore[attr-defined]
            self._send_bytes(body, content_type="application/json; charset=utf-8")
            return
        if path == "/session-config.json":
            self._send_bytes(b"method not allowed", content_type="text/plain", status=405)
            return
        if path == "/healthz":
            self._send_bytes(b"ok", content_type="text/plain; charset=utf-8")
            return
        self._send_bytes(b"not found", content_type="text/plain; charset=utf-8", status=404)

    def _browser_request_allowed(self, *, check_fetch_site: bool = True) -> bool:
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in self.server.allowed_hosts:
            return False
        origins = self.headers.get_all("Origin", [])
        if origins and (len(origins) != 1 or origins[0] not in self.server.allowed_origins):
            return False
        return not check_fetch_site or self.headers.get("Sec-Fetch-Site", "same-origin") in {"same-origin", "none"}

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler method
        capability = self.headers.get("X-Realtime-Launch", "")
        if (not self._browser_request_allowed() or not capability.isascii()
                or not secrets.compare_digest(capability, self.server.launch_capability)):
            self._send_bytes(b"forbidden", content_type="text/plain", status=403)
            return
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0") != "0":
            self.close_connection = True
            self._send_bytes(b"invalid request", content_type="text/plain", status=400)
            return
        if urlparse(self.path).path == "/session-config.json":
            try:
                token = self.server.realtime_token_factory()  # type: ignore[attr-defined]
                body = json.dumps(build_realtime_session_config(token), ensure_ascii=False).encode("utf-8")
                self._send_bytes(body, content_type="application/json; charset=utf-8")
            except Exception:
                body = json.dumps({"error": "Не удалось подготовить новую realtime-сессию. Проверьте ключ API и попробуйте ещё раз."}, ensure_ascii=False).encode("utf-8")
                self._send_bytes(body, content_type="application/json; charset=utf-8", status=503)
            return
        self._send_bytes(b"not found", content_type="text/plain; charset=utf-8", status=404)


def start_realtime_frontend_server(
    token_factory: Callable[[], str], *, host: str = "127.0.0.1", port: int = 0
) -> tuple[ThreadingHTTPServer, str]:
    """Start a lightweight local HTTP server for the standalone browser page."""

    root_id = create_realtime_colab_root_id()
    frontend_html = build_realtime_frontend_html(root_id=root_id)
    frontend_javascript = build_realtime_frontend_javascript(None, root_id)
    frontend_config = build_realtime_frontend_config()
    server = ThreadingHTTPServer((host, port), _RealtimeFrontendRequestHandler)
    server.frontend_html = frontend_html  # type: ignore[attr-defined]
    server.frontend_javascript = frontend_javascript  # type: ignore[attr-defined]
    server.frontend_config = frontend_config  # type: ignore[attr-defined]
    server.realtime_token_factory = token_factory  # type: ignore[attr-defined]
    actual_host, actual_port = server.server_address[:2]
    local_url = f"http://{actual_host}:{actual_port}/"
    server.launch_capability = secrets.token_urlsafe(32)
    server.allowed_hosts = {f"{actual_host}:{actual_port}", f"localhost:{actual_port}"}
    server.allowed_origins = {f"http://{authority}" for authority in server.allowed_hosts}
    thread = threading.Thread(target=server.serve_forever, name="elevenlabs-realtime-proxy", daemon=True)
    thread.start()
    _REALTIME_PROXY_SERVERS.append(server)
    return server, local_url + "#launch=" + server.launch_capability


def get_colab_proxy_url(port: int) -> str | None:
    """Return the standard Colab proxy URL for a local runtime port when available."""

    if (
        importlib.util.find_spec("google") is None
        or importlib.util.find_spec("google.colab") is None
        or importlib.util.find_spec("google.colab.output") is None
    ):
        return None
    from google.colab import output as colab_output

    try:
        proxy_url = colab_output.eval_js(f"google.colab.kernel.proxyPort({int(port)})")
    except Exception:
        return None
    if isinstance(proxy_url, str) and proxy_url.strip():
        return proxy_url.strip()
    return None


def _frontend_proxy_launch_url(server: ThreadingHTTPServer, proxy_url: str) -> str:
    parsed_proxy = urlparse(proxy_url)
    if parsed_proxy.scheme != "https" or not parsed_proxy.hostname or parsed_proxy.username or parsed_proxy.password:
        raise RealtimeTokenError("Invalid Colab proxy origin.")
    server.allowed_hosts.add(parsed_proxy.netloc.lower())
    server.allowed_origins.add(f"https://{parsed_proxy.netloc.lower()}")
    return parsed_proxy._replace(fragment="launch=" + server.launch_capability).geturl()


def build_realtime_proxy_launch_html(
    public_url: str, local_url: str, *, used_colab_proxy: bool
) -> str:
    """Build the Colab output containing the new-tab bridge link and warnings."""

    escaped_public_url = html.escape(public_url, quote=True)
    escaped_local_url = html.escape(urldefrag(local_url)[0], quote=True)
    proxy_note = "Colab proxy URL активен." if used_colab_proxy else (
        "Не удалось получить Colab proxy URL автоматически. Если ссылка localhost не открывается из браузера, "
        "перезапустите в Google Colab runtime и проверьте доступность google.colab.kernel.proxyPort(port)."
    )
    return f"""
<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.45;max-width:900px;border:1px solid #d8dee9;border-radius:14px;padding:16px;margin:8px 0;background:#fff;color:#17202a;">
  <h2 style="margin:0 0 8px;">LIVE-COLAB-PROXY-01: отдельная realtime-страница realtime-распознавания</h2>
  <p style="margin:0 0 12px;">Экспериментальный контур: Colab запускает локальный HTTP-сервер Python и открывает отдельную realtime-страницу браузера в новой вкладке.</p>
  <p style="margin:0 0 12px;"><a href="{escaped_public_url}" target="_blank" rel="noopener noreferrer" style="display:inline-block;padding:10px 14px;border-radius:10px;background:#2563eb;color:#fff;text-decoration:none;font-weight:700;">Открыть realtime-страницу в новой вкладке</a></p>
  <ul style="margin:0 0 12px 20px;padding:0;">
    <li>Без сохранения в Google Docs.</li>
    <li>Без чтения/записи manifest и без изменений схемы manifest.</li>
    <li>Без интеграции проектов спикеров.</li>
    <li>Браузер получает только одноразовый токен realtime, но не основной ключ API.</li>
    <li>Не заявляйте полный realtime E2E успех до ручной проверки Colab/browser/provider.</li>
  </ul>
  <p style="margin:0;color:#4b5563;">{html.escape(proxy_note)} Локальный runtime URL: <code>{escaped_local_url}</code></p>
</div>
"""


def launch_realtime_colab_proxy() -> None:
    """Launch LIVE-COLAB-PROXY-01 as a standalone page through Colab proxy."""

    if (
        importlib.util.find_spec("IPython") is None
        or importlib.util.find_spec("IPython.display") is None
    ):
        raise RealtimeTokenError("IPython.display is required to render the Colab proxy link.")
    from IPython.display import HTML, display

    api_key = get_elevenlabs_api_key()
    def token_factory() -> str:
        return create_realtime_single_use_token(api_key)

    server, local_url = start_realtime_frontend_server(token_factory)
    port = int(server.server_address[1])
    proxy_url = get_colab_proxy_url(port)
    if proxy_url:
        try:
            proxy_url = _frontend_proxy_launch_url(server, proxy_url)
        except RealtimeTokenError:
            server.shutdown()
            server.server_close()
            raise
    public_url = proxy_url or local_url
    display(
        HTML(
            build_realtime_proxy_launch_html(
                public_url, local_url, used_colab_proxy=proxy_url is not None
            )
        )
    )


def launch_realtime_standalone_page() -> None:
    """Compatibility alias for the LIVE-COLAB-PROXY-01 launcher."""

    launch_realtime_colab_proxy()

def launch_realtime_colab() -> None:
    """Create a realtime token and render the Colab browser UI."""

    if (
        importlib.util.find_spec("IPython") is None
        or importlib.util.find_spec("IPython.display") is None
    ):
        raise RealtimeTokenError("IPython.display is required to render the Colab realtime UI.")
    from IPython.display import HTML, display

    api_key = get_elevenlabs_api_key()
    token = create_realtime_single_use_token(api_key)
    display(HTML(build_realtime_colab_iframe_html(token)))


if __name__ == "__main__":
    launch_realtime_colab_proxy()
