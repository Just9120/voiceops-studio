import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";

import { lockDocumentScroll } from "./documentScrollLock";
import type {
  PickerResult,
  PickerSelection,
  PickerSession,
} from "./googlePicker";

const DRIVE_API_ROOT = "https://www.googleapis.com/drive/v3";
const FOLDER_MIME_TYPE = "application/vnd.google-apps.folder";
const GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document";
const MAX_LIST_PAGES = 10;
const MAX_SOURCE_SELECTIONS = 50;
const PAGE_SIZE = 100;
const INTERACTION_TIMEOUT_MS = 300_000;

export type AppOwnedDrivePickerMode =
  | "sources"
  | "source-folder"
  | "output-folder"
  | "transcript-folder"
  | "transcript-document";

export type DriveSourceMimePolicy = {
  supported_mime_prefixes: string[];
  supported_mime_types: string[];
};

type DriveItem = PickerSelection & { driveId?: string };

type DrivePage = {
  items: DriveItem[];
  nextPageToken?: string;
  pagesLoaded: number;
  usedPageTokens: string[];
};

type DriveListPayload = {
  files?: unknown;
  nextPageToken?: unknown;
};

type SharedDrivePayload = {
  drives?: unknown;
  nextPageToken?: unknown;
};

type DriveSort = "name_natural" | "name_natural desc" | "modifiedTime desc,name_natural" | "modifiedTime,name_natural";

const EMPTY_PAGE: DrivePage = {
  items: [],
  pagesLoaded: 0,
  usedPageTokens: [],
};

const DEFAULT_SOURCE_MIME_POLICY: DriveSourceMimePolicy = {
  supported_mime_prefixes: ["audio/", "video/"],
  supported_mime_types: ["application/ogg"],
};

function safeItemName(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim()
    ? value.trim().slice(0, 512)
    : fallback;
}

function normalizeMimePolicy(
  policy?: DriveSourceMimePolicy,
): DriveSourceMimePolicy {
  if (!policy) return DEFAULT_SOURCE_MIME_POLICY;
  const prefixes = policy.supported_mime_prefixes
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  const types = policy.supported_mime_types
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  return prefixes.length + types.length > 0
    ? {
        supported_mime_prefixes: [...new Set(prefixes)],
        supported_mime_types: [...new Set(types)],
      }
    : DEFAULT_SOURCE_MIME_POLICY;
}

function isSupportedMimeType(
  mimeType: string,
  policy: DriveSourceMimePolicy,
): boolean {
  const normalized = mimeType.trim().toLowerCase();
  return (
    policy.supported_mime_prefixes.some((prefix) =>
      normalized.startsWith(prefix),
    ) || policy.supported_mime_types.includes(normalized)
  );
}

function parseDriveItem(
  value: unknown,
  mode: AppOwnedDrivePickerMode,
  policy: DriveSourceMimePolicy,
  inheritedDriveId?: string,
): DriveItem | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.id !== "string" || !candidate.id.trim()) return null;
  const mimeType =
    typeof candidate.mimeType === "string" ? candidate.mimeType : "";
  const isFolder = mimeType === FOLDER_MIME_TYPE;
  const supportedFile =
    (mode === "sources" && isSupportedMimeType(mimeType, policy)) ||
    (mode === "transcript-document" && mimeType === GOOGLE_DOC_MIME_TYPE);
  if (!isFolder && !supportedFile) {
    return null;
  }
  return {
    id: candidate.id,
    name: safeItemName(
      candidate.name,
      isFolder ? "Папка Google Drive" : "Файл Google Drive",
    ),
    mimeType,
    driveId:
      typeof candidate.driveId === "string" && candidate.driveId.trim()
        ? candidate.driveId
        : inheritedDriveId,
  };
}

function parseSharedDrive(value: unknown): DriveItem | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.id !== "string" || !candidate.id.trim()) return null;
  return {
    id: candidate.id,
    name: safeItemName(candidate.name, "Общий диск"),
    mimeType: FOLDER_MIME_TYPE,
    driveId: candidate.id,
  };
}

function driveQueryLiteral(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll("'", "\\'");
}

function driveApiUrl(path: string, params: Record<string, string>): string {
  const url = new URL(`${DRIVE_API_ROOT}${path}`);
  Object.entries(params).forEach(([key, value]) =>
    url.searchParams.set(key, value),
  );
  return url.toString();
}

function itemMimeQuery(
  mode: AppOwnedDrivePickerMode,
  policy: DriveSourceMimePolicy,
): string {
  if (mode !== "sources") {
    if (mode === "transcript-document") {
      return `(mimeType = '${FOLDER_MIME_TYPE}' or mimeType = '${GOOGLE_DOC_MIME_TYPE}')`;
    }
    return `mimeType = '${FOLDER_MIME_TYPE}'`;
  }
  const mediaClauses = [
    ...policy.supported_mime_prefixes.map(
      (prefix) => `mimeType contains '${driveQueryLiteral(prefix)}'`,
    ),
    ...policy.supported_mime_types.map(
      (mimeType) => `mimeType = '${driveQueryLiteral(mimeType)}'`,
    ),
  ];
  return `(${[`mimeType = '${FOLDER_MIME_TYPE}'`, ...mediaClauses].join(" or ")})`;
}

async function fetchDriveJson(
  url: string,
  accessToken: string,
  signal: AbortSignal,
): Promise<unknown> {
  const response = await fetch(url, {
    method: "GET",
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error("Google Drive request failed");
  }
  return response.json();
}

async function loadRootFolder(
  accessToken: string,
  signal: AbortSignal,
): Promise<DriveItem> {
  const payload = await fetchDriveJson(
    driveApiUrl("/files/root", {
      fields: "id,name,mimeType,driveId",
      supportsAllDrives: "true",
    }),
    accessToken,
    signal,
  );
  const root = parseDriveItem(
    payload,
    "output-folder",
    DEFAULT_SOURCE_MIME_POLICY,
  );
  if (!root) throw new Error("Google Drive root response is invalid");
  const candidate = payload as Record<string, unknown>;
  return { ...root, name: safeItemName(candidate.name, "Мой диск") };
}

async function loadItemPage({
  parent,
  searchTerm,
  mode,
  policy,
  accessToken,
  signal,
  pageToken,
  orderBy = "name_natural",
}: {
  parent?: DriveItem;
  searchTerm?: string;
  mode: AppOwnedDrivePickerMode;
  policy: DriveSourceMimePolicy;
  accessToken: string;
  signal: AbortSignal;
  pageToken?: string;
  orderBy?: DriveSort;
}): Promise<{ items: DriveItem[]; nextPageToken?: string }> {
  const clauses = ["trashed = false", itemMimeQuery(mode, policy)];
  if (parent) {
    clauses.unshift(`'${driveQueryLiteral(parent.id)}' in parents`);
  }
  if (searchTerm) {
    clauses.push(`name contains '${driveQueryLiteral(searchTerm)}'`);
  }
  const params: Record<string, string> = {
    q: clauses.join(" and "),
    fields: "nextPageToken,files(id,name,mimeType,driveId)",
    pageSize: String(PAGE_SIZE),
    orderBy,
    spaces: "drive",
    supportsAllDrives: "true",
    includeItemsFromAllDrives: "true",
  };
  if (parent?.driveId) {
    params.corpora = "drive";
    params.driveId = parent.driveId;
  } else if (searchTerm) {
    params.corpora = "user";
  }
  if (pageToken) params.pageToken = pageToken;
  const payload = (await fetchDriveJson(
    driveApiUrl("/files", params),
    accessToken,
    signal,
  )) as DriveListPayload;
  const items = Array.isArray(payload.files)
    ? payload.files
        .map((value) =>
          parseDriveItem(value, mode, policy, parent?.driveId),
        )
        .filter((item): item is DriveItem => item !== null)
    : [];
  return {
    items,
    nextPageToken:
      typeof payload.nextPageToken === "string" && payload.nextPageToken
        ? payload.nextPageToken
        : undefined,
  };
}

async function loadSharedFolderPage({
  accessToken,
  signal,
  pageToken,
  orderBy = "name_natural",
}: {
  accessToken: string;
  signal: AbortSignal;
  pageToken?: string;
  orderBy?: DriveSort;
}): Promise<{ items: DriveItem[]; nextPageToken?: string }> {
  const params: Record<string, string> = {
    q: `sharedWithMe and trashed = false and mimeType = '${FOLDER_MIME_TYPE}'`,
    fields: "nextPageToken,files(id,name,mimeType,driveId)",
    pageSize: String(PAGE_SIZE),
    orderBy,
    spaces: "drive",
    supportsAllDrives: "true",
    includeItemsFromAllDrives: "true",
  };
  if (pageToken) params.pageToken = pageToken;
  const payload = (await fetchDriveJson(
    driveApiUrl("/files", params),
    accessToken,
    signal,
  )) as DriveListPayload;
  return {
    items: Array.isArray(payload.files)
      ? payload.files
          .map((value) =>
            parseDriveItem(
              value,
              "output-folder",
              DEFAULT_SOURCE_MIME_POLICY,
            ),
          )
          .filter((item): item is DriveItem => item !== null)
      : [],
    nextPageToken:
      typeof payload.nextPageToken === "string" && payload.nextPageToken
        ? payload.nextPageToken
        : undefined,
  };
}

async function loadSharedDrivePage({
  accessToken,
  signal,
  pageToken,
}: {
  accessToken: string;
  signal: AbortSignal;
  pageToken?: string;
}): Promise<{ items: DriveItem[]; nextPageToken?: string }> {
  const params: Record<string, string> = {
    fields: "nextPageToken,drives(id,name)",
    pageSize: String(PAGE_SIZE),
  };
  if (pageToken) params.pageToken = pageToken;
  const payload = (await fetchDriveJson(
    driveApiUrl("/drives", params),
    accessToken,
    signal,
  )) as SharedDrivePayload;
  return {
    items: Array.isArray(payload.drives)
      ? payload.drives
          .map(parseSharedDrive)
          .filter((item): item is DriveItem => item !== null)
      : [],
    nextPageToken:
      typeof payload.nextPageToken === "string" && payload.nextPageToken
        ? payload.nextPageToken
        : undefined,
  };
}

function isAbort(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === "AbortError";
}

function uniqueItems(items: DriveItem[]): DriveItem[] {
  const unique = new Map<string, DriveItem>();
  items.forEach((item) => unique.set(item.id, item));
  return [...unique.values()];
}

function pageFromResult(result: {
  items: DriveItem[];
  nextPageToken?: string;
}): DrivePage {
  return {
    items: uniqueItems(result.items),
    nextPageToken: result.nextPageToken,
    pagesLoaded: 1,
    usedPageTokens: [],
  };
}

function appendPage(
  current: DrivePage,
  pageToken: string,
  result: { items: DriveItem[]; nextPageToken?: string },
): DrivePage {
  return {
    items: uniqueItems([...current.items, ...result.items]),
    nextPageToken: result.nextPageToken,
    pagesLoaded: current.pagesLoaded + 1,
    usedPageTokens: [...current.usedPageTokens, pageToken],
  };
}

function pickerCopy(mode: AppOwnedDrivePickerMode): {
  title: string;
  description: string;
  closeLabel: string;
  searchLabel: string;
  searchPlaceholder: string;
} {
  if (mode === "sources") {
    return {
      title: "Выберите аудио или видео",
      description:
        "Откройте папку, отметьте до 50 поддерживаемых файлов и подтвердите выбор.",
      closeLabel: "Закрыть выбор файлов",
      searchLabel: "Поиск файлов по началу названия",
      searchPlaceholder: "Например, Интервью",
    };
  }
  if (mode === "source-folder") {
    return {
      title: "Выберите папку с аудио или видео",
      description:
        "Откройте нужную папку и подтвердите текущую папку кнопкой ниже.",
      closeLabel: "Закрыть выбор исходной папки",
      searchLabel: "Поиск папок по началу названия",
      searchPlaceholder: "Например, Записи встреч",
    };
  }
  if (mode === "transcript-folder") {
    return {
      title: "Выберите папку с транскриптами",
      description:
        "Откройте папку, которую нужно проверить вместе со всеми подпапками, и подтвердите её кнопкой ниже.",
      closeLabel: "Закрыть выбор папки с транскриптами",
      searchLabel: "Поиск папок с транскриптами по началу названия",
      searchPlaceholder: "Например, Созвоны",
    };
  }
  if (mode === "transcript-document") {
    return {
      title: "Выберите Google Doc с транскриптом",
      description:
        "Откройте нужную папку, выберите один Google Doc и подтвердите выбор.",
      closeLabel: "Закрыть выбор Google Doc",
      searchLabel: "Поиск Google Docs по началу названия",
      searchPlaceholder: "Например, Синк с разработкой",
    };
  }
  return {
    title: "Выберите папку для результатов",
    description:
      "Откройте нужную папку и подтвердите текущую папку кнопкой ниже.",
    closeLabel: "Закрыть выбор папки",
    searchLabel: "Поиск папок по началу названия",
    searchPlaceholder: "Например, Готовые транскрипты",
  };
}

function GoogleDrivePickerDialog({
  mode,
  accessToken,
  sourceMimePolicy,
  returnFocusTo,
  onSelect,
  onCancel,
  onFatalError,
}: {
  mode: AppOwnedDrivePickerMode;
  accessToken: string;
  sourceMimePolicy?: DriveSourceMimePolicy;
  returnFocusTo?: HTMLElement | null;
  onSelect: (items: DriveItem[]) => void;
  onCancel: () => void;
  onFatalError: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const searchId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const requestEpochRef = useRef(0);
  const policy = useMemo(
    () => normalizeMimePolicy(sourceMimePolicy),
    [sourceMimePolicy],
  );
  const copy = pickerCopy(mode);
  const [sort, setSort] = useState<DriveSort>("name_natural");
  const [current, setCurrent] = useState<DriveItem | null>(null);
  const [path, setPath] = useState<DriveItem[]>([]);
  const [browsePage, setBrowsePage] = useState<DrivePage>(EMPTY_PAGE);
  const [sharedFolderPage, setSharedFolderPage] =
    useState<DrivePage>(EMPTY_PAGE);
  const [sharedDrivePage, setSharedDrivePage] =
    useState<DrivePage>(EMPTY_PAGE);
  const [searchPage, setSearchPage] = useState<DrivePage>(EMPTY_PAGE);
  const [selected, setSelected] = useState<Map<string, DriveItem>>(new Map());
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState<
    "browse" | "search" | "shared-folders" | "shared-drives" | null
  >(null);
  const [error, setError] = useState("");
  const [searchError, setSearchError] = useState("");

  useEffect(() => {
    returnFocusRef.current = returnFocusTo ?? (
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null);
    cancelRef.current?.focus();
    const controller = new AbortController();
    requestRef.current = controller;
    const epoch = ++requestEpochRef.current;
    void (async () => {
      try {
        const root = await loadRootFolder(accessToken, controller.signal);
        if (controller.signal.aborted || epoch !== requestEpochRef.current) {
          return;
        }
        setCurrent(root);
        setPath([root]);
        const [children, shared, drives] = await Promise.allSettled([
          loadItemPage({
            parent: root,
            mode,
            policy,
            accessToken,
            signal: controller.signal,
          }),
          loadSharedFolderPage({ accessToken, signal: controller.signal }),
          loadSharedDrivePage({ accessToken, signal: controller.signal }),
        ]);
        if (controller.signal.aborted || epoch !== requestEpochRef.current) {
          return;
        }
        const unavailable: string[] = [];
        if (children.status === "fulfilled") {
          setBrowsePage(pageFromResult(children.value));
        } else {
          unavailable.push("содержимое текущей папки");
        }
        if (shared.status === "fulfilled") {
          setSharedFolderPage(pageFromResult(shared.value));
        } else {
          unavailable.push("доступные мне папки");
        }
        if (drives.status === "fulfilled") {
          setSharedDrivePage(pageFromResult(drives.value));
        } else {
          unavailable.push("общие диски");
        }
        setError(
          unavailable.length > 0
            ? mode === "sources"
              ? `Не удалось загрузить: ${unavailable.join(", ")}. Повторите попытку или используйте поиск.`
              : `Не удалось загрузить: ${unavailable.join(", ")}. Текущую папку всё равно можно выбрать.`
            : "",
        );
        setLoading(false);
        setInitialized(true);
      } catch (reason) {
        if (
          controller.signal.aborted ||
          epoch !== requestEpochRef.current ||
          isAbort(reason)
        ) {
          return;
        }
        onFatalError();
      }
    })();
    return () => {
      controller.abort();
      const target = returnFocusRef.current;
      if (target?.isConnected && !target.matches(":disabled")) target.focus();
    };
  }, [accessToken, mode, onFatalError, policy, returnFocusTo]);

  const visitFolder = (folder: DriveItem, nextPath: DriveItem[]) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const epoch = ++requestEpochRef.current;
    setCurrent(folder);
    setPath(nextPath);
    setSearchInput("");
    setSearchTerm("");
    setSearchPage(EMPTY_PAGE);
    setSearchError("");
    setBrowsePage(EMPTY_PAGE);
    setError("");
    setLoading(true);
    window.requestAnimationFrame(() => {
      dialogRef.current?.querySelector<HTMLButtonElement>(".google-drive-folder-breadcrumbs button:last-child")?.focus();
    });
    void loadItemPage({
      parent: folder,
      mode,
      policy,
      orderBy: sort,
      accessToken,
      signal: controller.signal,
    }).then(
      (result) => {
        if (controller.signal.aborted || epoch !== requestEpochRef.current) {
          return;
        }
        setBrowsePage(pageFromResult(result));
        setLoading(false);
      },
      (reason) => {
        if (
          controller.signal.aborted ||
          epoch !== requestEpochRef.current ||
          isAbort(reason)
        ) {
          return;
        }
        setError(
          "Не удалось загрузить содержимое. Текущую папку всё равно можно выбрать.",
        );
        setLoading(false);
      },
    );
  };

  const clearSearch = () => {
    requestRef.current?.abort();
    requestEpochRef.current += 1;
    setSearchInput("");
    setSearchTerm("");
    setSearchPage(EMPTY_PAGE);
    setSearchError("");
    setSearchLoading(false);
  };

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const term = searchInput.trim().slice(0, 256);
    if (!term) {
      clearSearch();
      return;
    }
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const epoch = ++requestEpochRef.current;
    setSearchTerm(term);
    setSearchPage(EMPTY_PAGE);
    setSearchError("");
    setSearchLoading(true);
    void loadItemPage({
      searchTerm: term,
      mode,
      policy,
      orderBy: sort,
      accessToken,
      signal: controller.signal,
    }).then(
      (result) => {
        if (controller.signal.aborted || epoch !== requestEpochRef.current) {
          return;
        }
        setSearchPage(pageFromResult(result));
        setSearchLoading(false);
      },
      (reason) => {
        if (
          controller.signal.aborted ||
          epoch !== requestEpochRef.current ||
          isAbort(reason)
        ) {
          return;
        }
        setSearchError("Не удалось выполнить поиск. Повторите попытку.");
        setSearchLoading(false);
      },
    );
  };

  const changeSort = async (orderBy: DriveSort) => {
    if (!current) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const epoch = ++requestEpochRef.current;
    setSort(orderBy);
    setLoading(true);
    setSearchLoading(Boolean(searchTerm));
    setLoadingMore(null);
    setBrowsePage(EMPTY_PAGE);
    setSearchPage(EMPTY_PAGE);
    setSharedFolderPage(EMPTY_PAGE);
    setError("");
    setSearchError("");
    const results = await Promise.allSettled([
      loadItemPage({ parent: current, mode, policy, accessToken, orderBy, signal: controller.signal }),
      loadSharedFolderPage({ accessToken, orderBy, signal: controller.signal }),
      searchTerm ? loadItemPage({ searchTerm, mode, policy, accessToken, orderBy, signal: controller.signal }) : Promise.resolve(null),
    ]);
    if (controller.signal.aborted || epoch !== requestEpochRef.current) return;
    const [children, shared, search] = results;
    if (children.status === "fulfilled") setBrowsePage(pageFromResult(children.value));
    if (shared.status === "fulfilled") setSharedFolderPage(pageFromResult(shared.value));
    if (children.status === "rejected" || shared.status === "rejected") setError("Не удалось обновить порядок папок. Повторите выбор сортировки.");
    if (search.status === "fulfilled" && search.value) setSearchPage(pageFromResult(search.value));
    if (search.status === "rejected") setSearchError("Не удалось обновить результаты поиска. Повторите поиск.");
    setLoading(false);
    setSearchLoading(false);
  };

  const loadMore = async (
    kind: "browse" | "search" | "shared-folders" | "shared-drives",
  ) => {
    const state =
      kind === "browse"
        ? browsePage
        : kind === "search"
          ? searchPage
          : kind === "shared-folders"
            ? sharedFolderPage
            : sharedDrivePage;
    const token = state.nextPageToken;
    if (
      !token ||
      state.pagesLoaded >= MAX_LIST_PAGES ||
      state.usedPageTokens.includes(token) ||
      loadingMore
    ) {
      if (state.usedPageTokens.includes(token ?? "")) {
        const message = "Google Drive повторил token страницы. Уточните поиск.";
        if (kind === "search") setSearchError(message);
        else setError(message);
      }
      return;
    }
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const epoch = ++requestEpochRef.current;
    setLoadingMore(kind);
    if (kind === "search") setSearchError("");
    else setError("");
    try {
      const result =
        kind === "shared-folders"
          ? await loadSharedFolderPage({
              orderBy: sort,
              accessToken,
              signal: controller.signal,
              pageToken: token,
            })
          : kind === "shared-drives"
            ? await loadSharedDrivePage({
                accessToken,
                signal: controller.signal,
                pageToken: token,
              })
            : await loadItemPage({
                parent: kind === "browse" ? current ?? undefined : undefined,
                searchTerm: kind === "search" ? searchTerm : undefined,
                mode,
                policy,
                orderBy: sort,
                accessToken,
                signal: controller.signal,
                pageToken: token,
              });
      if (controller.signal.aborted || epoch !== requestEpochRef.current) {
        return;
      }
      const update = (currentPage: DrivePage) =>
        appendPage(currentPage, token, result);
      if (kind === "browse") setBrowsePage(update);
      else if (kind === "search") setSearchPage(update);
      else if (kind === "shared-folders") setSharedFolderPage(update);
      else setSharedDrivePage(update);
    } catch (reason) {
      if (
        controller.signal.aborted ||
        epoch !== requestEpochRef.current ||
        isAbort(reason)
      ) {
        return;
      }
      const message = "Не удалось загрузить следующую страницу.";
      if (kind === "search") setSearchError(message);
      else setError(message);
    } finally {
      if (!controller.signal.aborted && epoch === requestEpochRef.current) {
        setLoadingMore(null);
      }
    }
  };

  const toggleFile = (file: DriveItem) => {
    setSelected((currentSelection) => {
      const next = new Map(currentSelection);
      if (next.has(file.id)) {
        next.delete(file.id);
      } else if (mode === "transcript-document") {
        next.clear();
        next.set(file.id, file);
      } else if (next.size < MAX_SOURCE_SELECTIONS) {
        next.set(file.id, file);
      }
      return next;
    });
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const controls = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), select:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
    if (controls.length === 0) {
      event.preventDefault();
      return;
    }
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const atRoot = path.length === 1;
  const activePage = searchTerm ? searchPage : browsePage;
  const activeLoading = searchTerm ? searchLoading : loading;
  const folders = activePage.items.filter(
    (item) => item.mimeType === FOLDER_MIME_TYPE,
  );
  const files = activePage.items.filter(
    (item) => item.mimeType !== FOLDER_MIME_TYPE,
  );
  const hasVisibleItems =
    activePage.items.length > 0 ||
    (!searchTerm &&
      atRoot &&
      (sharedFolderPage.items.length > 0 || sharedDrivePage.items.length > 0));

  const renderFolderButton = (
    folder: DriveItem,
    nextPath: DriveItem[],
    keyPrefix: string,
  ) => (
    <li key={`${keyPrefix}:${folder.id}`}>
      <button
        type="button"
        className="google-drive-folder-row"
        onClick={() => visitFolder(folder, nextPath)}
        aria-label={`Открыть папку «${folder.name}»`}
      >
        <span aria-hidden="true">📁</span>
        <span>{folder.name}</span>
        <span className="google-drive-picker-row-action" aria-hidden="true">
          Открыть
        </span>
      </button>
    </li>
  );

  const renderLoadMore = (
    page: DrivePage,
    kind: "browse" | "search" | "shared-folders" | "shared-drives",
  ) => {
    if (!page.nextPageToken) return null;
    if (page.pagesLoaded >= MAX_LIST_PAGES) {
      return (
        <p className="notice">
          Достигнут лимит просмотра. Уточните поиск по началу названия.
        </p>
      );
    }
    return (
      <button
        type="button"
        className="secondary google-drive-picker-load-more"
        disabled={loadingMore !== null}
        onClick={() => void loadMore(kind)}
      >
        {loadingMore === kind ? "Загружаем…" : "Загрузить ещё"}
      </button>
    );
  };

  return (
    <div className="confirm-clear-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="card google-drive-folder-picker-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={activeLoading || loadingMore !== null || undefined}
        data-studio-scroll-lock-allow="true"
        onKeyDown={handleKeyDown}
      >
        <header className="google-drive-folder-picker-header">
          <div>
            <h2 id={titleId}>{copy.title}</h2>
            <p id={descriptionId}>{copy.description}</p>
          </div>
          <button
            ref={cancelRef}
            type="button"
            className="secondary"
            onClick={onCancel}
            aria-label={copy.closeLabel}
          >
            Закрыть
          </button>
        </header>

        <div className="google-drive-picker-controls">
          <form
            className="google-drive-picker-search"
            role="search"
            onSubmit={submitSearch}
          >
            <label htmlFor={searchId}>{copy.searchLabel}</label>
            <div>
              <input
                id={searchId}
                type="search"
                value={searchInput}
                maxLength={256}
                placeholder={copy.searchPlaceholder}
                disabled={current === null || loading}
                onChange={(event) => setSearchInput(event.target.value)}
              />
              <button
                type="submit"
                className="secondary"
                disabled={current === null || loading}
              >
                Найти
              </button>
              {searchTerm && (
                <button type="button" className="secondary" onClick={clearSearch} disabled={loading || searchLoading}>
                  Сбросить
                </button>
              )}
            </div>
            <small>
              Google Drive ищет по началу имени среди доступных объектов.
            </small>
          </form>

          <label className="google-drive-picker-sort">Сортировка папок и файлов
            <select value={sort} disabled={!current || !initialized} onChange={(event) => void changeSort(event.target.value as DriveSort)}>
              <option value="name_natural">По имени: А → Я</option>
              <option value="name_natural desc">По имени: Я → А</option>
              <option value="modifiedTime desc,name_natural">По обновлению: сначала новые</option>
              <option value="modifiedTime,name_natural">По обновлению: сначала старые</option>
            </select>
          </label>
        </div>

        <nav className="google-drive-folder-breadcrumbs" aria-label="Путь">
          {path.map((folder, index) => (
            <button
              type="button"
              key={`${folder.id}:${index}`}
              className="secondary"
              aria-current={index === path.length - 1 ? "page" : undefined}
              disabled={index === path.length - 1 && !searchTerm}
              onClick={() => visitFolder(folder, path.slice(0, index + 1))}
            >
              {folder.name}
            </button>
          ))}
        </nav>

        <div className="google-drive-folder-picker-content">
          {activeLoading && (
            <p role="status">
              {searchTerm
                ? "Ищем в Google Drive…"
                : "Загружаем содержимое Google Drive…"}
            </p>
          )}
          {!searchTerm && error && <p role="alert">{error}</p>}
          {searchTerm && searchError && <p role="alert">{searchError}</p>}
          {!activeLoading && !hasVisibleItems && (
            <p className="notice">
              {searchTerm
                ? "Ничего не найдено. Проверьте начало названия."
                : mode === "sources"
                  ? "Внутри нет поддерживаемых аудио или видео."
                  : mode === "transcript-document"
                    ? "Внутри нет Google Docs. Откройте другую папку или используйте поиск."
                  : "Внутри нет папок. Текущую папку можно выбрать."}
            </p>
          )}
          {searchTerm && (
            <p className="google-drive-picker-search-summary" role="status">
              Результаты по запросу «{searchTerm}»
            </p>
          )}
          {folders.length > 0 && (
            <section aria-labelledby={`${titleId}-folders`}>
              <h3 id={`${titleId}-folders`}>Папки</h3>
              <ul className="google-drive-folder-list">
                {folders.map((folder) =>
                  renderFolderButton(
                    folder,
                    searchTerm ? [folder] : [...path, folder],
                    searchTerm ? "search-folder" : "folder",
                  ),
                )}
              </ul>
            </section>
          )}
          {(mode === "sources" || mode === "transcript-document") && files.length > 0 && (
            <section aria-labelledby={`${titleId}-files`}>
              <h3 id={`${titleId}-files`}>
                {mode === "sources" ? "Аудио и видео" : "Google Docs"}
              </h3>
              <ul className="google-drive-folder-list">
                {files.map((file) => {
                  const checked = selected.has(file.id);
                  return (
                    <li key={`file:${file.id}`}>
                      <button
                        type="button"
                        className="google-drive-folder-row google-drive-file-row"
                        aria-pressed={checked}
                        aria-label={`${checked ? "Убрать" : "Выбрать"} файл «${file.name}»`}
                        disabled={
                          mode === "sources" &&
                          !checked &&
                          selected.size >= MAX_SOURCE_SELECTIONS
                        }
                        onClick={() => toggleFile(file)}
                      >
                        <span aria-hidden="true">
                          {mode === "sources" ? "🎧" : "📄"}
                        </span>
                        <span>
                          <strong>{file.name}</strong>
                          <small>{file.mimeType}</small>
                        </span>
                        <span className="google-drive-picker-row-action" aria-hidden="true">
                          {checked ? "Выбрано" : "Выбрать"}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
          {renderLoadMore(activePage, searchTerm ? "search" : "browse")}
          {!searchTerm && atRoot && sharedDrivePage.items.length > 0 && (
            <section aria-labelledby={`${titleId}-drives`}>
              <h3 id={`${titleId}-drives`}>Общие диски</h3>
              <ul className="google-drive-folder-list">
                {sharedDrivePage.items.map((folder) =>
                  renderFolderButton(folder, [folder], "drive"),
                )}
              </ul>
              {renderLoadMore(sharedDrivePage, "shared-drives")}
            </section>
          )}
          {!searchTerm && atRoot && sharedFolderPage.items.length > 0 && (
            <section aria-labelledby={`${titleId}-shared`}>
              <h3 id={`${titleId}-shared`}>Доступные мне папки</h3>
              <ul className="google-drive-folder-list">
                {sharedFolderPage.items.map((folder) =>
                  renderFolderButton(folder, [folder], "shared"),
                )}
              </ul>
              {renderLoadMore(sharedFolderPage, "shared-folders")}
            </section>
          )}
        </div>

        {(mode === "sources" || mode === "transcript-document") && selected.size > 0 && (
          <section
            className="google-drive-picker-selection"
            aria-label="Выбранные файлы"
          >
            <div>
              <strong>
                {mode === "sources"
                  ? `Выбрано: ${selected.size} из ${MAX_SOURCE_SELECTIONS}`
                  : "Выбран один Google Doc"}
              </strong>
              <button
                type="button"
                className="secondary"
                onClick={() => setSelected(new Map())}
              >
                Очистить
              </button>
            </div>
            <ul>
              {[...selected.values()].map((file) => (
                <li key={`selected:${file.id}`}>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => toggleFile(file)}
                    aria-label={`Убрать файл «${file.name}»`}
                  >
                    {file.name} ×
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <footer className="actions google-drive-folder-picker-actions">
          {mode === "sources" || mode === "transcript-document" ? (
            <button
              type="button"
              className="primary"
              disabled={selected.size === 0}
              onClick={() => onSelect([...selected.values()])}
            >
              {mode === "sources"
                ? `Добавить выбранные файлы (${selected.size})`
                : "Выбрать Google Doc"}
            </button>
          ) : (
            <button
              type="button"
              className="primary"
              disabled={current === null}
              onClick={() => current && onSelect([current])}
            >
              Выбрать эту папку
            </button>
          )}
          <span className="muted">
            {current
              ? mode === "transcript-document"
                ? `Открытая папка: ${current.name}`
                : `Текущая папка: ${current.name}`
              : "Загрузка…"}
          </span>
        </footer>
      </section>
    </div>
  );
}

export function openGoogleDrivePicker(
  mode: AppOwnedDrivePickerMode,
  session: PickerSession,
  sourceMimePolicy?: DriveSourceMimePolicy,
  returnFocusTo?: HTMLElement | null,
): Promise<PickerResult> {
  let token = session.access_token;
  session.access_token = "";
  if (!token.trim()) {
    token = "";
    return Promise.resolve({
      action: "error",
      message: "Google Picker недоступен",
    });
  }
  const host = document.createElement("div");
  host.dataset.studioGoogleDriveFolderPicker = "true";
  document.body.appendChild(host);
  const root = createRoot(host);
  const releaseDocumentScroll = lockDocumentScroll();

  return new Promise((resolve) => {
    let completed = false;
    const finish = (result: PickerResult) => {
      if (completed) return;
      completed = true;
      window.clearTimeout(timeout);
      queueMicrotask(() => {
        root.unmount();
        host.remove();
        releaseDocumentScroll();
        token = "";
        resolve(result);
        if (returnFocusTo) {
          window.setTimeout(() => {
            if (!returnFocusTo.isConnected) return;
            if (!returnFocusTo.matches(":disabled")) {
              returnFocusTo.focus();
              return;
            }
            // The caller may release its busy state after React commits.
            const observer = new MutationObserver(() => {
              if (!returnFocusTo.isConnected) {
                observer.disconnect();
              } else if (!returnFocusTo.matches(":disabled")) {
                observer.disconnect();
                returnFocusTo.focus();
              }
            });
            observer.observe(returnFocusTo, { attributes: true, attributeFilter: ["disabled"] });
            window.setTimeout(() => observer.disconnect(), 1000);
          }, 0);
        }
      });
    };
    const timeout = window.setTimeout(
      () =>
        finish({
          action: "error",
          message: "Время выбора в Google Drive истекло. Повторите попытку.",
        }),
      INTERACTION_TIMEOUT_MS,
    );
    root.render(
      <GoogleDrivePickerDialog
        mode={mode}
        accessToken={token}
        sourceMimePolicy={sourceMimePolicy}
        returnFocusTo={returnFocusTo}
        onSelect={(items) =>
          finish({
            action: "picked",
            docs: items.map((item) => ({
              id: item.id,
              name: item.name,
              mimeType: item.mimeType,
            })),
          })
        }
        onCancel={() => finish({ action: "cancel" })}
        onFatalError={() =>
          finish({
            action: "error",
            message:
              "Не удалось загрузить Google Drive. Переподключите Drive или повторите попытку.",
          })
        }
      />,
    );
  });
}
