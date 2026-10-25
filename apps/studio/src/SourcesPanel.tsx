import { useEffect, useRef, useState } from "react";

import { ApiError, api, mutateWithCsrfRetry } from "./apiClient";
import { runBoundedRequest } from "./jobMutationRequest";
import { formatBytes, formatTime } from "./formatters";
import { isSafeDisplayUrl, ResourceExternalLink } from "./resourceLinks";
import {
  isUsableJobSource,
  sourceСтатусLabel,
  unusableJobSourceReason,
  type Source,
} from "./sourceModel";

type SourcesState = {
  loading: boolean;
  loadingMore: boolean;
  error: string;
  loaded: boolean;
  items: Source[];
  nextCursor: string | null;
};

export type SourceDeletionNotice = {
  projectId: string;
  sourceId: string;
  message: string;
  tone: "notice" | "error";
};

type SourceDeletionResponse = {
  ok: boolean;
  source_state?: string;
  storage_cleanup?: "not_applicable" | "pending" | "completed";
};

type BulkSourceDeletionPreview = {
  selection_ids?: string[];
  preview_token: string;
  eligible_count: number;
  listed_count: number;
  hidden_expired_count: number;
  eligible_bytes: number;
  eligible_unknown_size_count: number;
  blocked_count: number;
  blocked_bytes: number;
  blocked_unknown_size_count: number;
  blocked_reasons: Record<string, number>;
  google_drive_files_deleted: 0;
};

type BulkSourceDeletionResponse = {
  ok: true;
  deleted_count: number;
  blocked_count: number;
  blocked_reasons: Record<string, number>;
  cleanup_counts: Record<string, number>;
  google_drive_files_deleted: 0;
};

const bulkBlockerLabels: Record<string, string> = {
  queued_job_uses_source: "используются ожидающей задачей",
  processing_job_uses_source: "используются текущей обработкой",
  retryable_failed_job_uses_source: "нужны для безопасного повтора",
  audio_preparation_uses_source: "используются подготовкой аудио",
  unsupported_source_state: "имеют неподдерживаемое состояние",
};

function isExpectedDeletionResponse(
  value: SourceDeletionResponse,
  source: Source,
) {
  return (
    value.ok === true &&
    value.source_state === "deleted" &&
    (source.source_type === "google_drive" || source.source_type === "yandex_disk"
      ? value.storage_cleanup === "not_applicable"
      : value.storage_cleanup === "pending" ||
        value.storage_cleanup === "completed")
  );
}

function isAmbiguousDeletionFailure(error: unknown) {
  return (
    error instanceof TypeError ||
    (error instanceof ApiError && (error.status === 408 || error.status >= 500))
  );
}

function apiErrorDetailReason(error: unknown) {
  if (!(error instanceof ApiError) || !error.data || typeof error.data !== "object") {
    return null;
  }
  const detail = (error.data as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return null;
  const reason = (detail as { reason?: unknown }).reason;
  return typeof reason === "string" ? reason : null;
}

function sourceReadConfirmsDeletion(value: unknown, sourceId: string) {
  return (
    Boolean(value) &&
    typeof value === "object" &&
    (value as { id?: unknown }).id === sourceId &&
    (value as { upload_status?: unknown }).upload_status === "deleted" &&
    typeof (value as { deleted_at?: unknown }).deleted_at === "string"
  );
}

function safeConfirm(message: string) {
  try {
    return window.confirm(message) !== false;
  } catch {
    return false;
  }
}

export function SourcesPanel({
  project,
  csrf,
  onCsrf,
  sources,
  onReload,
  onLoadMore,
  onSourceRemoved,
  pendingDeletionIds,
  deletionNotices,
  beginDeletion,
  finishDeletion,
}: {
  project: { id: string; title: string };
  csrf: string;
  onCsrf: (csrf: string) => void;
  sources: SourcesState;
  onReload: (projectId: string) => void;
  onLoadMore: (projectId: string, cursor: string) => void;
  onSourceRemoved?: (
    source: Source,
    storageCleanup?: SourceDeletionResponse["storage_cleanup"],
  ) => void;
  pendingDeletionIds: ReadonlySet<string>;
  deletionNotices: Readonly<Record<string, SourceDeletionNotice>>;
  beginDeletion: (sourceId: string) => boolean;
  finishDeletion: (
    sourceId: string,
    notice: SourceDeletionNotice,
  ) => void;
}) {
  const [bulkPreview, setBulkPreview] = useState<BulkSourceDeletionPreview | null>(null);
  const [bulkPending, setBulkPending] = useState(false);
  const [bulkMessage, setBulkMessage] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkTargetIds, setBulkTargetIds] = useState<string[] | null>(null);
  const activeProject = useRef(project.id);
  activeProject.current = project.id;
  useEffect(() => { setSelectedIds(new Set()); setBulkTargetIds(null); setBulkPreview(null); setBulkMessage(""); }, [project.id]);
  const selectedSources = sources.items.filter((source) => selectedIds.has(source.id));

  async function previewBulkDeletion(selection: string[] | null = null) {
    if (bulkPending) return;
    const projectId = project.id;
    setBulkPending(true);
    setBulkTargetIds(selection);
    setBulkMessage("");
    try {
      const bounded = await runBoundedRequest((signal) => api<BulkSourceDeletionPreview>(
        `/projects/${project.id}/sources/bulk-deletion/preview${selection ? `?${new URLSearchParams(selection.map((id) => ["source_ids", id]))}` : ""}`,
        { cache: "no-store", signal },
      ));
      if (activeProject.current !== projectId) return;
      if (bounded.status === "timed_out") throw new Error("bulk_preview_timeout");
      const value = bounded.value;
      if (selection && (!Array.isArray(value?.selection_ids) ||
        JSON.stringify([...selection].sort()) !== JSON.stringify(value.selection_ids))) {
        throw new Error("unconfirmed_selection");
      }
      if (
        !value ||
        !/^[a-f0-9]{64}$/.test(value.preview_token) ||
        !Number.isInteger(value.eligible_count) ||
        !Number.isInteger(value.listed_count) ||
        !Number.isInteger(value.hidden_expired_count) ||
        !Number.isInteger(value.blocked_count) ||
        value.listed_count + value.hidden_expired_count !== value.eligible_count + value.blocked_count ||
        value.google_drive_files_deleted !== 0
      ) {
        throw new Error("invalid_bulk_preview");
      }
      setBulkPreview(value);
    } catch (error) {
      if (activeProject.current === projectId) setBulkMessage(error instanceof Error && error.message === "unconfirmed_selection"
        ? "Studio не подтвердила выбранные файлы. Обновите приложение и повторите проверку. Ничего не удалено."
        : "Не удалось подготовить безопасный план очистки.");
    } finally {
      setBulkPending(false);
    }
  }

  async function applyBulkDeletion() {
    if (!bulkPreview || bulkPending || bulkPreview.eligible_count === 0) return;
    const projectId = project.id;
    setBulkPending(true);
    setBulkMessage("");
    try {
      const bounded = await runBoundedRequest((signal) => mutateWithCsrfRetry<BulkSourceDeletionResponse>(
        `/projects/${project.id}/sources/bulk-deletion`,
        csrf,
        onCsrf,
        {
          method: "POST",
          signal,
          body: JSON.stringify({
            confirm_delete: true,
            expected_preview_token: bulkPreview.preview_token,
            expected_eligible_count: bulkPreview.eligible_count,
            expected_blocked_count: bulkPreview.blocked_count,
            ...(bulkTargetIds ? { source_ids: bulkTargetIds } : {}),
          }),
        },
      ));
      if (bounded.status === "timed_out") throw new Error("bulk_deletion_unconfirmed");
      if (activeProject.current !== projectId) return;
      const value = bounded.value;
      if (!value || value.ok !== true || value.google_drive_files_deleted !== 0) {
        throw new Error("invalid_bulk_result");
      }
      setBulkPreview(null);
      setBulkMessage(
        `Из Studio убрано файлов: ${value.deleted_count}. Пропущено: ${value.blocked_count}. Файлы Google Drive не удалялись.`,
      );
      onReload(project.id);
    } catch (error) {
      if (activeProject.current !== projectId) return;
      if (apiErrorDetailReason(error) === "recent_reauthentication_required") {
        setBulkMessage(
          "Сначала подтвердите личность в разделе «Аккаунт», затем повторите очистку.",
        );
      } else if (error instanceof ApiError && error.status === 401) {
        setBulkMessage("Для очистки войдите в аккаунт заново и повторите проверку.");
      } else if (error instanceof ApiError && error.status === 409) {
        setBulkPreview(null);
        setBulkMessage(bulkTargetIds ? "Состояние выбранных файлов изменилось. Проверьте выбор и нажмите «Убрать выбранные», чтобы получить новый план." : "Состояние файлов изменилось. Нажмите «Очистить все файлы», чтобы проверить новый план.");
      } else {
        setBulkPreview(null);
        setBulkMessage("Studio не подтвердила массовую очистку. Обновите список и повторите проверку.");
        onReload(project.id);
      }
    } finally {
      setBulkPending(false);
    }
  }
  function confirmedDeletionMessage(
    source: Source,
    storageCleanup?: SourceDeletionResponse["storage_cleanup"],
  ) {
    if (storageCleanup === "pending") {
      return source.upload_status === "pending"
        ? "Файл убран из Studio. Временная копия поставлена в очередь на удаление после завершения окна загрузки."
        : "Файл убран из Studio. Временная копия поставлена в очередь фонового удаления; выбранный срок хранения ждать не нужно.";
    }
    return storageCleanup === "completed"
      ? "Файл убран из Studio. Временная копия уже удалена из хранилища."
      : "Файл убран из Studio.";
  }

  function applyConfirmedDeletion(
    source: Source,
    storageCleanup?: SourceDeletionResponse["storage_cleanup"],
  ) {
    onSourceRemoved?.(source, storageCleanup);
  }

  async function reconcileAmbiguousDeletion(source: Source) {
    try {
      const result = await runBoundedRequest((signal) =>
        api<unknown>(`/sources/${source.id}`, {
          signal,
          cache: "no-store",
        }),
      );
      if (
        result.status === "completed" &&
        sourceReadConfirmsDeletion(result.value, source.id)
      ) {
        applyConfirmedDeletion(source);
        return true;
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        applyConfirmedDeletion(source);
        return true;
      }
      // The predefined ambiguous outcome below remains authoritative.
    }
    onReload(project.id);
    return false;
  }

  async function deleteSource(id: string) {
    const source = sources.items.find((item) => item.id === id);
    if (!source || pendingDeletionIds.has(id)) return false;
    const message =
      source.source_type === "google_drive"
        ? "Источник будет убран только из Studio. Файл останется на Google Drive."
        : "Источник будет убран из Studio. Временная копия будет удалена из хранилища после безопасной проверки связанных задач.";
    if (!safeConfirm(`${message} Старые неудачные задачи сохранятся в истории, но повтор с этим источником станет недоступен.`) || !beginDeletion(id)) return false;
    let notice: SourceDeletionNotice | null = null;
    try {
      const bounded = await runBoundedRequest((signal) =>
        mutateWithCsrfRetry<SourceDeletionResponse>(
          `/sources/${id}`,
          csrf,
          onCsrf,
          { method: "DELETE", signal },
        ),
      );
      if (bounded.status === "timed_out") {
        const confirmed = await reconcileAmbiguousDeletion(source);
        notice = {
          projectId: project.id,
          sourceId: id,
          message: confirmed
            ? "Файл убран из Studio."
            : "Studio не подтвердила удаление файла. Список обновлён; подождите и повторите при необходимости.",
          tone: confirmed ? "notice" : "error",
        };
        return confirmed;
      }
      const result = bounded.value;
      if (!isExpectedDeletionResponse(result, source)) {
        onReload(project.id);
        notice = {
          projectId: project.id,
          sourceId: id,
          message:
            "Studio вернула несогласованное подтверждение удаления. Список файлов обновлён.",
          tone: "error",
        };
        return false;
      }
      applyConfirmedDeletion(source, result.storage_cleanup);
      notice = {
        projectId: project.id,
        sourceId: id,
        message: confirmedDeletionMessage(source, result.storage_cleanup),
        tone: "notice",
      };
    } catch (error) {
      if (isAmbiguousDeletionFailure(error)) {
        const confirmed = await reconcileAmbiguousDeletion(source);
        notice = {
          projectId: project.id,
          sourceId: id,
          message: confirmed
            ? "Файл убран из Studio."
            : "Studio не подтвердила удаление файла. Список обновлён; подождите и повторите при необходимости.",
          tone: confirmed ? "notice" : "error",
        };
        return confirmed;
      }
      const detail =
        error instanceof ApiError &&
        error.data &&
        typeof error.data === "object" &&
        "detail" in error.data
          ? (error.data as { detail?: unknown }).detail
          : null;
      const reason =
        detail && typeof detail === "object" && "reason" in detail
          ? (detail as { reason?: string }).reason
          : null;
      const messages: Record<string, string> = {
        queued_job_uses_source:
          "Сначала отмените ожидающие задачи, использующие этот файл.",
        processing_job_uses_source:
          "Дождитесь завершения или отмены текущей обработки.",
        retryable_failed_job_uses_source:
          "Источник нужен для доступного безопасного повтора задачи.",
        audio_preparation_uses_source:
          "Сначала завершите или отмените подготовку аудио, использующую этот файл.",
      };
      notice = {
        projectId: project.id,
        sourceId: id,
        message:
          reason && messages[reason]
            ? messages[reason]
            : "Не удалось убрать файл из Studio.",
        tone: "error",
      };
    } finally {
      finishDeletion(
        id,
        notice ?? {
          projectId: project.id,
          sourceId: id,
          message: "Не удалось убрать файл из Studio.",
          tone: "error",
        },
      );
    }
    return notice?.tone === "notice";
  }
  return (
    <section className="sources" aria-label="Сохранённые файлы Studio">
      <div className="split">
        <h3>Сохранённые файлы Studio</h3>
        <button
          type="button"
          className="danger"
          disabled={bulkPending || Boolean(bulkPreview)}
          aria-busy={bulkPending || undefined}
          onClick={() => void previewBulkDeletion()}
        >
          {bulkPending ? "Проверяем…" : "Очистить все файлы"}
        </button>
      </div>
      {sources.items.length > 0 && <div className="bulk-selection-actions" aria-label="Выбор файлов">
        <button type="button" disabled={bulkPending || Boolean(bulkPreview)} onClick={() => setSelectedIds(new Set(sources.items.slice(0,50).map((source) => source.id)))}>Выбрать загруженные файлы (до 50)</button>
        {selectedSources.length > 0 && <><span>Выбрано: {selectedSources.length}</span><button className="danger" type="button" disabled={bulkPending || Boolean(bulkPreview) || pendingDeletionIds.size > 0} onClick={() => void previewBulkDeletion(selectedSources.map((source) => source.id))}>{`Убрать выбранные (${selectedSources.length})`}</button><button type="button" disabled={bulkPending || Boolean(bulkPreview)} onClick={() => setSelectedIds(new Set())}>Снять выбор</button></>}
      </div>}
      {bulkMessage && <p className="notice" role="status">{bulkMessage}</p>}
      {bulkPreview && (
        <section className="bulk-deletion-preview" aria-label="План очистки файлов Studio">
          <h4>{bulkTargetIds ? "План очистки выбранных файлов" : "План очистки"}</h4>
          <p>
            Сейчас в списке файлов: <b>{bulkPreview.listed_count}</b>.
            {bulkPreview.hidden_expired_count > 0
              ? <> Истёкших записей, скрытых после окончания срока хранения: <b>{bulkPreview.hidden_expired_count}</b>.</>
              : ""}
          </p>
          <p>
            К окончательной очистке готовы записи Studio: <b>{bulkPreview.eligible_count}</b> · известный размер исходных файлов {formatBytes(bulkPreview.eligible_bytes)}.
            {bulkPreview.eligible_unknown_size_count > 0
              ? ` Без размера: ${bulkPreview.eligible_unknown_size_count}.`
              : ""}
          </p>
          <p>
            Будут пропущены: <b>{bulkPreview.blocked_count}</b> · известный объём {formatBytes(bulkPreview.blocked_bytes)}.
          </p>
          {Object.keys(bulkPreview.blocked_reasons).length > 0 && (
            <ul>
              {Object.entries(bulkPreview.blocked_reasons).map(([reason, count]) => (
                <li key={reason}>{bulkBlockerLabels[reason] ?? "нельзя безопасно удалить"}: {count}</li>
              ))}
            </ul>
          )}
          <p className="notice">
            Удаляются только записи и оставшиеся временные копии Studio. Исходные файлы Google Drive останутся на месте.
            Старые неудачные задачи сохранятся в истории, но повтор с удалёнными источниками станет недоступен.
          </p>
          <div className="actions">
            <button
              type="button"
              className="danger"
              disabled={bulkPending || bulkPreview.eligible_count === 0}
              onClick={() => void applyBulkDeletion()}
            >
              Подтвердить очистку ({bulkPreview.eligible_count})
            </button>
            <button type="button" className="secondary" disabled={bulkPending} onClick={() => setBulkPreview(null)}>
              Отмена
            </button>
          </div>
        </section>
      )}
      {Object.values(deletionNotices)
        .filter((notice) => notice.projectId === project.id)
        .map((notice) => (
          <p
            key={notice.sourceId}
            className={notice.tone}
            role="status"
          >
            {notice.message}
          </p>
        ))}
      {sources.loading && <p role="status">Загрузка файлов…</p>}
      {sources.error && <p className="error">{sources.error}</p>}
      {sources.loaded && !sources.loading && sources.items.length === 0 && (
        <div><p className="notice">Источники пока не добавлены.</p><button type="button" onClick={() => window.dispatchEvent(new Event("studio:navigate-audio"))}>Добавить файлы для обработки</button></div>
      )}
      {sources.items.map((source) => (
        <article className="source-card" key={source.id}>
          <label className="check-row"><input type="checkbox" aria-label={`Выбрать файл: ${source.original_filename}`} disabled={bulkPending || Boolean(bulkPreview) || pendingDeletionIds.has(source.id) || (!selectedIds.has(source.id) && selectedSources.length >= 50)} checked={selectedIds.has(source.id)} onChange={(event) => setSelectedIds((current) => {const next=new Set(current);if(event.target.checked)next.add(source.id);else next.delete(source.id);return next;})} />Выбрать</label>
          <b>{source.original_filename}</b>
          <span>
            {source.source_type === "google_drive"
              ? "Google Drive"
              : source.source_type === "yandex_disk" ? "Яндекс Диск" : "С устройства"}
          </span>
          <span>Статус: {sourceСтатусLabel(source.upload_status)}</span>
          {!isUsableJobSource(source) && (
            <span>{unusableJobSourceReason(source)}</span>
          )}
          <span>Размер: {formatBytes(source.size_bytes)}</span>
          <span>
            Создан исходный файл: {source.source_created_at
              ? formatTime(source.source_created_at)
              : "не удалось определить"}
          </span>
          {source.source_type === "local_upload" && source.expires_at && (
            <span>Хранится до: {formatTime(source.expires_at)}</span>
          )}
          <div className="resource-actions">
            {isSafeDisplayUrl(source.drive_file_url) && (
              <ResourceExternalLink
                href={source.drive_file_url ?? ""}
                label={source.source_type === "yandex_disk" ? "Открыть файл на Яндекс Диске" : "Открыть файл в Google Drive"}
                ariaLabel={source.source_type === "yandex_disk" ? "Открыть файл на Яндекс Диске в новой вкладке" : "Открыть файл в Google Drive в новой вкладке"}
              />
            )}
            <div className="source-removal-note">
              {source.source_type === "google_drive"
                ? "Файл останется на Google Drive."
                : source.source_type === "yandex_disk" ? "Файл останется на Яндекс Диске." : "Временную копию удалит фоновая очистка Studio."}
            </div>
            <button
              type="button"
              onClick={() => deleteSource(source.id)}
              aria-label={`Убрать из Studio: ${source.original_filename}`}
              disabled={pendingDeletionIds.has(source.id) || bulkPending || Boolean(bulkPreview)}
              aria-busy={pendingDeletionIds.has(source.id)}
            >
              {pendingDeletionIds.has(source.id)
                ? "Удаление…"
                : "Убрать из Studio"}
            </button>
          </div>
          <details>
            <summary>Технические сведения</summary>
            <span>MIME: {source.mime_type || "не указан"}</span>
            <span>Загружен: {formatTime(source.uploaded_at)}</span>
            <span>Истекает: {formatTime(source.expires_at)}</span>
            <span>Удалён: {formatTime(source.deleted_at)}</span>
            {source.delete_reason && (
              <span>Причина: {source.delete_reason}</span>
            )}
          </details>
        </article>
      ))}
      {sources.nextCursor && (
        <button
          type="button"
          className="secondary"
          disabled={sources.loadingMore}
          onClick={() => onLoadMore(project.id, sources.nextCursor ?? "")}
        >
          {sources.loadingMore
            ? "Загружаем файлы…"
            : "Показать ещё файлы"}
        </button>
      )}
      <p className="notice">
        Этот раздел предназначен для просмотра безопасных метаданных и удаления
        файлов из Studio. Исходные файлы Google Drive и Яндекс Диска при этом не удаляются.
      </p>
    </section>
  );
}
