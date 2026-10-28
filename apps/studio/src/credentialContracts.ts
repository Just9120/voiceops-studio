import { api } from "./apiClient";
import { LATEST_REQUEST_CANCEL_REASON } from "./latestRequest";

export type Credential = {
  id: string;
  provider: "elevenlabs" | "yandex" | "openai" | "tbank" | "mistral" | "gemini";
  label: string;
  status: "active" | "revoked";
  masked_value: string | null;
  active_version: number | null;
  folder_id: string | null;
};

export function parseCredentialCollection(candidate: unknown): Credential[] | null {
  if (!candidate || typeof candidate !== "object") return null;
  const rawCredentials = (candidate as { credentials?: unknown }).credentials;
  if (!Array.isArray(rawCredentials)) return null;
  const credentials: Credential[] = [];
  for (const rawCredential of rawCredentials) {
    if (!rawCredential || typeof rawCredential !== "object") return null;
    const credential = rawCredential as Record<string, unknown>;
    if (
      typeof credential.id !== "string" ||
      credential.id.length === 0 ||
      credential.id.length > 36 ||
      (credential.provider !== "elevenlabs" &&
        credential.provider !== "yandex" &&
        credential.provider !== "openai" && credential.provider !== "tbank" && credential.provider !== "mistral" && credential.provider !== "gemini") ||
      typeof credential.label !== "string" ||
      credential.label.trim().length === 0 ||
      credential.label.length > 120 ||
      (credential.status !== "active" && credential.status !== "revoked") ||
      (credential.masked_value !== null &&
        (typeof credential.masked_value !== "string" ||
          credential.masked_value.length === 0 ||
          credential.masked_value.length > 80)) ||
      (credential.active_version !== null &&
        (!Number.isInteger(credential.active_version) ||
          (credential.active_version as number) <= 0)) ||
      (credential.folder_id !== null &&
        credential.folder_id !== undefined &&
        (typeof credential.folder_id !== "string" ||
          credential.folder_id.length === 0 ||
          credential.folder_id.length > 256))
    ) {
      return null;
    }
    credentials.push({
      id: credential.id,
      provider: credential.provider,
      label: credential.label,
      status: credential.status,
      masked_value: credential.masked_value,
      active_version: credential.active_version as number | null,
      folder_id: (credential.folder_id as string | null | undefined) ?? null,
    });
  }
  if (
    new Set(credentials.map((credential) => credential.id)).size !==
    credentials.length
  ) {
    return null;
  }
  return credentials;
}

export async function requestCredentialCollection(
  signal?: AbortSignal,
): Promise<Credential[]> {
  const candidate = await api<unknown>("/credentials", {
    signal,
    ignoredAbortReason: LATEST_REQUEST_CANCEL_REASON,
  });
  const credentials = parseCredentialCollection(candidate);
  if (credentials === null) throw new Error("invalid_credentials_response");
  return credentials;
}
