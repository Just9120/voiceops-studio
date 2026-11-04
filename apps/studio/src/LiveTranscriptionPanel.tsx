import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, mutateWithCsrfRetry } from "./apiClient";
import { RealtimeSessionHistory } from "./RealtimeSessionHistory";
import { ConfirmClearDialog } from "./ConfirmClearDialog";
import {
  requestCredentialCollection,
  type Credential,
} from "./credentialContracts";
import {
  cancelLatestRequests,
  settleLatestRequest,
} from "./latestRequest";
import {
  RealtimeSessionController,
  type RealtimeSessionStatus,
} from "./realtimeSession";
import type { TranscriptionLanguageMode } from "./jobModel";
import {
  JOB_MUTATION_TIMEOUT_REASON,
  runBoundedRequest,
} from "./jobMutationRequest";
import {
  REALTIME_PARTIAL_CHECKPOINT_DEBOUNCE_MS,
  deleteLocalRealtimeDraft,
  loadLocalRealtimeDraft,
  makeRealtimeDraft,
  newestRealtimeDraft,
  newRealtimeClientSessionId,
  parseLatestRealtimeDraftResponse,
  realtimeDraftDownloadText,
  realtimeTranscriptText,
  saveLocalRealtimeDraft,
  type RealtimeDraft,
} from "./realtimeDrafts";
import {
  REALTIME_CAPTION_CHANNEL,
  deliverRealtimeConsumer,
  makeRealtimeCaptionMessage,
} from "./realtimeConsumers";
import {
  requestSttProviderCatalog,
  type SttProviderCapability,
} from "./sttContracts";
import {
  exportLiveTranscript,
  LIVE_EXPORT_FORMATS,
  timedExportUnavailable,
  liveExportSelection,
  liveExportSessions,
  upsertLiveSegment,
  type LiveExportFormat,
  type LiveExportInput,
  type RealtimeSegmentMetadata,
} from "./realtimeTranscript";

type Props = {
  ownerUserId: string;
  projectId: string;
  csrf: string;
  onCsrf: (csrf: string) => void;
  active: boolean;
  initialSegments?: string[];
  onSegmentsChange?: (segments: string[]) => void;
};

const STATUS_LABELS: Omit<Record<RealtimeSessionStatus, string>, "connecting"> = {
  ready: "Готово к запуску",
  requesting_permission: "Ожидаем разрешение браузера",
  reconnecting: "Восстанавливаем соединение · Live-сессия продолжается",
  connected: "Соединение установлено",
  transcribing: "Распознаём речь",
  stopping: "Завершаем сессию",
  stopped: "Остановлено",
  closed: "Соединение закрыто",
};

const FAILURE_MESSAGES: Record<string, string> = {
  provider_authentication_rejected:
    "ElevenLabs отклонил основной ключ. Обновите профиль в настройках.",
  provider_request_rejected:
    "ElevenLabs отклонил запрос одноразового доступа.",
  provider_rate_limited:
    "ElevenLabs временно ограничил новые realtime-сессии. Повторите позже.",
  provider_timeout: "ElevenLabs не ответил вовремя. Повторите запуск.",
  provider_unavailable: "ElevenLabs временно недоступен. Повторите запуск.",
  malformed_provider_response:
    "ElevenLabs вернул некорректный одноразовый доступ.",
};

const CREDENTIAL_REQUEST_TIMEOUT_MS = 15_000;
const REALTIME_DRAFT_REQUEST_TIMEOUT_MS = 15_000;

function capabilityFailureMessage(
  error: unknown,
  provider: "elevenlabs" | "yandex",
) {
  const providerName = provider === "yandex" ? "Yandex SpeechKit" : "ElevenLabs";
  if (!(error instanceof ApiError) || !error.data) {
    return error instanceof Error
      ? error.message
      : "Не удалось подготовить realtime-сессию.";
  }
  const data = error.data as { detail?: { reason?: unknown } };
  const reason = data.detail?.reason;
  return typeof reason === "string" && FAILURE_MESSAGES[reason]
    ? FAILURE_MESSAGES[reason].replaceAll("ElevenLabs", providerName)
    : error.message;
}

function credentialLabel(credential: Credential) {
  return credential.active_version
    ? `${credential.label} · v${credential.active_version}`
    : credential.label;
}

function formatElapsed(totalSeconds: number) {
  const bounded = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(bounded / 3600);
  const minutes = Math.floor((bounded % 3600) / 60);
  const seconds = bounded % 60;
  const minuteSecond = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return hours > 0
    ? `${String(hours).padStart(2, "0")}:${minuteSecond}`
    : minuteSecond;
}

function segmentsArePrefix(prefix: string[], candidate: string[]) {
  return (
    prefix.length <= candidate.length &&
    prefix.every((segment, index) => segment === candidate[index])
  );
}

function transcriptFilename(format: LiveExportFormat = "txt", now = new Date()) {
  const timestamp = now
    .toISOString()
    .replace(/\.\d{3}Z$/, "Z")
    .replace(/[:T]/g, "-");
  return `studio-live-transcript-${timestamp}.${format}`;
}

export function LiveTranscriptionPanel({
  ownerUserId,
  projectId,
  csrf,
  onCsrf,
  active,
  initialSegments = [],
  onSegmentsChange,
}: Props) {
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [provider, setProvider] = useState<"elevenlabs" | "yandex">(
    "elevenlabs",
  );
  const [credentialId, setCredentialId] = useState("");
  const [credentialsState, setCredentialsState] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [credentialsMessage, setCredentialsMessage] = useState("");
  const [providerCatalog, setProviderCatalog] = useState<
    SttProviderCapability[]
  >([]);
  const [providerCatalogState, setProviderCatalogState] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [displayAudio, setDisplayAudio] = useState(() =>
    Boolean(navigator.mediaDevices?.getDisplayMedia),
  );
  const [microphone, setMicrophone] = useState(() =>
    !navigator.mediaDevices?.getDisplayMedia &&
    Boolean(navigator.mediaDevices?.getUserMedia),
  );
  const [microphoneDeviceId, setMicrophoneDeviceId] = useState("");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [language, setLanguage] =
    useState<TranscriptionLanguageMode>("ru");
  const [status, setStatus] = useState<RealtimeSessionStatus>("ready");
  const [partial, setPartial] = useState("");
  const [segments, setSegments] = useState<string[]>(() => [
    ...initialSegments,
  ]);
  const [error, setError] = useState("");
  const [exportNotice, setExportNotice] = useState("");
  const [inputLevel, setInputLevel] = useState(0);
  const [displayInputLevel, setDisplayInputLevel] = useState(0);
  const [microphoneInputLevel, setMicrophoneInputLevel] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [exportFormat, setExportFormat] = useState<LiveExportFormat>("txt");
  const [exportSession, setExportSession] = useState("");
  const [segmentMetadata, setSegmentMetadata] = useState<(RealtimeSegmentMetadata | null)[]>(initialSegments.map(() => null));
  const [followTranscript, setFollowTranscript] = useState(true);
  const [recoveryCandidate, setRecoveryCandidate] =
    useState<RealtimeDraft | null>(null);
  const [recoveryState, setRecoveryState] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [draftStatus, setDraftStatus] = useState<
    "idle" | "saving" | "saved" | "degraded"
  >("idle");
  const [youtubeEndpoint, setYoutubeEndpoint] = useState("");
  const [webhookEndpoint, setWebhookEndpoint] = useState("");
  const [consumersOpen, setConsumersOpen] = useState(false);
  const [consumerStatus, setConsumerStatus] = useState<Record<string, string>>(
    {},
  );
  const [historyVersion, setHistoryVersion] = useState(0);
  const [preparingStart, setPreparingStart] = useState(false);
  const [clearRequested, setClearRequested] = useState(false);
  const [clearPending, setClearPending] = useState(false);
  const [clearBoundaryPending, setClearBoundaryPending] = useState(false);
  const startButtonRef = useRef<HTMLButtonElement>(null);
  const stopButtonRef = useRef<HTMLButtonElement>(null);
  const startingRef = useRef(false);
  const activeRef = useRef(active);
  activeRef.current = active;
  const captureEpochRef = useRef(0);
  const controllerRef = useRef<RealtimeSessionController | null>(null);
  const credentialRequestEpochsRef = useRef(new Map<string, number>());
  const credentialRequestControllersRef = useRef(
    new Map<string, AbortController>(),
  );
  const sessionStartedAtRef = useRef<number | null>(null);
  const committedRef = useRef<HTMLDivElement | null>(null);
  const segmentsRef = useRef([...initialSegments]);
  const segmentMetadataRef = useRef<(RealtimeSegmentMetadata | null)[]>(initialSegments.map(() => null));
  const partialRef = useRef("");
  const draftRef = useRef<RealtimeDraft | null>(null);
  const localSaveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const serverSaveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const draftMutationGenerationRef = useRef(0);
  const draftDeletionGenerationRef = useRef(0);
  const draftDeletePendingRef = useRef(false);
  const partialCheckpointTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);
  const csrfRef = useRef(csrf);
  const onCsrfRef = useRef(onCsrf);
  const captionChannelRef = useRef<BroadcastChannel | null>(null);
  const consumerSequenceRef = useRef(0);
  const microphoneSupported = Boolean(
    navigator.mediaDevices?.getUserMedia,
  );
  const displayAudioSupported = Boolean(
    navigator.mediaDevices?.getDisplayMedia,
  );

  const running = [
    "requesting_permission",
    "connecting",
    "reconnecting",
    "connected",
    "transcribing",
    "stopping",
  ].includes(status);
  const providerCapability = providerCatalog.find(
    (candidate) => candidate.provider === provider,
  );
  const realtimeCapability = providerCapability?.modes.find(
    (candidate) => candidate.mode === "realtime",
  );
  const providerName =
    providerCapability?.display_name ??
    (provider === "yandex" ? "Yandex SpeechKit" : "ElevenLabs");
  const providerBlocker =
    providerCatalogState === "ready" && !providerCapability
      ? "Выбранный STT-провайдер отсутствует в актуальном каталоге Studio"
      : providerCapability
        ? !providerCapability.byok_enabled
          ? `${providerName} пока не включён оператором Studio`
          : !realtimeCapability
            ? `${providerName} не поддерживает Live-транскрибацию`
            : !realtimeCapability.health.available
              ? `${providerName} временно недоступен в Live-режиме`
              : ""
        : "";
  const activeProviderCredentials = credentials.filter(
    (credential) => credential.provider === provider,
  );
  const transcript = useMemo(() => segments.join("\n"), [segments]);
  const exportSessions = liveExportSessions(segmentMetadata);
  const selectedExportSession = exportSessions.includes(exportSession) ? exportSession : "";
  const selectedExportInput = liveExportSelection({ segments, metadata: segmentMetadata, partial }, selectedExportSession);
  const actionableDraftText = useMemo(
    () => realtimeTranscriptText(segments, partial),
    [segments, partial],
  );
  csrfRef.current = csrf;
  onCsrfRef.current = onCsrf;

  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel(REALTIME_CAPTION_CHANNEL);
    captionChannelRef.current = channel;
    return () => {
      channel.close();
      if (captionChannelRef.current === channel) captionChannelRef.current = null;
    };
  }, [projectId]);

  function publishCaption(committed: string[], currentPartial: string) {
    captionChannelRef.current?.postMessage(
      makeRealtimeCaptionMessage(projectId, committed, currentPartial),
    );
  }

  function deliverCommittedCaption(text: string) {
    const sequence = consumerSequenceRef.current++;
    const targets = [
      { kind: "youtube_live" as const, endpoint: youtubeEndpoint.trim() },
      { kind: "webhook" as const, endpoint: webhookEndpoint.trim() },
    ].filter((target) => target.endpoint);
    for (const target of targets) {
      setConsumerStatus((current) => ({ ...current, [target.kind]: "Отправляем…" }));
      void deliverRealtimeConsumer(
        projectId,
        target.kind,
        target.endpoint,
        text,
        sequence,
        csrfRef.current,
        onCsrfRef.current,
      ).then(
        () =>
          setConsumerStatus((current) => ({
            ...current,
            [target.kind]: "Доставлено",
          })),
        () =>
          setConsumerStatus((current) => ({
            ...current,
            [target.kind]: "Ошибка доставки; основная транскрибация продолжается",
          })),
      );
    }
  }

  function enqueueLocalDraftSave(nextDraft: RealtimeDraft) {
    const deletionGeneration = draftDeletionGenerationRef.current;
    const operation = localSaveQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        if (
          draftDeletePendingRef.current ||
          deletionGeneration !== draftDeletionGenerationRef.current
        ) {
          return false;
        }
        try {
          await saveLocalRealtimeDraft(nextDraft);
          return true;
        } catch {
          return false;
        }
      });
    localSaveQueueRef.current = operation.then(
      () => undefined,
      () => undefined,
    );
    return operation;
  }

  function enqueueServerDraftSave(nextDraft: RealtimeDraft) {
    const deletionGeneration = draftDeletionGenerationRef.current;
    const operation = serverSaveQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        if (
          draftDeletePendingRef.current ||
          deletionGeneration !== draftDeletionGenerationRef.current
        ) {
          return false;
        }
        try {
          const bounded = await runBoundedRequest(
            (signal) =>
              mutateWithCsrfRetry<unknown>(
                `/projects/${projectId}/realtime/drafts/${encodeURIComponent(nextDraft.client_session_id)}`,
                csrfRef.current,
                onCsrfRef.current,
                {
                  method: "PUT",
                  signal,
                  body: JSON.stringify({
                    revision: nextDraft.revision,
                    committed_segments: nextDraft.committed_segments,
                    segment_metadata: nextDraft.segment_metadata,
                    partial: nextDraft.partial,
                  }),
                },
              ),
            REALTIME_DRAFT_REQUEST_TIMEOUT_MS,
          );
          if (bounded.status !== "completed") return false;
          const response = bounded.value;
          const metadata =
            response && typeof response === "object"
              ? (response as { draft?: unknown }).draft
              : null;
          return Boolean(
            metadata &&
              typeof metadata === "object" &&
              (metadata as { client_session_id?: unknown }).client_session_id ===
                nextDraft.client_session_id &&
              (metadata as { revision?: unknown }).revision ===
                nextDraft.revision,
          );
        } catch {
          return false;
        }
      });
    serverSaveQueueRef.current = operation.then(
      () => undefined,
      () => undefined,
    );
    return operation;
  }

  async function persistDraft(nextDraft: RealtimeDraft) {
    const generation = draftMutationGenerationRef.current;
    const localWrite = enqueueLocalDraftSave(nextDraft);
    const serverWrite = enqueueServerDraftSave(nextDraft);
    const [localSaved, serverSaved] = await Promise.all([
      localWrite,
      serverWrite,
    ]);
    if (
      !mountedRef.current ||
      generation !== draftMutationGenerationRef.current ||
      draftRef.current?.client_session_id !== nextDraft.client_session_id ||
      draftRef.current?.revision !== nextDraft.revision
    ) {
      return localSaved || serverSaved;
    }
    setDraftStatus(localSaved && serverSaved ? "saved" : "degraded");
    return localSaved || serverSaved;
  }

  function checkpointDraft(
    committedSegments: string[],
    latestPartial: string,
    reportStatus = true,
  ) {
    if (
      draftDeletePendingRef.current ||
      (committedSegments.length === 0 && !latestPartial)
    ) {
      return;
    }
    const nextRevision = (draftRef.current?.revision ?? 0) + 1;
    let nextDraft: RealtimeDraft;
    try {
      nextDraft = makeRealtimeDraft({
        ownerUserId,
        projectId,
        clientSessionId:
          draftRef.current?.client_session_id ?? newRealtimeClientSessionId(),
        revision: nextRevision,
        committedSegments,
        segmentMetadata: segmentMetadataRef.current,
        partial: latestPartial,
      });
    } catch {
      if (reportStatus) {
        setDraftStatus("degraded");
        setError(
          "Live-текст превысил безопасный размер временного черновика. Скачайте текущий текст.",
        );
      }
      return;
    }
    draftRef.current = nextDraft;
    if (reportStatus) setDraftStatus("saving");
    void persistDraft(nextDraft);
  }

  function schedulePartialCheckpoint(nextPartial: string) {
    if (partialCheckpointTimerRef.current !== null) {
      window.clearTimeout(partialCheckpointTimerRef.current);
    }
    partialCheckpointTimerRef.current = window.setTimeout(() => {
      partialCheckpointTimerRef.current = null;
      checkpointDraft(segmentsRef.current, nextPartial);
    }, REALTIME_PARTIAL_CHECKPOINT_DEBOUNCE_MS);
  }

  useEffect(() => {
    mountedRef.current = true;
    let cancelled = false;
    setRecoveryState("loading");
    setRecoveryCandidate(null);
    void Promise.all([
      loadLocalRealtimeDraft(ownerUserId, projectId).catch(() => null),
      runBoundedRequest(
        (signal) =>
          api<unknown>(`/projects/${projectId}/realtime/drafts/latest`, {
            signal,
            ignoredAbortReason: JOB_MUTATION_TIMEOUT_REASON,
          }),
        REALTIME_DRAFT_REQUEST_TIMEOUT_MS,
      )
        .then((bounded) => {
          if (bounded.status !== "completed") return undefined;
          const candidate = bounded.value;
          const parsed = parseLatestRealtimeDraftResponse(
            candidate,
            ownerUserId,
            projectId,
          );
          if (parsed === undefined) throw new Error("invalid_realtime_draft_response");
          return parsed;
        })
        .catch(() => undefined),
    ]).then(async ([localDraft, serverDraft]) => {
      if (cancelled) return;
      let recoveryUnavailable = serverDraft === undefined;
      let candidate = newestRealtimeDraft(localDraft, serverDraft ?? null);
      if (candidate && candidate.client_session_id !== serverDraft?.client_session_id) {
        const localCandidate = candidate;
        const verified = await runBoundedRequest(signal => api<unknown>(
          `/projects/${projectId}/realtime/drafts/${encodeURIComponent(localCandidate.client_session_id)}`,
          {signal, cache:"no-store"}), REALTIME_DRAFT_REQUEST_TIMEOUT_MS).catch(() => null);
        if (cancelled) return;
        if (verified?.status === "completed" && verified.value && typeof verified.value === "object"
          && (verified.value as {cleared?:unknown}).cleared === true && (verified.value as {draft?:unknown}).draft === null) {
          await deleteLocalRealtimeDraft(ownerUserId, projectId, localCandidate.client_session_id).catch(() => undefined);
          if (cancelled) return;
          candidate = serverDraft ?? null;
        } else if (verified?.status !== "completed" || parseLatestRealtimeDraftResponse(verified.value, ownerUserId, projectId) === undefined) {
          recoveryUnavailable = true;
        }
      }
      if (cancelled) return;
      setRecoveryState(recoveryUnavailable ? "error" : "ready");
      if (
        candidate &&
        (candidate.committed_segments.length > 0 || candidate.partial)
      ) {
        setRecoveryCandidate(candidate);
      }
    });
    return () => {
      if (
        partialRef.current &&
        draftRef.current?.partial !== partialRef.current
      ) {
        checkpointDraft(segmentsRef.current, partialRef.current, false);
      }
      cancelled = true;
      mountedRef.current = false;
      captureEpochRef.current += 1;
      draftMutationGenerationRef.current += 1;
      if (partialCheckpointTimerRef.current !== null) {
        window.clearTimeout(partialCheckpointTimerRef.current);
        partialCheckpointTimerRef.current = null;
      }
    };
  }, [ownerUserId, projectId]);

  useEffect(() => {
    const flushDraft = () => {
      if (
        partialRef.current &&
        draftRef.current?.partial !== partialRef.current
      ) {
        checkpointDraft(segmentsRef.current, partialRef.current);
      }
    };
    window.addEventListener("pagehide", flushDraft);
    return () => window.removeEventListener("pagehide", flushDraft);
  }, [ownerUserId, projectId]);

  useEffect(() => {
    const startedAt = sessionStartedAtRef.current;
    if (!running || startedAt === null) return;
    const updateElapsed = () =>
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [running, status]);

  useEffect(() => {
    const committed = committedRef.current;
    if (!committed || !followTranscript) return;
    committed.scrollTop = committed.scrollHeight;
  }, [segments, followTranscript]);

  const loadCredentials = async () => {
    setCredentialsState("loading");
    setCredentialsMessage("");
    await settleLatestRequest(
      credentialRequestEpochsRef.current,
      "live:credentials",
      requestCredentialCollection,
      (credentialCollection) => {
        const activeCredentials = credentialCollection.filter(
          (credential) =>
            (credential.provider === "elevenlabs" ||
              credential.provider === "yandex") &&
            credential.status === "active",
        );
        setCredentials(activeCredentials);
        const matchingCredentials = activeCredentials.filter(
          (credential) => credential.provider === provider,
        );
        setCredentialId((selected) =>
          matchingCredentials.some((credential) => credential.id === selected)
            ? selected
            : (matchingCredentials[0]?.id ?? ""),
        );
        setCredentialsState("ready");
        setCredentialsMessage("");
      },
      () => {
        setCredentials([]);
        setCredentialId("");
        setCredentialsState("error");
        setCredentialsMessage(
          "Не удалось загрузить профили STT. Повторите попытку.",
        );
      },
      {
        controllers: credentialRequestControllersRef.current,
        timeoutMs: CREDENTIAL_REQUEST_TIMEOUT_MS,
      },
    );
  };

  const loadProviderCatalog = async () => {
    setProviderCatalogState("loading");
    await settleLatestRequest(
      credentialRequestEpochsRef.current,
      "live:providers",
      requestSttProviderCatalog,
      (catalog) => {
        setProviderCatalog(catalog);
        setProviderCatalogState("ready");
      },
      () => {
        setProviderCatalog([]);
        setProviderCatalogState("error");
      },
      {
        controllers: credentialRequestControllersRef.current,
        timeoutMs: CREDENTIAL_REQUEST_TIMEOUT_MS,
      },
    );
  };

  useEffect(() => {
    void loadCredentials();
    void loadProviderCatalog();
    return () => {
      cancelLatestRequests(
        credentialRequestEpochsRef.current,
        credentialRequestControllersRef.current,
      );
    };
  }, [projectId]);

  useEffect(() => {
    setCredentialId((selected) =>
      activeProviderCredentials.some((credential) => credential.id === selected)
        ? selected
        : (activeProviderCredentials[0]?.id ?? ""),
    );
  }, [provider, credentials]);

  async function refreshDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const available = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = available.filter(
        (device) => device.kind === "audioinput",
      );
      setDevices(audioInputs);
      setMicrophoneDeviceId((selected) =>
        selected && !audioInputs.some((device) => device.deviceId === selected)
          ? ""
          : selected,
      );
    } catch {
      setError(
        "Браузер пока не показывает аудиоустройства. После первого разрешения список обновится.",
      );
    }
  }

  useEffect(() => {
    void refreshDevices();
    const mediaDevices = navigator.mediaDevices;
    if (!mediaDevices?.addEventListener) return;
    const handler = () => void refreshDevices();
    mediaDevices.addEventListener("devicechange", handler);
    return () => mediaDevices.removeEventListener("devicechange", handler);
  }, []);

  useEffect(() => {
    const dispose = () => {
      controllerRef.current?.dispose();
      controllerRef.current = null;
    };
    window.addEventListener("pagehide", dispose);
    return () => {
      window.removeEventListener("pagehide", dispose);
      dispose();
    };
  }, [projectId]);

  useEffect(() => {
    const controller = controllerRef.current;
    if (active || !controller?.active) return;
    controller.stop();
    setExportNotice(
      "Live-сессия остановлена при переходе в пакетный режим. Текст сохранён в этой вкладке.",
    );
  }, [active]);

  useEffect(() => {
    if (!running && !actionableDraftText) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [running, actionableDraftText]);

  function resetVisibleDraft() {
    if (partialCheckpointTimerRef.current !== null) {
      window.clearTimeout(partialCheckpointTimerRef.current);
      partialCheckpointTimerRef.current = null;
    }
    draftRef.current = null;
    segmentsRef.current = [];
    segmentMetadataRef.current = [];
    partialRef.current = "";
    setSegments([]); setSegmentMetadata([]); setPartial("");
    onSegmentsChange?.([]);
    setRecoveryCandidate(null);
    setDraftStatus("idle");
    publishCaption([], "");
  }

  async function openSavedSession(candidate: RealtimeDraft) {
    if (running || startingRef.current || draftDeletePendingRef.current || !activeRef.current) return;
    const generation = captureEpochRef.current;
    if (draftRef.current?.client_session_id !== candidate.client_session_id && realtimeTranscriptText(segmentsRef.current, partialRef.current)) {
      checkpointDraft(segmentsRef.current, partialRef.current);
      if (!draftRef.current || !(await persistDraft(draftRef.current))) {
        setError("Текущий текст ещё не сохранён. Скачайте его перед переключением сессии.");
        return;
      }
    }
    if (captureEpochRef.current !== generation || startingRef.current || !mountedRef.current || !activeRef.current) return;
    resetVisibleDraft();
    draftRef.current = candidate;
    sessionStartedAtRef.current = null;
    setElapsedSeconds(0);
    segmentsRef.current = [...candidate.committed_segments];
    segmentMetadataRef.current = candidate.segment_metadata ?? candidate.committed_segments.map(() => null);
    partialRef.current = candidate.partial;
    setSegments(segmentsRef.current); setSegmentMetadata(segmentMetadataRef.current); setPartial(candidate.partial);
    onSegmentsChange?.(segmentsRef.current);
    setExportNotice("Сохранённая сессия открыта. Новая запись будет храниться отдельно.");
  }

  async function start() {
    if (running || startingRef.current || draftDeletePendingRef.current || !activeRef.current) return;
    startingRef.current = true;
    setPreparingStart(true);
    try {
      if (realtimeTranscriptText(segmentsRef.current, partialRef.current)) {
        checkpointDraft(segmentsRef.current, partialRef.current);
        if (!draftRef.current || !(await persistDraft(draftRef.current))) {
          setError("Не удалось сохранить прежнюю сессию. Скачайте её текст перед новой записью.");
          return;
        }
      }
      if (!mountedRef.current || !activeRef.current) return;
      resetVisibleDraft();
      const captureEpoch = ++captureEpochRef.current;
      setClearBoundaryPending(false);
    setError("");
    setExportNotice("");
    sessionStartedAtRef.current = null;
    consumerSequenceRef.current = 0;
    setElapsedSeconds(0);
    setFollowTranscript(true);
    const controller = new RealtimeSessionController(
      {
        onStatus: (nextStatus) => {
          if (captureEpoch !== captureEpochRef.current) return;
          if (nextStatus === "stopped" || nextStatus === "closed") setHistoryVersion(value => value + 1);
          if (
            (nextStatus === "connected" || nextStatus === "transcribing") &&
            sessionStartedAtRef.current === null
          ) {
            sessionStartedAtRef.current = Date.now();
            setElapsedSeconds(0);
          }
          if (
            (nextStatus === "stopped" || nextStatus === "closed") &&
            sessionStartedAtRef.current !== null
          ) {
            setElapsedSeconds(
              Math.floor(
                (Date.now() - sessionStartedAtRef.current) / 1000,
              ),
            );
          }
          setStatus(nextStatus);
          if (nextStatus === "connected" && microphone) {
            void refreshDevices();
          }
        },
        onPartial: (text) => {
          if (captureEpoch !== captureEpochRef.current) return;
          partialRef.current = text;
          setPartial(text);
          publishCaption(segmentsRef.current, text);
          schedulePartialCheckpoint(text);
        },
        onCommitted: (text, metadata) => {
          if (captureEpoch !== captureEpochRef.current) return;
          if (partialCheckpointTimerRef.current !== null) {
            window.clearTimeout(partialCheckpointTimerRef.current);
            partialCheckpointTimerRef.current = null;
          }
          const update = upsertLiveSegment(segmentsRef.current, segmentMetadataRef.current, text, metadata);
          const next = update.segments;
          const nextMetadata = update.metadata;
          segmentsRef.current = next;
          segmentMetadataRef.current = nextMetadata;
          setSegmentMetadata(nextMetadata);
          // A transport gap does not confirm or discard the provider's partial text.
          if (update.inserted && !metadata?.gap) partialRef.current = "";
          checkpointDraft(next, partialRef.current);
          setPartial(partialRef.current);
          setSegments(next);
          onSegmentsChange?.(next);
          publishCaption(next, partialRef.current);
          if (update.inserted && !metadata?.gap) deliverCommittedCaption(text);
        },
        onError: (message) => { if (captureEpoch === captureEpochRef.current) setError(message); },
        onClearBoundaryPending: (pending) => { if (captureEpoch === captureEpochRef.current) setClearBoundaryPending(pending); },
        onInputLevel: (level) => { if (captureEpoch === captureEpochRef.current) setInputLevel(level); },
        onSourceLevel: (kind, level) => {
          if (captureEpoch !== captureEpochRef.current) return;
          if (kind === "display") setDisplayInputLevel(level);
          else setMicrophoneInputLevel(level);
        },
      },
      {
        requestCapability: async (signal) => {
          try {
            return await mutateWithCsrfRetry(
              `/projects/${projectId}/realtime/capability`,
              csrf,
              onCsrf,
              {
                method: "POST",
                signal,
                body: JSON.stringify({
                  provider_credential_id: credentialId || null,
                  language,
                  provider,
                }),
              },
            );
          } catch (capabilityError) {
            throw new Error(capabilityFailureMessage(capabilityError, provider), {
              cause: capabilityError,
            });
          }
        },
      },
    );
    controllerRef.current?.dispose();
    controllerRef.current = controller;
    await controller.start({
      displayAudio,
      microphone,
      microphoneDeviceId: microphoneDeviceId || undefined,
    });
    } finally {
      startingRef.current = false;
      setPreparingStart(false);
    }
  }

  function stop() {
    controllerRef.current?.stop();
  }

  async function copyTranscript() {
    if (!actionableDraftText) return;
    try {
      await navigator.clipboard.writeText(actionableDraftText);
      setExportNotice("Текст скопирован в буфер обмена.");
    } catch {
      setExportNotice("");
      setError("Браузер не разрешил копирование. Используйте скачивание.");
    }
  }

  function downloadTextFile(text: string) {
    if (!text) return;
    const url = URL.createObjectURL(
      new Blob([text], { type: "text/plain;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = transcriptFilename();
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    setExportNotice("Текст сохранён в файл .txt.");
  }

  function downloadTranscript() {
    downloadFormattedTranscript(liveExportSelection({
      segments: segmentsRef.current,
      metadata: segmentMetadataRef.current,
      partial: partialRef.current,
      ...(sessionStartedAtRef.current !== null ? { startedAt: new Date(sessionStartedAtRef.current).toISOString() } : {}),
    }, selectedExportSession));
  }

  function downloadFormattedTranscript(input: LiveExportInput, format = exportFormat) {
    try {
      const result = exportLiveTranscript(input, format);
      const url = URL.createObjectURL(new Blob([result.bytes], { type: result.mime }));
      const link = document.createElement("a");
      link.href = url;
      link.download = transcriptFilename(format);
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setExportNotice(`Текст сохранён в файл .${format}.`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Не удалось сохранить файл. Текст остаётся доступен.");
    }
  }

  async function deleteDraft(draft: RealtimeDraft) {
    if (draftDeletePendingRef.current) return false;
    draftDeletePendingRef.current = true;
    draftMutationGenerationRef.current += 1;
    draftDeletionGenerationRef.current += 1;
    if (partialCheckpointTimerRef.current !== null) {
      window.clearTimeout(partialCheckpointTimerRef.current);
      partialCheckpointTimerRef.current = null;
    }
    setDraftStatus("saving");
    const localDelete = localSaveQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        try {
          await deleteLocalRealtimeDraft(ownerUserId, projectId, draft.client_session_id);
          return true;
        } catch {
          return false;
        }
      });
    localSaveQueueRef.current = localDelete.then(
      () => undefined,
      () => undefined,
    );
    const serverDelete = serverSaveQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        try {
          const bounded = await runBoundedRequest(
            (signal) =>
              mutateWithCsrfRetry<unknown>(
                `/projects/${projectId}/realtime/drafts/${encodeURIComponent(draft.client_session_id)}`,
                csrfRef.current,
                onCsrfRef.current,
                { method: "DELETE", signal },
              ),
            REALTIME_DRAFT_REQUEST_TIMEOUT_MS,
          );
          if (bounded.status !== "completed") return false;
          const response = bounded.value;
          return Boolean(
            response &&
              typeof response === "object" &&
              (response as { ok?: unknown }).ok === true,
          );
        } catch {
          return false;
        }
      });
    serverSaveQueueRef.current = serverDelete.then(
      () => undefined,
      () => undefined,
    );
    try {
      const [localDeleted, serverDeleted] = await Promise.all([
        localDelete,
        serverDelete,
      ]);
      if (!localDeleted || !serverDeleted) {
        throw new Error("invalid_realtime_draft_delete_response");
      }
      if (draftRef.current?.client_session_id === draft.client_session_id) {
        draftRef.current = null;
      }
      setDraftStatus("idle");
      return true;
    } catch {
      setDraftStatus("degraded");
      setError(
        "Очистка всех копий черновика не подтверждена. Текст в этой вкладке сохранён; повторите действие.",
      );
      return false;
    } finally {
      draftDeletePendingRef.current = false;
    }
  }

  async function restoreRecoveryDraft() {
    let candidate = recoveryCandidate;
    if (!candidate) return;
    const recoveringId = candidate.client_session_id;
    const generation = captureEpochRef.current;
    const verified = await runBoundedRequest(signal => api<unknown>(
      `/projects/${projectId}/realtime/drafts/${encodeURIComponent(recoveringId)}`,
      {signal, cache:"no-store"}), REALTIME_DRAFT_REQUEST_TIMEOUT_MS).catch(() => null);
    if (generation !== captureEpochRef.current || running || startingRef.current || !mountedRef.current) return;
    if (verified?.status === "completed" && verified.value && typeof verified.value === "object"
      && (verified.value as {cleared?:unknown}).cleared === true && (verified.value as {draft?:unknown}).draft === null) {
      await deleteLocalRealtimeDraft(ownerUserId, projectId, candidate.client_session_id).catch(() => undefined);
      if (generation !== captureEpochRef.current || !mountedRef.current) return;
      setRecoveryCandidate(null);
      setExportNotice("Эта сессия уже очищена в Studio. Старая локальная копия не восстановлена.");
      return;
    }
    if (verified?.status === "completed") {
      const latest = parseLatestRealtimeDraftResponse(verified.value, ownerUserId, projectId);
      if (latest?.client_session_id === candidate.client_session_id) candidate = newestRealtimeDraft(candidate, latest)!;
    }
    const retainedSegments = [...segmentsRef.current];
    const candidateSegments = [...candidate.committed_segments];
    const candidateExtendsRetained = segmentsArePrefix(
      retainedSegments,
      candidateSegments,
    );
    const retainedExtendsCandidate = segmentsArePrefix(
      candidateSegments,
      retainedSegments,
    );
    if (!candidateExtendsRetained && !retainedExtendsCandidate) {
      setError(
        "Сохранённый Live-черновик отличается от текста в этой вкладке. Скачайте черновик и явно удалите его либо сохраните текущий текст отдельно; автоматическая замена заблокирована.",
      );
      return;
    }
    if (
      retainedExtendsCandidate &&
      retainedSegments.length > candidateSegments.length
    ) {
      let reconciled: RealtimeDraft;
      try {
        reconciled = makeRealtimeDraft({
          ownerUserId,
          projectId,
          clientSessionId: candidate.client_session_id,
          revision: candidate.revision + 1,
          committedSegments: retainedSegments,
          segmentMetadata: segmentMetadataRef.current,
          partial: partialRef.current,
        });
      } catch {
        setError(
          "Более полный текст сохранён в этой вкладке, но его не удалось согласовать с временным черновиком. Скачайте оба варианта перед удалением.",
        );
        return;
      }
      draftRef.current = reconciled;
      setRecoveryCandidate(null);
      setDraftStatus("saving");
      void persistDraft(reconciled);
      setExportNotice(
        "Сохранён более полный текст из этой вкладки; старый Live-черновик не перезаписал его.",
      );
      return;
    }
    draftRef.current = candidate;
    segmentsRef.current = candidateSegments;
    sessionStartedAtRef.current = null;
    setElapsedSeconds(0);
    segmentMetadataRef.current = candidate.segment_metadata ?? candidateSegments.map(() => null);
    setSegmentMetadata(segmentMetadataRef.current);
    partialRef.current = candidate.partial;
    setSegments(candidateSegments);
    setPartial(candidate.partial);
    onSegmentsChange?.(candidateSegments);
    setRecoveryCandidate(null);
    setDraftStatus("saving");
    void persistDraft(candidate);
    setExportNotice("Незавершённый Live-черновик восстановлен.");
  }

  async function discardRecoveryDraft() {
    const candidate = recoveryCandidate;
    if (!candidate) return;
    setError("");
    if (await deleteDraft(candidate)) {
      setRecoveryCandidate(null);
      setExportNotice("Временный Live-черновик удалён.");
    }
  }

  async function clearTranscript(stopCapture: boolean) {
    if (!actionableDraftText || clearPending) return;
    setClearPending(true);
    if (stopCapture) {
      captureEpochRef.current += 1;
      controllerRef.current?.stop();
      controllerRef.current?.dispose();
      controllerRef.current = null;
      setStatus("stopped");
      setClearBoundaryPending(false);
    }
    const currentDraft = draftRef.current;
    try {
      if (currentDraft && !(await deleteDraft(currentDraft))) return;
      const continuing = !stopCapture && controllerRef.current?.active === true;
      if (!stopCapture) controllerRef.current?.clearTranscript();
      resetVisibleDraft();
      setHistoryVersion(value => value + 1);
      setExportNotice(stopCapture ? "Запись остановлена, текст этой сессии очищен." : continuing
        ? "Текст очищен. Запись продолжается; новые реплики сохраняются отдельно от очищенного текста."
        : "Текст этой сессии очищен.");
      setClearRequested(false);
    } finally { setClearPending(false); }
  }

  const sourceReady =
    (displayAudio && displayAudioSupported) ||
    (microphone && microphoneSupported);
  const startDisabled = running || preparingStart || clearPending ||
                credentialsState !== "ready" ||
                recoveryState === "loading" ||
                recoveryCandidate !== null ||
                !sourceReady ||
                !credentialId ||
                Boolean(providerBlocker);
  const startReadinessLabel = !sourceReady ? "Выберите источник звука"
    : recoveryCandidate ? "Сначала выберите действие с черновиком"
    : !credentialId ? "Выберите ключ провайдера"
    : "Проверяем настройки и готовность провайдера";
  const inputPercent = Math.round(inputLevel * 100);
  const displayInputPercent = Math.round(displayInputLevel * 100);
  const microphoneInputPercent = Math.round(microphoneInputLevel * 100);
  const inputSignalLabel = running
    ? inputPercent >= 2
      ? "Сигнал есть"
      : "Тишина или очень тихий сигнал"
    : "Измерение начнётся после запуска";
  return (
    <section
      className="live-transcription"
      aria-label="Live-транскрибация"
    >
      <header className="live-intro">
        <div>
          <h2>Live-транскрибация</h2>
          <p>
            Распознаёт микрофон, звук выбранной вкладки или экрана либо оба
            источника одновременно. Незавершённый текст можно восстановить
            до ручной очистки; звук не сохраняется.
          </p>
        </div>
        <span className={`live-status live-status-${status === "ready" && startDisabled ? "not-ready" : status}`} role="status">
          {status === "connecting"
            ? `Подключаемся к ${providerName}`
            : status === "ready" && startDisabled ? startReadinessLabel : STATUS_LABELS[status]}
        </span>
      </header>

      {recoveryState === "loading" && (
        <p className="muted" role="status">
          Проверяем незавершённые Live-черновики…
        </p>
      )}
      {recoveryState === "error" && (
        <p className="error" role="alert">
          Восстановление из Studio сейчас недоступно. Локальный черновик, если
          он есть, всё равно можно восстановить ниже.
        </p>
      )}
      {recoveryCandidate && (
        <section className="notice live-recovery" aria-label="Восстановление Live-черновика">
          <div>
            <h3>Найден незавершённый Live-черновик</h3>
            <p>
              Обновлён {new Date(recoveryCandidate.updated_at).toLocaleString("ru-RU")}
              {" · "}подтверждённых фрагментов: {recoveryCandidate.committed_segments.length}
              {recoveryCandidate.partial ? " · есть неподтверждённый фрагмент" : ""}.
            </p>
          </div>
          <div className="actions">
            <button
              type="button"
              className="primary"
              onClick={() => void restoreRecoveryDraft()}
            >
              Восстановить
            </button>
            <button
              type="button"
              onClick={() => downloadTextFile(realtimeDraftDownloadText(recoveryCandidate))}
            >
              Скачать .txt
            </button>
            {(["docx", "md", "srt", "vtt"] as const).map((format) => (
              <button type="button" key={format}
                disabled={(format === "srt" || format === "vtt") && Boolean(timedExportUnavailable({ segments: recoveryCandidate.committed_segments, metadata: recoveryCandidate.segment_metadata, partial: recoveryCandidate.partial }))}
                onClick={() => downloadFormattedTranscript({ segments: recoveryCandidate.committed_segments, metadata: recoveryCandidate.segment_metadata, partial: recoveryCandidate.partial }, format)}>
                Скачать .{format}
              </button>
            ))}
            {timedExportUnavailable({ segments: recoveryCandidate.committed_segments, metadata: recoveryCandidate.segment_metadata, partial: recoveryCandidate.partial }) && <p className="muted">{timedExportUnavailable({ segments: recoveryCandidate.committed_segments, metadata: recoveryCandidate.segment_metadata, partial: recoveryCandidate.partial })}</p>}
            <button
              type="button"
              className="danger"
              disabled={draftStatus === "saving"}
              onClick={() => void discardRecoveryDraft()}
            >
              Удалить черновик
            </button>
            <button type="button" disabled={preparingStart || running} onClick={() => {
              setRecoveryCandidate(null);
              setExportNotice("Сохранённый текст доступен в списке Live-сессий. Можно начать отдельную запись.");
            }}>Начать отдельную запись</button>
          </div>
        </section>
      )}

      <RealtimeSessionHistory ownerUserId={ownerUserId} projectId={projectId} disabled={running || preparingStart}
        currentDraft={draftRef.current} refreshKey={historyVersion} onOpen={openSavedSession} />

      <div className="live-config-grid">
        <section className="live-config-card">
          <h3>Источники звука</h3>
          <label className="check-row">
            <input
              type="checkbox"
              aria-label="Звук вкладки или экрана"
              checked={displayAudio}
              disabled={running || !displayAudioSupported}
              onChange={(event) => setDisplayAudio(event.target.checked)}
            />
            <span>
              <b>Звук вкладки или экрана</b>
              <small>
                {displayAudioSupported
                  ? "В окне Chrome выберите источник и включите передачу аудио."
                  : "Этот браузер не поддерживает захват звука вкладки или экрана."}
              </small>
            </span>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              aria-label="Микрофон или аудиовход"
              checked={microphone}
              disabled={running || !microphoneSupported}
              onChange={(event) => setMicrophone(event.target.checked)}
            />
            <span>
              <b>Микрофон или аудиовход</b>
              <small>
                {microphoneSupported
                  ? "Можно смешать с системным звуком."
                  : "Этот браузер не поддерживает захват микрофона."}
              </small>
            </span>
          </label>
          {microphone && (
            <label>
              Устройство ввода
              <select
                value={microphoneDeviceId}
                disabled={running}
                onChange={(event) =>
                  setMicrophoneDeviceId(event.target.value)
                }
              >
                <option value="">По умолчанию</option>
                {devices.map((device, index) => (
                  <option key={device.deviceId || index} value={device.deviceId}>
                    {device.label || `Аудиовход ${index + 1}`}
                  </option>
                ))}
              </select>
            </label>
          )}
          {!sourceReady && (
            <p className="error">Выберите хотя бы один источник аудио.</p>
          )}
          <div className="live-input-level">
            <div className="split">
              <b>Входной сигнал</b>
              <span>{inputSignalLabel} · {inputPercent}%</span>
            </div>
            <meter
              aria-label="Уровень входного аудио"
              min="0"
              max="100"
              value={inputPercent}
            />
            <small>
              Рассчитывается только в браузере и не сохраняется.
            </small>
            {displayAudio && microphone && (
              <div
                className="live-source-levels"
                aria-label="Уровни источников смешанного аудио"
              >
                <label>
                  Звук вкладки · {displayInputPercent}%
                  <meter
                    aria-label="Уровень звука вкладки"
                    min="0"
                    max="100"
                    value={displayInputPercent}
                  />
                </label>
                <label>
                  Микрофон · {microphoneInputPercent}%
                  <meter
                    aria-label="Уровень микрофона"
                    min="0"
                    max="100"
                    value={microphoneInputPercent}
                  />
                </label>
                <small>
                  Во время речи Studio автоматически приглушает звук вкладки.
                  Если шкала микрофона остаётся на нуле, браузер или устройство
                  не передаёт сигнал микрофона в смешанный поток.
                </small>
              </div>
            )}
          </div>
        </section>

        <section
          className="live-config-card"
          aria-busy={
            credentialsState === "loading" ||
            providerCatalogState === "loading" ||
            undefined
          }
        >
          <h3>Распознавание</h3>
          <label>
            Провайдер
            <select
              aria-label="Провайдер Live-транскрибации"
              value={provider}
              disabled={running}
              onChange={(event) =>
                setProvider(event.target.value as "elevenlabs" | "yandex")
              }
            >
              <option
                value="elevenlabs"
                disabled={
                  providerCatalogState === "ready" &&
                  providerCatalog.find(
                    (candidate) => candidate.provider === "elevenlabs",
                  )?.byok_enabled !== true
                }
              >
                ElevenLabs
              </option>
              <option
                value="yandex"
                disabled={
                  providerCatalogState === "ready" &&
                  providerCatalog.find(
                    (candidate) => candidate.provider === "yandex",
                  )?.byok_enabled !== true
                }
              >
                Yandex SpeechKit
                {providerCatalogState === "ready" &&
                providerCatalog.find(
                  (candidate) => candidate.provider === "yandex",
                )?.byok_enabled !== true
                  ? " — не включён"
                  : ""}
              </option>
            </select>
          </label>
          {providerCatalogState === "error" && (
            <p className="muted" role="status">
              Не удалось обновить доступность провайдеров. Studio проверит её
              при запуске сессии.
            </p>
          )}
          {providerBlocker && (
            <p className="error" role="alert">
              {providerBlocker}
            </p>
          )}
          <label>
            Профиль {providerName}
            <select
              value={credentialId}
              disabled={running || credentialsState !== "ready"}
              onChange={(event) => setCredentialId(event.target.value)}
            >
              {activeProviderCredentials.length === 0 && (
                <option value="">Активный профиль не найден</option>
              )}
              {activeProviderCredentials.map((credential) => (
                <option key={credential.id} value={credential.id}>
                  {credentialLabel(credential)}
                </option>
              ))}
            </select>
          </label>
          {credentialsState === "loading" && (
            <p role="status" className="muted">
              Загружаем профили STT…
            </p>
          )}
          {credentialsState === "error" && (
            <div className="error">
              <p role="alert">{credentialsMessage}</p>
              <button
                type="button"
                className="secondary"
                onClick={() => void loadCredentials()}
              >
                Повторить загрузку профилей
              </button>
            </div>
          )}
          <label>
            Язык
            <select
              value={language}
              disabled={running}
              onChange={(event) =>
                setLanguage(event.target.value as TranscriptionLanguageMode)
              }
            >
              <option value="ru">Русский</option>
              <option value="en">Английский</option>
              <option value="detect">Определить автоматически</option>
            </select>
          </label>
          <details className="technical-details">
            <summary>Технические параметры</summary>
            <p className="muted">
              Provider: {providerName} · mode: realtime · segment detection:
              VAD.
            </p>
          </details>
          <div className="actions">
            <button
              className="primary"
              type="button"
              disabled={startDisabled}
              ref={startButtonRef}
              onClick={() => void start()}
            >
              Начать
            </button>
            <button ref={stopButtonRef} type="button" disabled={!running || clearPending} onClick={stop}>
              Остановить
            </button>
          </div>
        </section>
      </div>

      <details className="live-config-card realtime-consumers" onToggle={(event) => setConsumersOpen(event.currentTarget.open)}>
        <summary>Субтитры и внешние получатели</summary>
        <p className="muted">
          Каждый получатель работает независимо. Ошибка overlay, YouTube или
          webhook не останавливает распознавание и сохранение основного текста.
        </p>
        <div className="actions">
          <button
            type="button"
            onClick={() =>
              window.open(
                `/realtime-overlay?project=${encodeURIComponent(projectId)}`,
                "studio-realtime-overlay",
                "popup,width=1280,height=720",
              )
            }
          >
            Открыть overlay для браузера / OBS
          </button>
        </div>
        {active && consumersOpen && (
          <form
            className="realtime-consumer-endpoints"
            aria-label="Адреса внешних получателей Live"
            autoComplete="off"
            onSubmit={(event) => event.preventDefault()}
          >
            <label>
              YouTube Live closed-caption ingestion URL
              <input
                type="password"
                name="youtube-caption-ingestion-url"
                autoComplete="new-password"
                value={youtubeEndpoint}
                disabled={running}
                placeholder="https://upload.youtube.com/closedcaption?..."
                onChange={(event) => setYoutubeEndpoint(event.target.value)}
              />
              <small>
                Адрес действует только в этой вкладке и не сохраняется в Studio.
              </small>
              {consumerStatus.youtube_live && (
                <span role="status">{consumerStatus.youtube_live}</span>
              )}
            </label>
            <label>
              HTTPS webhook
              <input
                type="password"
                name="live-webhook-endpoint"
                autoComplete="new-password"
                value={webhookEndpoint}
                disabled={running}
                placeholder="Разрешённый оператором HTTPS endpoint"
                onChange={(event) => setWebhookEndpoint(event.target.value)}
              />
              <small>
                Хост должен быть заранее добавлен оператором в allowlist Studio.
              </small>
              {consumerStatus.webhook && (
                <span role="status">{consumerStatus.webhook}</span>
              )}
            </label>
          </form>
        )}
      </details>

      {displayAudio && microphone && !running && (
        <p className="notice">
          В смешанном режиме Studio показывает уровни каждого источника и
          автоматически приглушает системный источник во время речи. Наушники
          дополнительно уменьшают эхо, но не требуются для диагностики.
        </p>
      )}
      {error && !clearRequested && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {exportNotice && (
        <p className="notice" role="status">
          {exportNotice}
        </p>
      )}
      {draftStatus === "saving" && (
        <p className="muted" role="status">Сохраняем временный Live-черновик…</p>
      )}
      {draftStatus === "saved" && (
        <p className="muted" role="status">
          Live-текст сохранён локально и в Studio до ручной очистки.
        </p>
      )}
      {draftStatus === "degraded" && (
        <p className="error" role="alert">
          Не все копии Live-черновика подтверждены. Не закрывайте вкладку и
          скачайте текст при первой возможности.
        </p>
      )}
      {clearBoundaryPending && <p className="notice" role="status">После очистки ждём разметку текущей реплики от провайдера. Studio покажет слова после границы очистки; для фразы без таймкодов граница не угадывается.</p>}

      <section className="live-transcript-card">
        <header className="split">
          <div>
            <h3>Текст Live-транскрибации</h3>
            <p className="muted">
              Хранится до вашей ручной очистки. Не попадает в
              Google Docs, каталог, пакетную историю, аналитику или диагностику.
            </p>
            <p className="muted" aria-label="Статистика live-сессии">
              Сессия: {running || elapsedSeconds > 0 ? formatElapsed(elapsedSeconds) : actionableDraftText ? "сохранённый текст" : "не запущена"} · Фрагментов:{" "}
              {segments.length} · Символов: {transcript.length}
            </p>
          </div>
          <div className="actions">
            <label>
              Формат скачивания
              <select aria-label="Формат скачивания Live" value={exportFormat} onChange={(event) => setExportFormat(event.target.value as LiveExportFormat)}>
                {LIVE_EXPORT_FORMATS.map((format) => <option key={format} value={format} disabled={(format === "srt" || format === "vtt") && Boolean(timedExportUnavailable(selectedExportInput))}>{format.toUpperCase()}</option>)}
              </select>
            </label>
            {exportSessions.length > 0 && (exportSessions.length > 1 || segmentMetadata.some((item) => !item?.session_id)) && (
              <label>Текст для скачивания
                <select aria-label="Сессия скачивания Live" value={selectedExportSession} onChange={(event) => setExportSession(event.target.value)}>
                  <option value="">Весь сохранённый текст</option>
                  {exportSessions.map((id, index) => <option key={id} value={id}>Сессия {index + 1}: подтверждённый текст</option>)}
                </select>
              </label>
            )}
            <button
              type="button"
              aria-pressed={followTranscript}
              onClick={() => setFollowTranscript((current) => !current)}
            >
              Автопрокрутка: {followTranscript ? "вкл" : "выкл"}
            </button>
            <button
              type="button"
              disabled={!actionableDraftText}
              onClick={() => void copyTranscript()}
            >
              Копировать
            </button>
            <button
              type="button"
              disabled={!actionableDraftText || ((exportFormat === "srt" || exportFormat === "vtt") && Boolean(timedExportUnavailable(selectedExportInput)))}
              onClick={downloadTranscript}
            >
              Скачать .{exportFormat}
            </button>
            <button
              type="button"
              disabled={
                !actionableDraftText ||
                preparingStart || clearPending || status === "stopping" ||
                recoveryState === "loading"
              }
              onClick={() => {setError(""); setClearRequested(true);}}
            >
              Очистить
            </button>
          </div>
        </header>
        {selectedExportSession && <p className="muted">Скачивается подтверждённый текст выбранной сессии. Неподтверждённый фрагмент остаётся в выгрузке всего сохранённого текста.</p>}
        {timedExportUnavailable(selectedExportInput) && (
          <p className="muted" role="status">{timedExportUnavailable(selectedExportInput)}</p>
        )}
        <div className="live-partial" aria-live="polite">
          <span>Предварительно</span>
          <p>{partial || "Речь появится здесь до подтверждения фрагмента."}</p>
        </div>
        <div
          ref={committedRef}
          className="live-committed"
          aria-label="Подтверждённая транскрипция"
          aria-live="polite"
          onScroll={(event) => {
            const target = event.currentTarget;
            const distanceFromBottom =
              target.scrollHeight - target.scrollTop - target.clientHeight;
            setFollowTranscript(distanceFromBottom <= 32);
          }}
        >
          {segments.length === 0 ? (
            <p className="muted">
              Подтверждённых фрагментов пока нет.
            </p>
          ) : (
            segments.map((segment, index) => (
              <p key={segmentMetadata[index]?.id ?? `${index}-${segment.slice(0, 24)}`}>
                {segmentMetadata[index]?.speaker !== undefined && <strong>Спикер {segmentMetadata[index]!.speaker}: </strong>}
                {segment}
              </p>
            ))
          )}
        </div>
      </section>
      {clearRequested && <ConfirmClearDialog title="Очистить текст Live-сессии?"
        description={running ? "Очистим накопленный текст в этой вкладке и сохранённых копиях. Можно продолжить запись или остановить её. Другие сессии сохранятся." : "Очистим текст этой сессии в этой вкладке и сохранённых копиях. Другие сессии сохранятся."}
        pending={clearPending} confirmLabel={running ? "Очистить и продолжить" : "Очистить"} cancelLabel="Отмена"
        error={error}
        secondaryConfirm={running ? {label:"Остановить и очистить", onClick:() => void clearTranscript(true)} : undefined}
        onConfirm={() => void clearTranscript(false)} onCancel={() => setClearRequested(false)}
        fallbackFocus={() => (controllerRef.current?.active ? stopButtonRef.current : startButtonRef.current)?.focus()} />}

      <details className="live-boundaries technical-details">
        <summary>Технические ограничения и восстановление</summary>
        <ul>
          <li>
            При временном разрыве связи Studio автоматически пытается
            восстановить соединение и передать ещё не отправленный звук из
            ограниченного буфера. Невосстановленные участки отмечаются как
            пропуски. Если восстановление не удалось, запустите новую сессию.
          </li>
          <li>
            Обновление или закрытие текущей вкладки останавливает захват.
            После повторного входа можно восстановить последний черновик, но
            звук и сама Live-сессия не возобновляются.
          </li>
          <li>
            Пока идёт сессия или есть текст, браузер предупреждает
            перед обновлением или закрытием вкладки.
          </li>
          <li>
            Другие вкладки не продолжают захват звука; владелец аккаунта может
            восстановить последний временный черновик.
          </li>
        </ul>
      </details>
    </section>
  );
}
