import { useEffect, useMemo, useRef, useState } from "react";
import { mutateWithCsrfRetry } from "./apiClient";
import {
  DirectDriveUploadError,
  DIRECT_DRIVE_UPLOAD_MAX_FILES,
  directDriveFileSelectionError,
  newDirectDriveOperationId,
  parseDirectDriveUploadSession,
  uploadDirectDriveFile,
  type DirectDriveUploadItem,
} from "./directDriveUpload";
import { DirectUploadAmbiguousError } from "./directUpload";
import { formatBytes } from "./formatters";
import * as googlePicker from "./googlePicker";


type ItemStatus =
  | "pending"
  | "preparing"
  | "uploading"
  | "verifying"
  | "completed"
  | "cancelled"
  | "failed";

type ItemView = DirectDriveUploadItem & {
  status: ItemStatus;
  loadedBytes: number;
  error: string | null;
  webViewUrl: string | null;
  reused: boolean;
};

type VerifiedResult = {
  name: string;
  mime_type: string;
  size_bytes: number;
  web_view_url: string;
};

function statusLabel(item: ItemView) {
  if (item.status === "pending") return "Готов к загрузке";
  if (item.status === "preparing") return "Проверяем папку и доступ";
  if (item.status === "uploading") return "Загружаем напрямую в Google Drive";
  if (item.status === "verifying") return "Проверяем, что файл появился в Google Drive";
  if (item.status === "completed")
    return item.reused ? "Уже загружен — подтверждён без дубля" : "Загружен и подтверждён";
  if (item.status === "cancelled") return "Отменён — перед повтором будет проверен Drive";
  return "Не завершён";
}

function uploadErrorLabel(reason: unknown) {
  if (reason instanceof DOMException && reason.name === "AbortError")
    return "Загрузка отменена. Безопасный повтор сначала проверит Google Drive и не создаст дубль.";
  if (reason instanceof DirectUploadAmbiguousError) {
    if (reason.message === "direct_upload_aborted")
      return "Загрузка отменена. Безопасный повтор сначала проверит Google Drive и не создаст дубль.";
    return "Результат передачи пока не подтверждён. Нажмите «Повторить»: Studio сначала проверит Google Drive.";
  }
  if (reason instanceof DirectDriveUploadError) {
    if (reason.message === "direct_drive_reauthorization_required")
      return "Google Drive требует повторного подключения в Настройках.";
    if (reason.message === "direct_drive_lookup_ambiguous")
      return "В Google Drive найдено несколько результатов одной операции. Повтор заблокирован; проверьте папку вручную.";
    if (reason.message === "direct_drive_session_invalid")
      return "Google Drive не подготовил загрузку. Повторите позже.";
  }
  return "Загрузка не подтверждена. При повторе Studio сначала проверит, появился ли файл в Google Drive.";
}

function parseVerifiedResult(value: unknown, item: DirectDriveUploadItem) {
  if (!value || typeof value !== "object") return null;
  const result = value as Partial<VerifiedResult>;
  if (
    result.name !== item.file.name ||
    result.mime_type !== item.file.type.trim().toLowerCase() ||
    result.size_bytes !== item.file.size ||
    typeof result.web_view_url !== "string" ||
    result.web_view_url.length > 2000
  ) return null;
  try {
    const url = new URL(result.web_view_url);
    if (
      url.protocol !== "https:" ||
      url.hostname !== "drive.google.com" ||
      !url.pathname.startsWith("/file/d/") ||
      url.username ||
      url.password ||
      url.port
    ) return null;
  } catch {
    return null;
  }
  return result as VerifiedResult;
}

export function DirectDriveUploadPanel({
  projectId,
  csrf,
  onCsrf,
}: {
  projectId: string;
  csrf: string;
  onCsrf: (value: string) => void;
}) {
  const [folder, setFolder] = useState<{ id: string; name: string } | null>(null);
  const [items, setItems] = useState<ItemView[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const aggregate = useMemo(() => {
    const totalBytes = items.reduce((total, item) => total + item.file.size, 0);
    const loadedBytes = items.reduce(
      (total, item) =>
        total + (item.status === "completed"
          ? item.file.size
          : Math.min(item.file.size, item.loadedBytes)),
      0,
    );
    return {
      totalBytes,
      loadedBytes,
      percent: totalBytes > 0
        ? Math.min(100, Math.round((loadedBytes / totalBytes) * 100))
        : 0,
      completed: items.filter((item) => item.status === "completed").length,
    };
  }, [items]);

  const current = items.find((item) =>
    ["preparing", "uploading", "verifying"].includes(item.status),
  );
  const retryable = items.filter((item) =>
    ["pending", "cancelled", "failed"].includes(item.status),
  );
  const folderLocked = items.some((item) => item.status !== "pending");

  async function mutate<T>(path: string, options: RequestInit) {
    return mutateWithCsrfRetry<T>(path, csrf, onCsrf, options);
  }

  async function pickerSession() {
    return mutate<googlePicker.PickerSession>("/google/picker/session", {
      method: "POST",
    });
  }

  async function chooseFolder() {
    if (busy) return;
    const returnFocusTo = document.activeElement instanceof HTMLElement
      ? document.activeElement : null;
    setBusy(true);
    setError("");
    try {
      const result = await googlePicker.openGooglePicker(
        "output-folder",
        await pickerSession(),
        { returnFocusTo },
      );
      if (result.action === "picked" && result.docs.length === 1) {
        setFolder({
          id: result.docs[0].id,
          name: result.docs[0].name || "Папка Google Drive",
        });
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось выбрать папку Google Drive.",
      );
    } finally {
      setBusy(false);
    }
  }

  function chooseFiles(files: File[]) {
    const selectionError = directDriveFileSelectionError(files);
    if (selectionError) {
      setError(selectionError);
      return;
    }
    try {
      setItems(files.map((file) => ({
        operationId: newDirectDriveOperationId(),
        file,
        status: "pending",
        loadedBytes: 0,
        error: null,
        webViewUrl: null,
        reused: false,
      })));
      setError("");
    } catch {
      setError("Браузер не смог создать безопасные идентификаторы загрузки. Обновите браузер.");
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function updateItem(
    operationId: string,
    patch: Partial<Omit<ItemView, "operationId" | "file">>,
  ) {
    setItems((currentItems) => currentItems.map((item) =>
      item.operationId === operationId ? { ...item, ...patch } : item,
    ));
  }

  async function runUploads(operationIds?: string[]) {
    if (!folder || busy) return;
    const allowed = operationIds ? new Set(operationIds) : null;
    const pending = items.filter((item) =>
      (!allowed || allowed.has(item.operationId)) &&
      ["pending", "cancelled", "failed"].includes(item.status),
    );
    if (pending.length === 0) return;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setBusy(true);
    setError("");
    pending.forEach((item) => updateItem(item.operationId, {
      status: "preparing",
      loadedBytes: 0,
      error: null,
    }));
    try {
      const rawSession = await mutate<unknown>(
        `/projects/${projectId}/direct-drive-uploads/session`,
        {
          method: "POST",
          signal: controller.signal,
          body: JSON.stringify({
            folder_id: folder.id,
            files: pending.map((item) => ({
              operation_id: item.operationId,
              original_filename: item.file.name,
              mime_type: item.file.type,
              size_bytes: item.file.size,
            })),
          }),
        },
      );
      const session = parseDirectDriveUploadSession(rawSession, pending);
      if (!session)
        throw new DirectDriveUploadError("direct_drive_api_session_invalid");
      setFolder((currentFolder) => currentFolder
        ? { ...currentFolder, name: session.folderName }
        : currentFolder);
      for (const item of pending) {
        if (controller.signal.aborted) break;
        const capability = session.capabilities.get(item.operationId);
        if (!capability)
          throw new DirectDriveUploadError("direct_drive_capability_missing");
        updateItem(item.operationId, { status: "uploading" });
        try {
          const reference = await uploadDirectDriveFile({
            item,
            folderId: folder.id,
            accessToken: session.accessToken,
            expiresIn: session.expiresIn,
            signal: controller.signal,
            onProgress: (progress) => updateItem(item.operationId, {
              status: "uploading",
              loadedBytes: progress.loadedBytes,
            }),
          });
          updateItem(item.operationId, {
            status: "verifying",
            loadedBytes: item.file.size,
          });
          const rawResult = await mutate<unknown>(
            `/projects/${projectId}/direct-drive-uploads/complete`,
            {
              method: "POST",
              signal: controller.signal,
              body: JSON.stringify({
                operation_id: item.operationId,
                original_filename: item.file.name,
                mime_type: item.file.type,
                size_bytes: item.file.size,
                folder_id: folder.id,
                file_id: reference.fileId,
                capability,
              }),
            },
          );
          const result = parseVerifiedResult(rawResult, item);
          if (!result)
            throw new DirectDriveUploadError("direct_drive_result_invalid");
          updateItem(item.operationId, {
            status: "completed",
            loadedBytes: item.file.size,
            webViewUrl: result.web_view_url,
            error: null,
            reused: reference.reused,
          });
        } catch (reason) {
          const cancelled = controller.signal.aborted ||
            (reason instanceof DirectUploadAmbiguousError &&
              reason.message === "direct_upload_aborted") ||
            (reason instanceof DOMException && reason.name === "AbortError");
          updateItem(item.operationId, {
            status: cancelled ? "cancelled" : "failed",
            error: uploadErrorLabel(reason),
          });
          if (controller.signal.aborted) break;
        }
      }
    } catch (reason) {
      const message = uploadErrorLabel(reason);
      const pendingIds = new Set(pending.map((item) => item.operationId));
      setItems((currentItems) => currentItems.map((item) =>
        pendingIds.has(item.operationId) && item.status !== "completed"
          ? {
              ...item,
              status: controller.signal.aborted ? "cancelled" : "failed",
              error: message,
            }
          : item,
      ));
      setError(message);
    } finally {
      if (controller.signal.aborted) {
        const pendingIds = new Set(pending.map((item) => item.operationId));
        const message = uploadErrorLabel(new DOMException("Aborted", "AbortError"));
        setItems((currentItems) => currentItems.map((item) =>
          pendingIds.has(item.operationId) &&
              !["completed", "failed", "cancelled"].includes(item.status)
            ? { ...item, status: "cancelled", error: message }
            : item,
        ));
      }
      if (abortRef.current === controller) abortRef.current = null;
      setBusy(false);
    }
  }

  function removeItem(operationId: string) {
    if (busy) return;
    setItems((currentItems) => currentItems.filter(
      (item) => item.operationId !== operationId,
    ));
  }

  return (
    <section
      className="direct-drive-upload-panel"
      role="tabpanel"
      id="audio-source-panel-direct-drive"
      aria-labelledby="audio-source-tab-direct-drive"
    >
      <div>
        <h3>Загрузить исходные файлы без обработки</h3>
        <p className="muted">
          Файлы сохраняются в выбранной папке Google Drive без изменения качества и не запускают транскрибацию.
        </p>
        <details className="technical-details">
          <summary>Как это работает</summary>
          <p className="muted">
            Браузер передаёт исходные bytes напрямую в Google Drive. Studio не создаёт внутреннюю копию и не запускает FFmpeg.
          </p>
        </details>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="direct-drive-workbench">
        <div className="direct-drive-workbench-panel">
          <h4>Исходные файлы</h4>
          <p className="muted">До {DIRECT_DRIVE_UPLOAD_MAX_FILES} файлов, суммарно до 2 ГБ. Названия и содержимое сохраняются.</p>
          <button type="button" onClick={() => fileInput.current?.click()} disabled={busy}>
            Выбрать аудио или видео с устройства
          </button>
          <input
            ref={fileInput}
            hidden
            type="file"
            multiple
            accept="audio/*,video/*,application/ogg,.ogg"
            aria-label="Выбрать файлы для прямой загрузки в Google Drive"
            onChange={(event) => chooseFiles(Array.from(event.target.files || []))}
          />
        </div>
        <div className="direct-drive-workbench-panel">
          <h4>Папка назначения</h4>
          {folder && <p>Папка: <strong>{folder.name}</strong></p>}
          {folderLocked && <p className="muted">Целевая папка зафиксирована для этой операции. Чтобы выбрать другую, начните новый набор файлов.</p>}
          <button type="button" onClick={() => void chooseFolder()} disabled={busy || folderLocked}>
            {folder ? "Изменить целевую папку" : "Выбрать целевую папку"}
          </button>
        </div>
      </div>
      {items.length > 0 && <ol className="direct-drive-upload-list">
        {items.map((item, index) => {
          const loadedBytes = item.status === "completed"
            ? item.file.size
            : Math.min(item.file.size, item.loadedBytes);
          const percent = item.file.size > 0
            ? Math.min(100, Math.round((loadedBytes / item.file.size) * 100))
            : 0;
          return <li key={item.operationId}>
          <span className="audio-order-index" aria-hidden="true">{index + 1}</span>
          <span className="direct-drive-upload-item-copy">
            <strong>{item.file.name}</strong>
            <small>{formatBytes(item.file.size)} · {statusLabel(item)}</small>
            <progress
              aria-label={`Прогресс загрузки ${item.file.name}`}
              max="100"
              value={percent}
            >{percent}%</progress>
            <small>{formatBytes(loadedBytes)} из {formatBytes(item.file.size)} · {percent}%</small>
            {item.error && <small className="error">{item.error}</small>}
          </span>
          <span className="actions">
            {item.webViewUrl && <a
              className="button-like secondary"
              href={item.webViewUrl}
              target="_blank"
              rel="noreferrer"
            >Открыть в Google Drive</a>}
            {["cancelled", "failed"].includes(item.status) && <button
              type="button"
              disabled={busy || !folder}
              onClick={() => void runUploads([item.operationId])}
            >Повторить</button>}
            {item.status !== "completed" && <button
              type="button"
              disabled={busy}
              onClick={() => removeItem(item.operationId)}
            >Убрать</button>}
          </span>
        </li>;
        })}
      </ol>}
      {items.length > 0 && <div className="upload-progress" aria-live="polite">
        <p>
          <strong>{current ? statusLabel(current) : "Состояние загрузки"}</strong>
          {current ? `: ${current.file.name}` : ""}
        </p>
        <progress
          aria-label="Общий прогресс прямой загрузки в Google Drive"
          max="100"
          value={aggregate.percent}
        >{aggregate.percent}%</progress>
        <small>
          {formatBytes(aggregate.loadedBytes)} из {formatBytes(aggregate.totalBytes)} · {aggregate.percent}% · подтверждено {aggregate.completed} из {items.length}
        </small>
        <div className="actions">
          {busy ? <button type="button" onClick={() => abortRef.current?.abort()}>
            Отменить загрузку
          </button> : retryable.length > 0 && <button
            className="primary"
            type="button"
            disabled={!folder}
            onClick={() => void runUploads()}
          >
            {items.some((item) => ["cancelled", "failed"].includes(item.status))
              ? "Повторить незавершённые"
              : "Загрузить в Google Drive"}
          </button>}
        </div>
      </div>}
    </section>
  );
}
