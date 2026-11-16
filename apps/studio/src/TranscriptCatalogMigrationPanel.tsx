import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, api, mutateWithCsrfRetry } from "./apiClient";
import * as googlePicker from "./googlePicker";
import type { PickerSession } from "./googlePicker";
import { googlePickerFailureMessage } from "./googlePickerErrors";
import { ConfirmClearDialog } from "./ConfirmClearDialog";
import {
  cancelLatestRequests,
  LATEST_REQUEST_CANCEL_REASON,
  settleLatestRequest,
} from "./latestRequest";
import {
  googleMaintenanceOauthMessages,
  type GoogleMaintenanceOauthResult,
} from "./googleOauthResult";
import {
  parseTranscriptMaintenanceRun,
  type CatalogImportAction,
  type CatalogImportOutcome,
  type MaintenanceReason,
  type StandardizationAction,
  type StandardizationOutcome,
  type SourceCreationStatus,
  type TranscriptCatalogImportApply,
  type TranscriptCatalogImportDryRun,
  type TranscriptImportStatus,
  type TranscriptMaintenanceApply,
  type TranscriptMaintenanceDryRun,
  type TranscriptMaintenanceRun,
  type TranscriptMaintenanceWorkflow,
  type TranscriptSettingsStatus,
  type TranscriptStandardStatus,
  type TranscriptStandardizationApply,
  type TranscriptStandardizationDryRun,
} from "./transcriptMaintenanceModel";

type BusyState =
  | "target-picker"
  | "dry-run"
  | "apply"
  | null;
type TranscriptMaintenanceSelectionMode =
  | "folder_tree"
  | "single_document";
type SelectedTarget = { id: string; name: string };
type Mutate = <T>(path: string, options: RequestInit) => Promise<T>;
type GoogleOauthStart = { authorization_url: string; expires_at: string };
type GoogleMaintenanceConnection = {
  connected: boolean;
  status: "active" | "revoked" | "incomplete" | null;
  google_email: string | null;
  scopes: string | null;
  connected_at: string | null;
  revoked_at: string | null;
  configured: boolean;
  account_match: boolean;
  scope_ready: boolean;
  ready: boolean;
  reconnect_required: boolean;
};
type MaintenanceAccessStatus = {
  kind:
    | "checking_primary"
    | "primary_disconnected"
    | "primary_reconnect_required"
    | "checking_maintenance"
    | "status_unavailable"
    | "server_not_configured"
    | "maintenance_disconnected"
    | "maintenance_revoked"
    | "maintenance_incomplete"
    | "account_mismatch"
    | "scope_missing"
    | "ready"
    | "invalid_state";
  message: string;
  tone: "notice" | "error";
};

const MAINTENANCE_CONNECTION_REQUEST_TIMEOUT_MS = 15_000;

function parseGoogleMaintenanceConnection(
  candidate: unknown,
): GoogleMaintenanceConnection | null {
  if (!candidate || typeof candidate !== "object") return null;
  const value = candidate as Record<string, unknown>;
  const status = value.status;
  const googleEmail = value.google_email;
  const scopes = value.scopes;
  const connectedAt = value.connected_at;
  const revokedAt = value.revoked_at;
  if (
    typeof value.connected !== "boolean" ||
    (status !== null &&
      status !== "active" &&
      status !== "revoked" &&
      status !== "incomplete") ||
    (googleEmail !== null &&
      (typeof googleEmail !== "string" ||
        googleEmail.trim().length === 0 ||
        googleEmail.length > 320)) ||
    (scopes !== null &&
      (typeof scopes !== "string" ||
        scopes.trim().length === 0 ||
        scopes.length > 2_048)) ||
    !isNullableIsoDate(connectedAt) ||
    !isNullableIsoDate(revokedAt) ||
    typeof value.configured !== "boolean" ||
    typeof value.account_match !== "boolean" ||
    typeof value.scope_ready !== "boolean" ||
    typeof value.ready !== "boolean" ||
    typeof value.reconnect_required !== "boolean" ||
    (value.connected && status !== "active") ||
    (value.ready &&
      (!value.connected ||
        !value.configured ||
        !value.account_match ||
        !value.scope_ready)) ||
    value.reconnect_required !== Boolean(status && !value.ready)
  ) {
    return null;
  }
  return {
    connected: value.connected,
    status,
    google_email: googleEmail,
    scopes,
    connected_at: connectedAt,
    revoked_at: revokedAt,
    configured: value.configured,
    account_match: value.account_match,
    scope_ready: value.scope_ready,
    ready: value.ready,
    reconnect_required: value.reconnect_required,
  };
}

function isNullableIsoDate(value: unknown): value is string | null {
  return (
    value === null ||
    (typeof value === "string" &&
      value.length > 0 &&
      value.length <= 64 &&
      Number.isFinite(Date.parse(value)))
  );
}

async function requestGoogleMaintenanceConnection(signal?: AbortSignal) {
  const candidate = await api<unknown>("/google/maintenance/connection", {
    signal,
    ignoredAbortReason: LATEST_REQUEST_CANCEL_REASON,
  });
  const connection = parseGoogleMaintenanceConnection(candidate);
  if (!connection) throw new Error("invalid_maintenance_connection_response");
  return connection;
}

export function maintenanceAccessStatus({
  googleConnected,
  googleLoading,
  pickerReady,
  maintenanceConnection,
  maintenanceLoading,
  maintenanceReadError,
}: {
  googleConnected: boolean;
  googleLoading: boolean;
  pickerReady: boolean;
  maintenanceConnection: GoogleMaintenanceConnection | null;
  maintenanceLoading: boolean;
  maintenanceReadError: string;
}): MaintenanceAccessStatus {
  if (googleLoading) {
    return {
      kind: "checking_primary",
      message: "Проверяем основное подключение Google Drive…",
      tone: "notice",
    };
  }
  if (!googleConnected) {
    return {
      kind: "primary_disconnected",
      message: "Сначала подключите Google Drive.",
      tone: "error",
    };
  }
  if (!pickerReady) {
    return {
      kind: "primary_reconnect_required",
      message:
        "Обновите подключение Google Drive, чтобы выбирать документы и папки.",
      tone: "error",
    };
  }
  if (maintenanceLoading) {
    return {
      kind: "checking_maintenance",
      message: "Проверяем расширенный доступ к готовым документам…",
      tone: "notice",
    };
  }
  if (maintenanceReadError || !maintenanceConnection) {
    return {
      kind: "status_unavailable",
      message:
        "Не удалось проверить расширенный доступ Google.",
      tone: "error",
    };
  }
  if (!maintenanceConnection.configured) {
    return {
      kind: "server_not_configured",
      message:
        "Расширенный доступ Google пока не настроен в Studio. Обратитесь в поддержку.",
      tone: "error",
    };
  }
  if (maintenanceConnection.status === "revoked") {
    return {
      kind: "maintenance_revoked",
      message: "Расширенный доступ Google отозван. Подключите его заново.",
      tone: "error",
    };
  }
  if (maintenanceConnection.status === "incomplete") {
    return {
      kind: "maintenance_incomplete",
      message:
        "Подключение расширенного доступа не было завершено. Попробуйте заново.",
      tone: "error",
    };
  }
  if (!maintenanceConnection.connected) {
    return {
      kind: "maintenance_disconnected",
      message: "Подключите расширенный доступ Google для готовых документов.",
      tone: "error",
    };
  }
  if (!maintenanceConnection.account_match) {
    return {
      kind: "account_mismatch",
      message:
        "Основное и расширенное подключения принадлежат разным Google-аккаунтам.",
      tone: "error",
    };
  }
  if (!maintenanceConnection.scope_ready) {
    return {
      kind: "scope_missing",
      message:
        "Расширенному доступу не хватает разрешений Google Drive или Google Docs.",
      tone: "error",
    };
  }
  if (maintenanceConnection.ready) {
    return {
      kind: "ready",
      message: maintenanceConnection.google_email
        ? `Расширенный доступ подключён и готов: ${maintenanceConnection.google_email}.`
        : "Расширенный доступ подключён и готов.",
      tone: "notice",
    };
  }
  return {
    kind: "invalid_state",
    message:
      "Не удалось подтвердить состояние расширенного доступа. Обратитесь в поддержку.",
    tone: "error",
  };
}

const STANDARD_LABELS: Record<TranscriptStandardStatus, string> = {
  current: "Актуальный стандарт",
  outdated: "Требует обновления",
  unstructured: "Без структуры",
  unreadable: "Не удалось прочитать",
};
const IMPORT_LABELS: Record<TranscriptImportStatus, string> = {
  not_imported: "Ещё не учтён Studio",
  imported_exact: "Уже учтён Studio",
  conflict: "Конфликт",
};
const SETTINGS_LABELS: Record<TranscriptSettingsStatus, string> = {
  exact: "Настройки определены",
  indeterminate: "Настройки не определены",
};
const SOURCE_CREATION_LABELS: Record<SourceCreationStatus, string> = {
  authoritative: "Подтверждена",
  unavailable: "Не определена",
  conflict: "Конфликт",
};
const STANDARDIZATION_ACTION_LABELS: Record<
  StandardizationAction,
  string
> = {
  standardize_document: "Стандартизировать документ",
  unchanged: "Оставить без изменений",
  blocked: "Заблокировано",
};
const CATALOG_ACTION_LABELS: Record<CatalogImportAction, string> = {
  import_metadata: "Учесть готовый документ",
  unchanged: "Оставить без изменений",
  blocked: "Заблокировано",
};
const STANDARDIZATION_OUTCOME_LABELS: Record<
  StandardizationOutcome,
  string
> = {
  standardized: "Документ обновлён",
  already_current: "Уже актуален",
  blocked: "Заблокировано",
};
const CATALOG_OUTCOME_LABELS: Record<CatalogImportOutcome, string> = {
  imported: "Документ учтён Studio",
  already_applied: "Документ уже был учтён",
  unchanged: "Без изменений",
  blocked: "Заблокировано",
  standardization_required: "Сначала нужна стандартизация",
  conflict: "Конфликт",
};
const REASON_LABELS: Record<MaintenanceReason, string> = {
  catalog_conflict: "Конфликт с существующей записью Studio",
  document_unreadable: "Документ недоступен для чтения",
  standardization_required: "Сначала стандартизируйте документ",
  catalog_metadata_conflict: "Метаданные Studio изменились",
  catalog_document_unavailable:
    "Документ стал недоступен во время применения",
  catalog_document_write_rejected:
    "Google Drive отклонил изменение документа",
  catalog_document_revision_changed:
    "Документ изменился после проверки",
  catalog_document_multiple_tabs:
    "Документ с несколькими вкладками не поддерживается",
  catalog_document_content_unsupported:
    "Структура документа не поддерживается",
  catalog_document_classification_changed:
    "Состояние документа изменилось после проверки",
  catalog_document_empty:
    "Пустой документ нельзя стандартизировать",
  catalog_document_limit_exceeded:
    "Документ слишком большой для безопасной стандартизации",
  catalog_document_response_invalid:
    "Google Docs вернул некорректную структуру документа",
  source_creation_time_unavailable:
    "Нет подтверждённой даты создания исходного файла",
  source_creation_time_conflict:
    "Обнаружен конфликт даты создания исходного файла",
};
const ERROR_MESSAGES: Record<string, string> = {
  catalog_google_connection_missing:
    "Подключите Google Drive перед операцией.",
  catalog_google_connection_inactive:
    "Подключение Google Drive неактивно. Обновите его в настройках.",
  catalog_google_maintenance_connection_missing:
    "Подключите отдельный доступ Google для обслуживания папок.",
  catalog_google_maintenance_connection_inactive:
    "Доступ Google для обслуживания неактивен. Подключите его заново.",
  catalog_google_maintenance_account_mismatch:
    "Подключите для обслуживания тот же Google-аккаунт, что и основной.",
  catalog_google_reauthorization_required:
    "Google Drive требует повторного подключения.",
  catalog_google_scope_unavailable:
    "Текущего разрешения Google Drive недостаточно для операции.",
  catalog_google_config_unavailable:
    "Интеграция Google Drive временно не настроена.",
  catalog_google_token_unavailable:
    "Google Drive временно недоступен. Повторите попытку позже.",
  catalog_folder_unavailable:
    "Выбранная папка недоступна. Выберите её через Google Picker ещё раз.",
  catalog_google_rate_limited:
    "Google Drive ограничил частоту запросов. Повторите попытку позже.",
  catalog_google_unavailable:
    "Google Drive временно недоступен. Повторите попытку позже.",
  catalog_google_timeout:
    "Google Drive не ответил вовремя. Повторите попытку.",
  catalog_google_response_invalid:
    "Google Drive вернул неожиданный ответ. Повторите попытку позже.",
  catalog_scan_incomplete:
    "Google Drive вернул неполный список. Повторите проверку.",
  catalog_scan_limit_exceeded:
    "Выбранная папка слишком большая для одной операции. Выберите более узкую папку.",
  catalog_document_unavailable:
    "Один из документов стал недоступен. Запустите проверку заново.",
  catalog_document_write_rejected:
    "Google Drive отклонил изменение документа.",
  catalog_document_revision_changed:
    "Документ изменился после проверки. Запустите проверку заново.",
  catalog_document_multiple_tabs:
    "Документ с несколькими вкладками нельзя стандартизировать автоматически.",
  catalog_document_content_unsupported:
    "Структура одного из документов не поддерживается.",
  catalog_document_classification_changed:
    "Состояние документа изменилось. Запустите проверку заново.",
  catalog_document_empty:
    "Пустой документ нельзя стандартизировать как транскрипт.",
  catalog_document_limit_exceeded:
    "Один из документов слишком большой для безопасной стандартизации.",
  transcript_folder_invalid: "Выбранная папка некорректна.",
  transcript_document_invalid: "Выбранный документ некорректен.",
  transcript_document_not_google_doc:
    "Выберите документ в формате Google Docs.",
  transcript_document_trashed:
    "Выбранный документ находится в корзине Google Drive.",
  transcript_maintenance_run_in_progress:
    "Для этой операции уже выполняется задача. Дождитесь её завершения.",
  transcript_maintenance_idempotency_conflict:
    "Запрос операции конфликтует с ранее созданной задачей. Обновите страницу.",
  transcript_maintenance_preview_invalid:
    "Предыдущая проверка устарела. Запустите проверку заново.",
  transcript_maintenance_attempts_exhausted:
    "Операция не завершилась после нескольких безопасных попыток. Запустите проверку заново.",
  transcript_maintenance_internal_error:
    "Операция остановлена из-за внутренней ошибки. Повторите проверку; если ошибка повторится, скачайте диагностику.",
};

const OPERATION_COPY = {
  standardization: {
    title: "Привести документы к текущему формату",
    description:
      "Проверяет выбранный Google Doc или папку с подпапками и обновляет только документы со старым оформлением. " +
      "Уже актуальные документы пропускаются, а существующая корректная дата создания сохраняется.",
    applyLabel: "Обновить документы",
    resultTitle: "Документы обновлены",
  },
  catalog_import: {
    title: "Учесть готовые документы в Studio",
    description:
      "Проверяет выбранный Google Doc или папку с подпапками и отмечает в Studio уже готовые актуальные документы. " +
      "Содержимое Google Docs не изменяется.",
    applyLabel: "Учесть документы",
    resultTitle: "Готовые документы учтены",
  },
} as const;

function maintenanceTarget(
  selectionMode: TranscriptMaintenanceSelectionMode,
  target: SelectedTarget,
) {
  const common = {
    target_name: target.name,
    idempotency_key: newIdempotencyKey(),
  };
  return selectionMode === "folder_tree"
    ? { ...common, selection_mode: selectionMode, folder_id: target.id }
    : { ...common, selection_mode: selectionMode, document_id: target.id };
}

function newIdempotencyKey(): string {
  try {
    return crypto.randomUUID().replaceAll("-", "");
  } catch {
    return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`
      .padEnd(16, "0")
      .slice(0, 64);
  }
}

function apiReason(error: unknown): string | null {
  if (!(error instanceof ApiError) || !error.data) return null;
  const payload = error.data;
  if (typeof payload !== "object" || !("detail" in payload)) return null;
  const detail = (payload as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object" || !("reason" in detail)) {
    return null;
  }
  const reason = (detail as { reason?: unknown }).reason;
  return typeof reason === "string" ? reason : null;
}

function maintenanceErrorMessage(error: unknown): string {
  const reason = apiReason(error);
  if (reason && ERROR_MESSAGES[reason]) return ERROR_MESSAGES[reason];
  if (error instanceof ApiError && error.status === 429) return error.message;
  return "Не удалось выполнить операцию. Повторите попытку.";
}

function maintenanceRunErrorMessage(run: TranscriptMaintenanceRun): string {
  const code = run.error?.code;
  if (code && ERROR_MESSAGES[code]) return ERROR_MESSAGES[code];
  return run.error?.retryable
    ? "Операция временно не завершилась. Повторите проверку."
    : "Операция остановлена безопасно. Проверьте доступ и повторите проверку.";
}

function parseLatestRun(value: unknown): TranscriptMaintenanceRun | null {
  if (!value || typeof value !== "object") {
    throw new Error("invalid maintenance latest response");
  }
  const run = (value as { run?: unknown }).run;
  return run === null ? null : parseTranscriptMaintenanceRun(run);
}

const RUN_STAGE_LABELS: Record<
  TranscriptMaintenanceRun["current_stage"],
  string
> = {
  queued: "Ждёт начала обработки",
  authorizing: "Проверяем доступ Google",
  scanning: "Сканируем папки Google Drive",
  inspecting: "Проверяем Google Docs",
  applying: "Применяем подтверждённую операцию",
  completed: "Операция завершена",
  failed: "Операция остановлена",
};

function safeName(value: unknown, fallback: string): string {
  if (typeof value !== "string") return fallback;
  const cleaned = value.trim();
  return cleaned ? cleaned.slice(0, 160) : fallback;
}

function explicitConfirmation(message: string): boolean {
  try {
    return window.confirm(message) === true;
  } catch {
    return false;
  }
}

function actionableCount(result: TranscriptMaintenanceDryRun): number {
  return result.workflow === "standardization"
    ? result.summary.standardize_document_count
    : result.summary.import_metadata_count;
}

function Reason({ reason }: { reason: MaintenanceReason | null }) {
  if (!reason) return null;
  return (
    <span className="error catalog-item-reason">
      {REASON_LABELS[reason]}
    </span>
  );
}

function Summary({
  entries,
}: {
  entries: { label: string; value: number }[];
}) {
  return (
    <dl className="catalog-migration-summary">
      {entries.map((entry) => (
        <div key={entry.label}>
          <dt>{entry.label}</dt>
          <dd>{entry.value}</dd>
        </div>
      ))}
    </dl>
  );
}

const MAINTENANCE_RESULT_PAGE_SIZE = 25;

function MaintenanceItemsTable<T extends { position: number; name: string }>({
  items,
  columns,
  renderCells,
}: {
  items: T[];
  columns: string[];
  renderCells: (item: T) => ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(MAINTENANCE_RESULT_PAGE_SIZE);
  const normalizedQuery = query.trim().toLocaleLowerCase("ru-RU");
  const filteredItems = normalizedQuery
    ? items.filter((item) =>
        item.name.toLocaleLowerCase("ru-RU").includes(normalizedQuery),
      )
    : items;
  const visibleItems = filteredItems.slice(0, visibleCount);

  useEffect(() => {
    setVisibleCount(MAINTENANCE_RESULT_PAGE_SIZE);
  }, [items, normalizedQuery]);

  return (
    <section className="maintenance-result-list" aria-label="Проверенные документы">
      <div className="maintenance-result-list-header">
        <h5>Документы</h5>
        <span className="muted">
          Показано {visibleItems.length} из {filteredItems.length}
        </span>
      </div>
      <label className="maintenance-result-filter">
        Найти документ
        <input
          type="search"
          value={query}
          placeholder="Название документа"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {visibleItems.length > 0 ? (
        <div className="catalog-migration-table-wrap">
          <table className="catalog-migration-table">
            <thead>
              <tr>
                {columns.map((column) => <th key={column}>{column}</th>)}
              </tr>
            </thead>
            <tbody>
              {visibleItems.map((item) => (
                <tr key={item.position}>{renderCells(item)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="notice">Документы с таким названием не найдены.</p>
      )}
      {visibleItems.length < filteredItems.length && (
        <button
          type="button"
          className="secondary maintenance-result-more"
          onClick={() =>
            setVisibleCount((current) =>
              Math.min(current + MAINTENANCE_RESULT_PAGE_SIZE, filteredItems.length),
            )
          }
        >
          Показать ещё {Math.min(
            MAINTENANCE_RESULT_PAGE_SIZE,
            filteredItems.length - visibleItems.length,
          )}
        </button>
      )}
    </section>
  );
}

function SelectionScanDetails({
  result,
  selectionMode,
}: {
  result: TranscriptMaintenanceDryRun;
  selectionMode: TranscriptMaintenanceSelectionMode;
}) {
  const summary = result.selection_summary;
  if (selectionMode === "single_document") {
    return (
      <p className="muted catalog-scan-details">
        Проверен один выбранный Google Doc. Не удалось прочитать документов:{" "}
        {summary.unreadable_document_count}.
      </p>
    );
  }
  return (
    <p className="muted catalog-scan-details">
      Вложенных папок: {summary.nested_folder_count}. Пропущено других файлов:{" "}
      {summary.skipped_non_document_count}. Страниц Drive просканировано:{" "}
      {summary.pages_scanned}. Не удалось прочитать документов:{" "}
      {summary.unreadable_document_count}.
    </p>
  );
}

function StandardizationDryRunResult({
  result,
  selectionMode,
}: {
  result: TranscriptStandardizationDryRun;
  selectionMode: TranscriptMaintenanceSelectionMode;
}) {
  return (
    <>
      <Summary
        entries={[
          {
            label: "Google Docs найдено",
            value: result.selection_summary.google_document_count,
          },
          {
            label: "Будут стандартизированы",
            value: result.summary.standardize_document_count,
          },
          { label: "Без изменений", value: result.summary.unchanged_count },
          { label: "Заблокированы", value: result.summary.blocked_count },
        ]}
      />
      <SelectionScanDetails
        result={result}
        selectionMode={selectionMode}
      />
      <MaintenanceItemsTable
        items={result.items}
        columns={["Документ", "Формат", "Дата источника", "Что произойдёт"]}
        renderCells={(item) => <>
          <td>{item.name}</td>
          <td>{STANDARD_LABELS[item.standard_status]}</td>
          <td>{SOURCE_CREATION_LABELS[item.source_creation_status]}</td>
          <td>
            {STANDARDIZATION_ACTION_LABELS[item.action]}
            <Reason reason={item.reason_code} />
          </td>
        </>}
      />
    </>
  );
}

function CatalogDryRunResult({
  result,
  selectionMode,
}: {
  result: TranscriptCatalogImportDryRun;
  selectionMode: TranscriptMaintenanceSelectionMode;
}) {
  return (
    <>
      <Summary
        entries={[
          {
            label: "Google Docs найдено",
            value: result.selection_summary.google_document_count,
          },
          {
            label: "Будут учтены Studio",
            value: result.summary.import_metadata_count,
          },
          { label: "Без изменений", value: result.summary.unchanged_count },
          { label: "Заблокированы", value: result.summary.blocked_count },
        ]}
      />
      <SelectionScanDetails
        result={result}
        selectionMode={selectionMode}
      />
      <MaintenanceItemsTable
        items={result.items}
        columns={["Документ", "Формат", "Учёт Studio", "Что произойдёт"]}
        renderCells={(item) => <>
          <td>{item.name}</td>
          <td>{STANDARD_LABELS[item.standard_status]}</td>
          <td>
            {IMPORT_LABELS[item.import_status]}
            <span className="muted catalog-settings-status">
              {SETTINGS_LABELS[item.settings_status]}
            </span>
          </td>
          <td>
            {CATALOG_ACTION_LABELS[item.action]}
            <Reason reason={item.reason_code} />
          </td>
        </>}
      />
    </>
  );
}

function DryRunResult({
  result,
  selectionMode,
}: {
  result: TranscriptMaintenanceDryRun;
  selectionMode: TranscriptMaintenanceSelectionMode;
}) {
  const title = OPERATION_COPY[result.workflow].title;
  return (
    <details
      className="catalog-migration-result"
      aria-label={`Результат проверки: ${title}`}
      open
    >
      <summary><strong>План операции</strong></summary>
      {result.workflow === "standardization" ? (
        <StandardizationDryRunResult
          result={result}
          selectionMode={selectionMode}
        />
      ) : (
        <CatalogDryRunResult
          result={result}
          selectionMode={selectionMode}
        />
      )}
    </details>
  );
}

function StandardizationApplyResult({
  result,
}: {
  result: TranscriptStandardizationApply;
}) {
  return (
    <>
      <Summary
        entries={[
          { label: "Стандартизировано", value: result.summary.standardized_count },
          {
            label: "Уже актуальны",
            value: result.summary.already_current_count,
          },
          { label: "Заблокированы", value: result.summary.blocked_count },
        ]}
      />
      <MaintenanceItemsTable
        items={result.items}
        columns={["Документ", "Дата источника", "Действие", "Результат"]}
        renderCells={(item) => <>
          <td>{item.name}</td>
          <td>{SOURCE_CREATION_LABELS[item.source_creation_status]}</td>
          <td>{STANDARDIZATION_ACTION_LABELS[item.action]}</td>
          <td>
            {STANDARDIZATION_OUTCOME_LABELS[item.outcome]}
            <Reason reason={item.reason_code} />
          </td>
        </>}
      />
    </>
  );
}

function CatalogApplyResult({
  result,
}: {
  result: TranscriptCatalogImportApply;
}) {
  const persistedCount =
    result.summary.imported_count + result.summary.already_applied_count;

  return (
    <>
      <Summary
        entries={[
          {
            label: "Учтены Studio",
            value: result.summary.imported_count,
          },
          {
            label: "Уже были учтены",
            value: result.summary.already_applied_count,
          },
          { label: "Без изменений", value: result.summary.unchanged_count },
          {
            label: "Конфликты и блокировки",
            value: result.summary.blocked_count + result.summary.conflict_count,
          },
        ]}
      />
      {persistedCount > 0 && (
        <p className="muted" role="status">
          Результат сохранён в Studio. Повторно применять эту операцию не
          нужно. Новая проверка покажет документы как уже учтённые.
        </p>
      )}
      <MaintenanceItemsTable
        items={result.items}
        columns={["Документ", "Действие", "Результат"]}
        renderCells={(item) => <>
          <td>{item.name}</td>
          <td>{CATALOG_ACTION_LABELS[item.action]}</td>
          <td>
            {CATALOG_OUTCOME_LABELS[item.outcome]}
            <Reason reason={item.reason_code} />
          </td>
        </>}
      />
    </>
  );
}

function ApplyResult({ result }: { result: TranscriptMaintenanceApply }) {
  return (
    <details
      className="catalog-migration-result"
      aria-label={`Результат применения: ${OPERATION_COPY[result.workflow].title}`}
      open
    >
      <summary><strong>{OPERATION_COPY[result.workflow].resultTitle}</strong></summary>
      {result.workflow === "standardization" ? (
        <StandardizationApplyResult result={result} />
      ) : (
        <CatalogApplyResult result={result} />
      )}
    </details>
  );
}

function MaintenanceOperationCard({
  workflow,
  operationReady,
  mutate,
}: {
  workflow: TranscriptMaintenanceWorkflow;
  operationReady: boolean;
  mutate: Mutate;
}) {
  const copy = OPERATION_COPY[workflow];
  const [selectionMode, setSelectionMode] =
    useState<TranscriptMaintenanceSelectionMode>("folder_tree");
  const [selectedTarget, setSelectedTarget] =
    useState<SelectedTarget | null>(null);
  const [dryRun, setDryRun] = useState<TranscriptMaintenanceDryRun | null>(
    null,
  );
  const [applyResult, setApplyResult] =
    useState<TranscriptMaintenanceApply | null>(null);
  const [previewRunId, setPreviewRunId] = useState<string | null>(null);
  const [activeRun, setActiveRun] =
    useState<TranscriptMaintenanceRun | null>(null);
  const [busy, setBusy] = useState<BusyState>(null);
  const [message, setMessage] = useState("");
  const pickerActive = useRef(false);
  const runInProgress =
    activeRun?.status === "queued" || activeRun?.status === "running";

  function acceptRun(run: TranscriptMaintenanceRun) {
    if (run.workflow !== workflow) {
      throw new Error("invalid maintenance run workflow");
    }
    setActiveRun(run);
    setSelectionMode(run.selection_mode);
    setSelectedTarget((current) =>
      current?.name === run.target_name
        ? current
        : { id: "", name: run.target_name },
    );
    if (run.status === "failed") {
      setMessage(maintenanceRunErrorMessage(run));
      setDryRun(null);
      setPreviewRunId(null);
      return;
    }
    setMessage("");
    if (run.status !== "succeeded" || !run.result) return;
    if (run.operation === "dry_run") {
      setDryRun(run.result as TranscriptMaintenanceDryRun);
      setPreviewRunId(run.id);
      setApplyResult(null);
    } else {
      setApplyResult(run.result as TranscriptMaintenanceApply);
      setDryRun(null);
      setPreviewRunId(null);
    }
  }

  useEffect(() => {
    if (!operationReady) return;
    let cancelled = false;
    const controller = new AbortController();
    void api<unknown>(
      `/transcript-maintenance/runs?workflow=${encodeURIComponent(workflow)}`,
      { cache: "no-store", signal: controller.signal },
    ).then(
      (value) => {
        if (cancelled) return;
        const run = parseLatestRun(value);
        if (run) acceptRun(run);
      },
      () => {
        if (!cancelled) {
          setMessage("Не удалось восстановить состояние обслуживания.");
        }
      },
    );
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [operationReady, workflow]);

  useEffect(() => {
    if (!runInProgress || !activeRun) return;
    let cancelled = false;
    let timer = 0;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const value = await api<unknown>(
          `/transcript-maintenance/runs/${activeRun.id}`,
          { cache: "no-store", signal: controller.signal },
        );
        if (cancelled) return;
        const run = parseTranscriptMaintenanceRun(value);
        acceptRun(run);
        if (run.status === "queued" || run.status === "running") {
          timer = window.setTimeout(() => void poll(), 2_000);
        }
      } catch {
        if (!cancelled) {
          setMessage(
            "Не удалось обновить прогресс. Повторяем проверку автоматически…",
          );
          timer = window.setTimeout(() => void poll(), 2_000);
        }
      }
    };
    timer = window.setTimeout(() => void poll(), 1_200);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [activeRun?.id, activeRun?.status, runInProgress]);

  function resetResult() {
    setDryRun(null);
    setApplyResult(null);
    setPreviewRunId(null);
    setActiveRun(null);
  }

  async function pickerSession(): Promise<PickerSession> {
    return mutate<PickerSession>("/google/picker/session", {
      method: "POST",
    });
  }

  function changeSelectionMode(
    nextMode: TranscriptMaintenanceSelectionMode,
  ) {
    if (nextMode === selectionMode) return;
    setSelectionMode(nextMode);
    setSelectedTarget(null);
    setMessage("");
    resetResult();
  }

  async function chooseTarget() {
    if (!operationReady || busy || pickerActive.current || runInProgress) return;
    const returnFocusTo = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    pickerActive.current = true;
    setBusy("target-picker");
    setMessage("");
    try {
      const result = await googlePicker.openGooglePicker(
        selectionMode === "folder_tree"
          ? "transcript-folder"
          : "transcript-document",
        await pickerSession(),
        { returnFocusTo },
      );
      if (result.action === "cancel") return;
      if (result.action === "error") {
        setMessage(result.message);
        return;
      }
      const target = result.docs[0];
      if (!target?.id || result.docs.length !== 1) {
        setMessage(
          selectionMode === "folder_tree"
            ? "Выберите одну папку Google Drive."
            : "Выберите один Google Doc.",
        );
        return;
      }
      setSelectedTarget({
        id: target.id,
        name: safeName(
          target.name,
          selectionMode === "folder_tree"
            ? "Выбранная папка Google Drive"
            : "Выбранный Google Doc",
        ),
      });
      resetResult();
    } catch (error) {
      setMessage(
        googlePickerFailureMessage(error) ??
          "Не удалось открыть Google Picker.",
      );
    } finally {
      pickerActive.current = false;
      setBusy(null);
    }
  }

  async function runDryRun() {
    if (
      !operationReady ||
      !selectedTarget ||
      !selectedTarget.id ||
      busy ||
      runInProgress
    ) {
      return;
    }
    setBusy("dry-run");
    setMessage("");
    resetResult();
    try {
      const raw = await mutate<unknown>(
        `/transcript-maintenance/${workflow === "standardization" ? "standardization" : "catalog-import"}/dry-run`,
        {
          method: "POST",
          body: JSON.stringify(
            maintenanceTarget(selectionMode, selectedTarget),
          ),
        },
      );
      acceptRun(parseTranscriptMaintenanceRun(raw));
    } catch (error) {
      setDryRun(null);
      setMessage(maintenanceErrorMessage(error));
    } finally {
      setBusy(null);
    }
  }

  async function applyOperation() {
    if (
      !operationReady ||
      !selectedTarget ||
      !dryRun ||
      !previewRunId ||
      dryRun.workflow !== workflow ||
      actionableCount(dryRun) === 0 ||
      busy ||
      runInProgress
    ) {
      return;
    }
    if (
      !explicitConfirmation(
        workflow === "standardization"
          ? `Стандартизировать ${actionableCount(dryRun)} выбранных документов? Каталог Studio не изменится.`
          : `Учесть ${actionableCount(dryRun)} готовых документов в Studio? Google Docs не изменятся.`,
      )
    ) {
      return;
    }
    setBusy("apply");
    setMessage("");
    try {
      const raw = await mutate<unknown>(
        `/transcript-maintenance/${workflow === "standardization" ? "standardization" : "catalog-import"}/apply`,
        {
          method: "POST",
          body: JSON.stringify({
            confirm_apply: true,
            preview_run_id: previewRunId,
            idempotency_key: newIdempotencyKey(),
          }),
        },
      );
      acceptRun(parseTranscriptMaintenanceRun(raw));
    } catch (error) {
      setDryRun(null);
      setMessage(maintenanceErrorMessage(error));
    } finally {
      setBusy(null);
    }
  }

  const actionable =
    dryRun && dryRun.workflow === workflow ? actionableCount(dryRun) : 0;

  return (
    <section
      className="card transcript-catalog-migration transcript-maintenance-operation"
      aria-labelledby={`transcript-maintenance-${workflow}-title`}
    >
      <h3 id={`transcript-maintenance-${workflow}-title`}>{copy.title}</h3>
      <p>{copy.description}</p>
      <div className="maintenance-target">
        <p className="muted">
          Сначала выполните проверку — она ничего не изменит. Содержимое
          документов не показывается в браузере.
        </p>
        <label
          htmlFor={`transcript-maintenance-${workflow}-selection-mode`}
        >
          Что обработать
        </label>
        <select
          id={`transcript-maintenance-${workflow}-selection-mode`}
          value={selectionMode}
          disabled={!operationReady || busy !== null || runInProgress}
          onChange={(event) =>
            changeSelectionMode(
              event.target.value as TranscriptMaintenanceSelectionMode,
            )
          }
        >
          <option value="folder_tree">Папка и все подпапки</option>
          <option value="single_document">Один конкретный Google Doc</option>
        </select>
        <div className="actions">
          <button
            type="button"
            disabled={!operationReady || busy !== null || runInProgress}
            onClick={chooseTarget}
          >
            {busy === "target-picker"
              ? "Открываем Google Drive…"
              : selectedTarget
                ? selectionMode === "folder_tree"
                  ? "Сменить папку"
                  : "Сменить документ"
                : selectionMode === "folder_tree"
                  ? "Выбрать папку"
                  : "Выбрать документ"}
          </button>
          <button
            type="button"
            className="primary"
            disabled={
              !operationReady ||
              !selectedTarget ||
              !selectedTarget.id ||
              runInProgress ||
              busy !== null
            }
            onClick={runDryRun}
          >
            {busy === "dry-run" ? "Проверяем…" : "Проверить документы"}
          </button>
        </div>
        {selectedTarget && (
          <p className="folder-status" role="status">
            {selectionMode === "folder_tree" ? (
              <>
                Корневая папка: <b>{selectedTarget.name}</b>. Будут проверены
                Google Docs в ней и всех подпапках.
              </>
            ) : (
              <>
                Выбран документ: <b>{selectedTarget.name}</b>. Будет проверен
                только этот Google Doc.
              </>
            )}
          </p>
        )}
      </div>
      <div className="maintenance-review">
        <h4>Проверка и результат</h4>
        {!message && !runInProgress && !dryRun && !applyResult && (
          <p className="muted">Здесь появятся результаты проверки выбранных документов.</p>
        )}
        {message && (
          <p className="error" role="alert">
            {message}
          </p>
        )}
        {activeRun && runInProgress && (
          <section className="maintenance-run-progress" aria-live="polite">
            <div>
              <strong>{RUN_STAGE_LABELS[activeRun.current_stage]}</strong>
              <span>
                {activeRun.progress.total === null
                  ? activeRun.progress.completed > 0
                    ? `Проверено этапов/страниц: ${activeRun.progress.completed}`
                    : "Операция сохранена и продолжится независимо от страницы"
                  : `${activeRun.progress.completed} из ${activeRun.progress.total}`}
              </span>
            </div>
            <progress
              max={activeRun.progress.total ?? undefined}
              value={
                activeRun.progress.total === null
                  ? undefined
                  : activeRun.progress.completed
              }
            />
          </section>
        )}
        {dryRun && dryRun.workflow === workflow && (
          <DryRunResult
            result={dryRun}
            selectionMode={selectionMode}
          />
        )}
        {dryRun && dryRun.workflow === workflow && (
          <div className="catalog-migration-apply">
            <p>
              {selectionMode === "folder_tree"
                ? "Перед применением Studio заново проверит эту корневую папку и все подпапки."
                : "Перед применением Studio заново проверит именно этот Google Doc."}{" "}
              Эта проверка разрешает применить только выбранную операцию.
            </p>
            <button
              type="button"
              className="primary"
              disabled={
                !operationReady ||
                busy !== null ||
                runInProgress ||
                !previewRunId ||
                actionable === 0
              }
              onClick={applyOperation}
            >
              {busy === "apply"
                ? "Применяем…"
                : `${copy.applyLabel} (${actionable})`}
            </button>
          </div>
        )}
        {applyResult && applyResult.workflow === workflow && (
          <ApplyResult result={applyResult} />
        )}
        {(dryRun || applyResult) && !runInProgress && (
          <button type="button" className="secondary" onClick={resetResult}>
            Закрыть результат
          </button>
        )}
      </div>
    </section>
  );
}

export function TranscriptCatalogMigrationPanel({
  csrf,
  onCsrf,
  googleConnected,
  googleLoading,
  pickerReady,
  maintenanceOauthResult,
  view,
  onOpenWorkspace,
  onOpenConnections,
}: {
  csrf: string;
  onCsrf: (csrf: string) => void;
  googleConnected: boolean;
  googleLoading: boolean;
  pickerReady: boolean;
  maintenanceOauthResult: GoogleMaintenanceOauthResult | null;
  view: "connections" | "workspace";
  onOpenWorkspace?: () => void;
  onOpenConnections?: () => void;
}) {
  useEffect(() => {
    if (view !== "connections") return;
    const reveal = () => {
      if (window.location.hash !== "#google-maintenance-access") return;
      const panel=document.getElementById("google-maintenance-access") as HTMLDetailsElement | null;
      if (panel) { panel.open=true; panel.scrollIntoView?.({block:"start"}); panel.querySelector<HTMLElement>("summary")?.focus(); }
    };
    reveal();
    window.addEventListener("studio:maintenance-access",reveal);
    return () => window.removeEventListener("studio:maintenance-access",reveal);
  }, [view]);
  const mutate: Mutate = <T,>(path: string, options: RequestInit) =>
    mutateWithCsrfRetry<T>(path, csrf, onCsrf, options);
  const [maintenanceConnection, setMaintenanceConnection] =
    useState<GoogleMaintenanceConnection | null>(null);
  const [maintenanceLoading, setMaintenanceLoading] = useState(true);
  const [maintenanceStarting, setMaintenanceStarting] = useState(false);
  const [maintenanceMessage, setMaintenanceMessage] = useState("");
  const [maintenanceReadError, setMaintenanceReadError] = useState("");
  const [clearOpen, setClearOpen] = useState(false);
  const [clearPending, setClearPending] = useState(false);
  const [clearMessage, setClearMessage] = useState("");
  const clearPendingRef = useRef(false);
  const [exportPending, setExportPending] = useState(false);
  const exportPendingRef = useRef(false);
  const [exportMessage, setExportMessage] = useState("");
  const [exportUrl, setExportUrl] = useState("");
  const maintenanceRequestEpochsRef = useRef(new Map<string, number>());
  const maintenanceRequestControllersRef = useRef(
    new Map<string, AbortController>(),
  );

  async function loadMaintenanceConnection() {
    setMaintenanceLoading(true);
    setMaintenanceMessage("");
    setMaintenanceReadError("");
    await settleLatestRequest(
      maintenanceRequestEpochsRef.current,
      "maintenance-connection",
      requestGoogleMaintenanceConnection,
      (connection) => {
        setMaintenanceConnection(connection);
        setMaintenanceLoading(false);
        setMaintenanceReadError("");
      },
      () => {
        setMaintenanceConnection(null);
        setMaintenanceLoading(false);
        setMaintenanceReadError(
          "Не удалось проверить доступ Google для обслуживания.",
        );
      },
      {
        controllers: maintenanceRequestControllersRef.current,
        timeoutMs: MAINTENANCE_CONNECTION_REQUEST_TIMEOUT_MS,
      },
    );
  }

  useEffect(() => {
    if (!googleConnected) {
      cancelLatestRequests(
        maintenanceRequestEpochsRef.current,
        maintenanceRequestControllersRef.current,
      );
      setMaintenanceConnection(null);
      setMaintenanceLoading(false);
      setMaintenanceReadError("");
      return;
    }
    void loadMaintenanceConnection();
    return () =>
      cancelLatestRequests(
        maintenanceRequestEpochsRef.current,
        maintenanceRequestControllersRef.current,
      );
  }, [googleConnected, maintenanceOauthResult]);

  async function connectMaintenance() {
    if (
      maintenanceStarting ||
      !pickerReady ||
      maintenanceConnection?.configured === false
    ) {
      return;
    }
    setMaintenanceStarting(true);
    setMaintenanceMessage("");
    try {
      const result = await mutate<GoogleOauthStart>(
        "/google/maintenance/oauth/start",
        { method: "POST" },
      );
      window.location.assign(result.authorization_url);
    } catch {
      setMaintenanceMessage(
        "Не удалось начать подключение доступа для обслуживания.",
      );
      setMaintenanceStarting(false);
    }
  }

  async function disconnectMaintenance() {
    setMaintenanceMessage("");
    try {
      const connection = await mutate<GoogleMaintenanceConnection>(
        "/google/maintenance/connection",
        { method: "DELETE" },
      );
      setMaintenanceConnection(connection);
    } catch {
      setMaintenanceMessage(
        "Не удалось отключить доступ Google для обслуживания.",
      );
    }
  }

  async function exportManifest() {
    if (exportPendingRef.current || clearPendingRef.current || !pickerReady) return;
    exportPendingRef.current = true;
    setExportPending(true);
    setExportMessage("");
    setExportUrl("");
    const returnFocusTo = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    try {
      const session = await mutate<PickerSession>("/google/picker/session", { method: "POST" });
      const picked = await googlePicker.openGooglePicker("output-folder", session, { returnFocusTo });
      if (picked.action === "cancel") return;
      if (picked.action === "error") throw new Error("picker_unavailable");
      if (picked.docs.length !== 1 || !picked.docs[0]?.id) throw new Error("invalid_folder");
      const result = await mutate<{ ok: boolean; entry_count: number; web_view_url: string }>("/transcript-catalog/export", {
        method: "POST", body: JSON.stringify({ folder_id: picked.docs[0].id }),
      });
      if (result.ok !== true || !Number.isInteger(result.entry_count) || result.entry_count < 0
        || typeof result.web_view_url !== "string" || !/^https:\/\/drive\.google\.com\/file\/d\/[\w-]+(?:\/view)?$/.test(result.web_view_url)) {
        throw new Error("invalid_export_response");
      }
      setExportMessage(`Манифест сохранён в выбранную папку Google Drive. Записей: ${result.entry_count}.`);
      setExportUrl(result.web_view_url);
    } catch {
      setExportMessage("Не удалось сохранить манифест. Проверьте подключение и доступ к папке, затем повторите. Учёт Studio сохранён.");
    } finally {
      exportPendingRef.current = false;
      setExportPending(false);
    }
  }

  async function clearManifest() {
    if (clearPendingRef.current) return;
    clearPendingRef.current = true;
    setClearPending(true);
    setClearMessage("");
    try {
      const result = await mutate<unknown>("/transcript-catalog/clear", {
        method: "POST",
        body: JSON.stringify({ confirm_clear: true }),
      });
      if (!isCatalogClearResponse(result)) {
        throw new Error("invalid_catalog_clear_response");
      }
      setClearOpen(false);
      setClearMessage(
        "Манифест очищен. Результаты, Google Docs и исходные файлы сохранены.",
      );
    } catch {
      setClearMessage("Не удалось очистить манифест. Повторите попытку.");
    } finally {
      clearPendingRef.current = false;
      setClearPending(false);
    }
  }

  const maintenanceReady = maintenanceConnection?.ready === true;
  const operationReady = pickerReady && maintenanceReady;
  const accessStatus = maintenanceAccessStatus({
    googleConnected,
    googleLoading,
    pickerReady,
    maintenanceConnection,
    maintenanceLoading,
    maintenanceReadError,
  });
  const oauthMessage =
    maintenanceOauthResult === "connected"
      ? !maintenanceLoading && maintenanceReady
        ? googleMaintenanceOauthMessages.connected
        : ""
      : maintenanceOauthResult
        ? googleMaintenanceOauthMessages[maintenanceOauthResult]
        : "";

  if (view === "connections") {
    return (
      <section
        className="transcript-maintenance-panel"
        aria-labelledby="transcript-maintenance-access-title"
      >
        <span className="tag">РАСШИРЕННЫЙ ДОСТУП</span>
        <h2 id="transcript-maintenance-access-title">
          Работа с готовыми Google Docs
        </h2>
        <p>
          Подключите отдельный доступ, чтобы проверять и приводить готовые
          документы к текущему формату. Сами действия находятся в разделе
          «Транскрибации → Обслуживание».
        </p>
        <details className="technical-details">
          <summary>Почему нужен отдельный доступ</summary>
          <p>
            Токены хранятся только в защищённой части Studio. Это разрешение используется для
            чтения структуры выбранных Google Docs и явного применения
            подтверждённых изменений.
          </p>
        </details>
        <section className="card transcript-maintenance-access">
          <p
            className={accessStatus.tone}
            role={accessStatus.tone === "error" ? "alert" : "status"}
            data-maintenance-state={accessStatus.kind}
          >
            {accessStatus.message}
          </p>
          {oauthMessage && (
            <p className="notice" role="status">
              {oauthMessage}
            </p>
          )}
          <div className="actions">
            {!maintenanceReady && (
              <button
                type="button"
                className="primary"
                disabled={
                  maintenanceLoading ||
                  maintenanceStarting ||
                  !maintenanceConnection ||
                  !pickerReady ||
                  maintenanceConnection?.configured === false
                }
                onClick={connectMaintenance}
              >
                {maintenanceStarting
                  ? "Открываем Google…"
                  : maintenanceConnection?.reconnect_required
                    ? "Переподключить доступ"
                    : "Подключить доступ"}
              </button>
            )}
            {maintenanceConnection?.connected && (
              <button type="button" onClick={disconnectMaintenance}>
                Отключить доступ
              </button>
            )}
            {maintenanceReady && onOpenWorkspace && (
              <button
                type="button"
                className="primary"
                onClick={onOpenWorkspace}
              >
                Перейти к обслуживанию
              </button>
            )}
          </div>
          {maintenanceReadError && (
            <div className="error">
              <button
                type="button"
                className="secondary"
                disabled={maintenanceLoading}
                onClick={() => void loadMaintenanceConnection()}
              >
                Повторить проверку доступа
              </button>
            </div>
          )}
          {maintenanceMessage && (
            <p className="error" role="alert">
              {maintenanceMessage}
            </p>
          )}
        </section>
      </section>
    );
  }

  return (
    <section
      className="transcript-maintenance-panel"
      aria-labelledby="transcript-maintenance-title"
    >
      <span className="tag">ПОДГОТОВКА ДОКУМЕНТОВ</span>
      <h2 id="transcript-maintenance-title">
        Проверка и обновление Google Docs
      </h2>
      <p>
        Выберите один документ или папку с подпапками. Сначала Studio покажет,
        что изменится, и только затем предложит отдельное подтверждение.
      </p>
      <details className="technical-details">
        <summary>Чем отличаются операции</summary>
        <p>
          Обновление формата изменяет только подходящие Google Docs. Учёт
          готовых документов сохраняет только служебные metadata Studio и не
          изменяет содержимое Google Docs. Проверка и подтверждение у операций
          независимы.
        </p>
      </details>
      <div className={accessStatus.tone} role={accessStatus.tone === "error" ? "alert" : "status"}>
        <p>{accessStatus.message}</p>
        {!operationReady && onOpenConnections && (
          <button type="button" className="secondary" onClick={onOpenConnections}>
            Настроить доступ Google
          </button>
        )}
      </div>
      <details className="card transcript-maintenance-access technical-details">
        <summary className="summary-row">Расширенные действия</summary>
        <h3>Сохранить манифест</h3>
        <p>Сохраните JSON со связями исходников, настройками и готовыми документами в выбранную папку Google Drive. Текст транскрипций и ключи в файл не входят.</p>
        <button type="button" disabled={!pickerReady || exportPending || clearPending} onClick={() => void exportManifest()}>
          {exportPending ? "Сохраняем манифест…" : "Сохранить манифест в Google Drive"}
        </button>
        {exportMessage && <p role="status">{exportMessage}</p>}
        {exportUrl && <a href={exportUrl} target="_blank" rel="noopener noreferrer">Открыть сохранённый манифест</a>}
        <h3>Сбросить учёт готовых документов</h3>
        <p>
          Сброс удаляет только историю защиты от повторной обработки. Google
          Docs, результаты, исходные файлы, задачи и журнал действий сохранятся.
        </p>
        <button
          type="button"
          className="danger"
          disabled={clearPending || exportPending}
          onClick={() => setClearOpen(true)}
        >
          Сбросить учёт
        </button>
        {clearMessage && (
          <p role="status" className="notice">{clearMessage}</p>
        )}
      </details>
      <div className="transcript-maintenance-grid">
        <MaintenanceOperationCard
          workflow="standardization"
          operationReady={operationReady}
          mutate={mutate}
        />
        <MaintenanceOperationCard
          workflow="catalog_import"
          operationReady={operationReady}
          mutate={mutate}
        />
      </div>
      {clearOpen && (
        <ConfirmClearDialog
          title="Сбросить учёт готовых документов?"
          description="Ранее учтённые результаты перестанут защищать от повторной транскрибации. Google Docs, результаты, исходные файлы, задачи и журнал действий не удаляются."
          pending={clearPending}
          onConfirm={() => void clearManifest()}
          onCancel={() => setClearOpen(false)}
        />
      )}
    </section>
  );
}

function isCatalogClearResponse(value: unknown): value is {
  ok: true;
  reset_at: string;
  hidden_evidence_count: number;
} {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.ok === true &&
    typeof candidate.reset_at === "string" &&
    Number.isFinite(Date.parse(candidate.reset_at)) &&
    typeof candidate.hidden_evidence_count === "number" &&
    Number.isInteger(candidate.hidden_evidence_count) &&
    candidate.hidden_evidence_count >= 0
  );
}
