import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  apiResponse,
  mutateWithCsrfRetry,
} from "./apiClient";
import type { TranscriptionJob } from "./jobModel";
import {
  parseSpeakerProfile,
  requestSpeakerProfiles,
  type SpeakerProfile,
} from "./speakerIdentityContracts";

export function SpeakerIdentityPanel({
  job,
  csrf,
  onCsrf,
  onJobUpdated,
}: {
  job: TranscriptionJob;
  csrf: string;
  onCsrf: (csrf: string) => void;
  onJobUpdated: () => void | Promise<void>;
}) {
  const speakers = job.speaker_identities ?? EMPTY_SPEAKERS;
  const [open, setOpen] = useState(false);
  const [profiles, setProfiles] = useState<SpeakerProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [selectedProfiles, setSelectedProfiles] = useState<Record<string, string>>(
    () => Object.fromEntries(
      speakers
        .filter((speaker) => speaker.profile)
        .map((speaker) => [speaker.id, speaker.profile?.id ?? ""]),
    ),
  );
  const [sampleUrls, setSampleUrls] = useState<Record<string, string>>({});
  const sampleUrlsRef = useRef(sampleUrls);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    requestSpeakerProfiles(controller.signal)
      .then((rows) => setProfiles(rows))
      .catch((caught) => {
        if (!(caught instanceof DOMException && caught.name === "AbortError")) {
          setError("Не удалось загрузить базу спикеров.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open]);

  sampleUrlsRef.current = sampleUrls;
  useEffect(() => () => {
    for (const url of Object.values(sampleUrlsRef.current)) URL.revokeObjectURL(url);
  }, []);

  if (job.status !== "completed" || !job.diarization_enabled || speakers.length === 0) {
    return null;
  }

  async function reloadProfiles() {
    const rows = await requestSpeakerProfiles();
    setProfiles(rows);
  }

  async function createProfile(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending("create"); setError(""); setMessage("");
    try {
      const candidate = await mutateWithCsrfRetry<unknown>(
        "/speaker-profiles",
        csrf,
        onCsrf,
        { method: "POST", body: JSON.stringify({ display_name: name, role }) },
      );
      const created = parseSpeakerProfile(candidate);
      if (!created || !created.active) throw new Error("invalid_speaker_profile");
      setName(""); setRole("");
      await reloadProfiles();
      setMessage("Профиль спикера сохранён.");
    } catch {
      setError("Не удалось сохранить профиль. Проверьте имя и роль.");
    } finally {
      setPending("");
    }
  }

  async function saveProfile(profileId: string) {
    if (pending) return;
    setPending(`edit:${profileId}`); setError(""); setMessage("");
    try {
      const candidate = await mutateWithCsrfRetry<unknown>(
        `/speaker-profiles/${profileId}`,
        csrf,
        onCsrf,
        { method: "PATCH", body: JSON.stringify({ display_name: editName, role: editRole }) },
      );
      if (!parseSpeakerProfile(candidate)) throw new Error("invalid_speaker_profile");
      setEditingId(null);
      await reloadProfiles();
      setMessage("Профиль спикера обновлён. Уже подписанные документы не изменены.");
    } catch {
      setError("Не удалось обновить профиль.");
    } finally {
      setPending("");
    }
  }

  async function deactivateProfile(profileId: string) {
    if (pending) return;
    setPending(`delete:${profileId}`); setError(""); setMessage("");
    try {
      await mutateWithCsrfRetry<unknown>(
        `/speaker-profiles/${profileId}`,
        csrf,
        onCsrf,
        { method: "DELETE" },
      );
      setConfirmDeleteId(null);
      await reloadProfiles();
      setMessage("Профиль спикера удалён из активной базы.");
    } catch {
      setError("Не удалось удалить профиль.");
    } finally {
      setPending("");
    }
  }

  async function loadSample(speakerId: string) {
    if (pending) return;
    setPending(`sample:${speakerId}`); setError(""); setMessage("");
    try {
      const response = await apiResponse(
        `/jobs/${job.id}/speakers/${speakerId}/sample`,
        { cache: "no-store" },
      );
      const contentType = response.headers.get("content-type") ?? "";
      const blob = await response.blob();
      if (!contentType.startsWith("audio/") || blob.size <= 0 || blob.size > 2_097_152) {
        throw new Error("invalid_speaker_sample");
      }
      const url = URL.createObjectURL(blob);
      setSampleUrls((current) => {
        if (current[speakerId]) URL.revokeObjectURL(current[speakerId]);
        return { ...current, [speakerId]: url };
      });
      setMessage("Фрагмент готов к прослушиванию и не сохраняется в профиле.");
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status === 410
          ? "Исходный файл уже удалён, поэтому фрагмент недоступен."
          : "Не удалось загрузить фрагмент голоса.",
      );
    } finally {
      setPending("");
    }
  }

  async function assignProfile(speakerId: string) {
    const profileId = selectedProfiles[speakerId];
    if (!profileId || pending) return;
    setPending(`assign:${speakerId}`); setError(""); setMessage("");
    try {
      const candidate = await mutateWithCsrfRetry<unknown>(
        `/jobs/${job.id}/speakers/${speakerId}/assignment`,
        csrf,
        onCsrf,
        { method: "PUT", body: JSON.stringify({ profile_id: profileId }) },
      );
      if (!isExpectedAssignment(candidate, speakerId, profileId)) {
        throw new Error("invalid_speaker_assignment");
      }
      await onJobUpdated();
      setMessage("Имя и роль применены к Google Docs и истории транскрибации.");
    } catch {
      setError("Не удалось применить профиль. Документ мог быть изменён вручную.");
    } finally {
      setPending("");
    }
  }

  return (
    <section className="speaker-identity-panel" aria-label={`Идентификация спикеров ${job.id}`}>
      <h3 className="job-detail-subheading">Идентификация спикеров</h3>
      {!open ? (
        <button type="button" className="secondary" onClick={() => setOpen(true)}>
          Настроить имена спикеров
        </button>
      ) : (
        <>
          <p className="muted">
            Идентификация выполняется только вручную. Голосовые фрагменты не
            сохраняются в профилях.
          </p>
          {loading && <p role="status">Загрузка базы спикеров…</p>}
          <form onSubmit={createProfile} className="form-grid" aria-label="Новый профиль спикера">
            <label>
              Имя
              <input value={name} maxLength={160} required onChange={(event) => setName(event.target.value)} />
            </label>
            <label>
              Роль
              <input value={role} maxLength={120} required onChange={(event) => setRole(event.target.value)} />
            </label>
            <button type="submit" disabled={Boolean(pending)}>Добавить профиль</button>
          </form>

          {profiles.length > 0 && <h6>База имён и ролей</h6>}
          {profiles.map((profile) => (
            <article className="source-card" key={profile.id}>
              {editingId === profile.id ? (
                <>
                  <label>Имя<input value={editName} maxLength={160} onChange={(event) => setEditName(event.target.value)} /></label>
                  <label>Роль<input value={editRole} maxLength={120} onChange={(event) => setEditRole(event.target.value)} /></label>
                  <div className="resource-actions">
                    <button type="button" disabled={Boolean(pending)} onClick={() => void saveProfile(profile.id)}>Сохранить</button>
                    <button type="button" className="secondary" onClick={() => setEditingId(null)}>Отмена</button>
                  </div>
                </>
              ) : (
                <>
                  <b>{profile.display_name}</b><span>{profile.role}</span>
                  <div className="resource-actions">
                    <button type="button" className="secondary" onClick={() => { setEditingId(profile.id); setEditName(profile.display_name); setEditRole(profile.role); }}>Изменить</button>
                    {confirmDeleteId === profile.id ? (
                      <><span>Удалить профиль?</span><button type="button" onClick={() => void deactivateProfile(profile.id)}>Да</button><button type="button" className="secondary" onClick={() => setConfirmDeleteId(null)}>Нет</button></>
                    ) : (
                      <button type="button" className="secondary" onClick={() => setConfirmDeleteId(profile.id)}>Удалить</button>
                    )}
                  </div>
                </>
              )}
            </article>
          ))}

          <h6>Спикеры в транскрибации</h6>
          {speakers.map((speaker) => (
            <article className="source-card" key={speaker.id}>
              <b>{speaker.label}</b>
              <span>{speaker.profile ? `${speaker.profile.display_name} — ${speaker.profile.role}` : "Имя не назначено"}</span>
              <div className="resource-actions">
                <button type="button" className="secondary" disabled={!speaker.sample_available || Boolean(pending)} onClick={() => void loadSample(speaker.id)}>Прослушать фрагмент</button>
                <label>
                  Профиль
                  <select value={selectedProfiles[speaker.id] ?? ""} onChange={(event) => setSelectedProfiles((current) => ({ ...current, [speaker.id]: event.target.value }))}>
                    <option value="">Выберите имя и роль</option>
                    {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.display_name} — {profile.role}</option>)}
                  </select>
                </label>
                <button type="button" disabled={!selectedProfiles[speaker.id] || Boolean(pending)} onClick={() => void assignProfile(speaker.id)}>Применить к документу</button>
              </div>
              {sampleUrls[speaker.id] && <audio controls autoPlay preload="none" src={sampleUrls[speaker.id]}>Ваш браузер не поддерживает аудио.</audio>}
            </article>
          ))}
          {message && <p className="notice" role="status">{message}</p>}
          {error && <p className="error" role="alert">{error}</p>}
          <button type="button" className="secondary" onClick={() => setOpen(false)}>Свернуть</button>
        </>
      )}
    </section>
  );
}

const EMPTY_SPEAKERS: NonNullable<TranscriptionJob["speaker_identities"]> = [];

function isExpectedAssignment(candidate: unknown, speakerId: string, profileId: string) {
  if (!candidate || typeof candidate !== "object") return false;
  const speaker = (candidate as { speaker?: unknown }).speaker;
  if (!speaker || typeof speaker !== "object") return false;
  const row = speaker as { id?: unknown; profile?: unknown };
  if (row.id !== speakerId || !row.profile || typeof row.profile !== "object") return false;
  return (row.profile as { id?: unknown }).id === profileId;
}
