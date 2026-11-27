import { type FormEvent, useEffect, useState } from "react";
import { ApiError, api, mutateWithCsrfRetry } from "./apiClient";

type SecurityStatus = {
  totp_enabled: boolean;
  totp_enrollment_pending: boolean;
  recent_auth_expires_at: string | null;
  password_reset_delivery: string;
  trusted_device_expires_at: string | null;
  trusted_device_count: number;
  trusted_device_supported: boolean;
};

type Enrollment = {
  secret: string;
  otpauth_uri: string;
  qr_svg_data_uri: string;
};

function parseStatus(value: unknown): SecurityStatus | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Partial<SecurityStatus>;
  if (
    typeof row.totp_enabled !== "boolean" ||
    typeof row.totp_enrollment_pending !== "boolean" ||
    (row.recent_auth_expires_at !== null &&
      typeof row.recent_auth_expires_at !== "string") ||
    typeof row.password_reset_delivery !== "string"
  ) return null;
  if (row.trusted_device_expires_at !== undefined &&
      row.trusted_device_expires_at !== null &&
      typeof row.trusted_device_expires_at !== "string") return null;
  if (row.trusted_device_count !== undefined &&
      (!Number.isInteger(row.trusted_device_count) || row.trusted_device_count < 0)) return null;
  return {
    ...row,
    trusted_device_expires_at: row.trusted_device_expires_at ?? null,
    trusted_device_count: row.trusted_device_count ?? 0,
    trusted_device_supported:
      row.trusted_device_expires_at !== undefined && row.trusted_device_count !== undefined,
  } as SecurityStatus;
}

function apiReason(error: unknown) {
  if (!(error instanceof ApiError) || !error.data || typeof error.data !== "object") return "";
  const detail = (error.data as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return "";
  const reason = (detail as { reason?: unknown }).reason;
  return typeof reason === "string" ? reason : "";
}

export function requestReauthentication(
  data: FormData,
  csrf: string,
  onCsrf: (csrf: string) => void,
  allowRememberDevice = false,
) {
  return mutateWithCsrfRetry("/auth/reauth", csrf, onCsrf, {
    method: "POST",
    body: JSON.stringify({
      password: String(data.get("password") ?? ""),
      verification_code: String(data.get("verificationCode") ?? "").trim() || undefined,
      recovery_code: String(data.get("recoveryCode") ?? "").trim() || undefined,
      ...(allowRememberDevice ? { remember_device: data.get("rememberDevice") === "on" } : {}),
    }),
  });
}

export function AccountSecurityPanel({
  csrf,
  onCsrf,
}: {
  csrf: string;
  onCsrf: (csrf: string) => void;
}) {
  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  async function load() {
    try {
      const next = parseStatus(await api<unknown>("/auth/security"));
      if (!next) throw new Error("invalid_security_status");
      setStatus(next);
    } catch {
      setMessage("Не удалось загрузить настройки защиты аккаунта.");
    }
  }

  useEffect(() => { void load(); }, []);

  async function reauthenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setPending(true); setMessage("");
    try {
      await requestReauthentication(data, csrf, onCsrf, status?.trusted_device_supported);
      form.reset();
      setMessage("Личность подтверждена. Теперь можно выполнить защищённое действие.");
      await load();
    } catch {
      setMessage("Не удалось подтвердить личность.");
    } finally {
      setPending(false);
    }
  }

  async function revokeDevice(allDevices: boolean) {
    if (pending) return;
    setPending(true); setMessage("");
    try {
      await mutateWithCsrfRetry("/auth/trusted-device/revoke", csrf, onCsrf, {
        method: "POST",
        body: JSON.stringify({ all_devices: allDevices }),
      });
      setMessage(allDevices ? "Доверие отозвано на всех устройствах." : "Доверие к этому браузеру отозвано.");
      await load();
    } catch {
      setMessage("Не удалось отозвать доверие. Повторите попытку.");
    } finally {
      setPending(false);
    }
  }

  async function mutate(path: string, options: RequestInit = { method: "POST" }) {
    if (pending) return null;
    setPending(true); setMessage("");
    try {
      return await mutateWithCsrfRetry<unknown>(path, csrf, onCsrf, options);
    } catch (error) {
      setMessage(
        apiReason(error) === "recent_reauthentication_required"
          ? "Сначала подтвердите личность паролем."
          : "Операция защиты не выполнена.",
      );
      return null;
    } finally {
      setPending(false);
    }
  }

  async function beginEnrollment() {
    const result = await mutate("/auth/totp/enroll");
    if (!result || typeof result !== "object") return;
    const candidate = result as Partial<Enrollment>;
    if (
      typeof candidate.secret !== "string" ||
      typeof candidate.otpauth_uri !== "string" ||
      typeof candidate.qr_svg_data_uri !== "string" ||
      !candidate.qr_svg_data_uri.startsWith("data:image/svg+xml;base64,")
    ) return;
    setEnrollment(candidate as Enrollment);
    setMessage("Добавьте ключ в приложение-аутентификатор и подтвердите код.");
  }

  async function confirmEnrollment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const result = await mutate("/auth/totp/confirm", {
      method: "POST",
      body: JSON.stringify({ verification_code: String(data.get("verificationCode") ?? "") }),
    });
    if (!result || typeof result !== "object") return;
    const codes = (result as { recovery_codes?: unknown }).recovery_codes;
    if (Array.isArray(codes) && codes.every((code) => typeof code === "string")) {
      setRecoveryCodes(codes);
      setEnrollment(null);
      setMessage("Двухфакторная защита включена. Сохраните резервные коды сейчас.");
      await load();
    }
  }

  async function rotateRecoveryCodes() {
    const result = await mutate("/auth/totp/recovery-codes");
    if (!result || typeof result !== "object") return;
    const codes = (result as { recovery_codes?: unknown }).recovery_codes;
    if (Array.isArray(codes) && codes.every((code) => typeof code === "string")) {
      setRecoveryCodes(codes);
      setMessage("Созданы новые резервные коды; прежние больше не действуют.");
    }
  }

  async function disable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const result = await mutate("/auth/totp", {
      method: "DELETE",
      body: JSON.stringify({
        verification_code: String(data.get("verificationCode") ?? "").trim() || undefined,
        recovery_code: String(data.get("recoveryCode") ?? "").trim() || undefined,
      }),
    });
    if (result) {
      setRecoveryCodes([]); setEnrollment(null);
      setMessage("Двухфакторная защита отключена; другие сессии завершены.");
      await load();
    }
  }

  return (
    <section className="card account-security" aria-labelledby="account-security-title">
      <h3 id="account-security-title">Защита аккаунта</h3>
      <p className="muted">
        Для ключей, подключения или отключения Google Drive, управления сессиями и очистки данных Studio просит заново подтвердить личность. Подтверждение действует недолго.
      </p>
      {status?.trusted_device_supported && (
        <p className="muted">Доверенный браузер позволяет выполнять операции с данными, Google Drive и ключами без повторного ввода пароля в течение 30 дней. Вход с двухфакторной защитой, изменение 2FA и управление сессиями всё равно требуют обычного подтверждения.</p>
      )}
      <form onSubmit={reauthenticate} className="security-form">
        <label>Пароль<input name="password" type="password" autoComplete="current-password" required /></label>
        {status?.totp_enabled && (
          <>
            <label>Код из приложения<input name="verificationCode" inputMode="numeric" autoComplete="one-time-code" /></label>
            <label>Или резервный код<input name="recoveryCode" autoComplete="off" /></label>
          </>
        )}
        {status?.trusted_device_supported && (
          <label><input name="rememberDevice" type="checkbox" /> Запомнить этот браузер на 30 дней</label>
        )}
        <button type="submit" disabled={pending}>Подтвердить личность</button>
      </form>
      {status?.trusted_device_expires_at && (
        <p>Этот браузер доверенный до {new Date(status.trusted_device_expires_at).toLocaleString("ru-RU")}.</p>
      )}
      {status?.trusted_device_expires_at && (
        <button type="button" disabled={pending} onClick={() => void revokeDevice(false)}>Забыть этот браузер</button>
      )}
      {(status?.trusted_device_count ?? 0) > 0 && (
        <button type="button" disabled={pending} onClick={() => void revokeDevice(true)}>Забыть все доверенные браузеры</button>
      )}
      {status && !status.totp_enabled && !enrollment && (
        <button type="button" onClick={() => void beginEnrollment()} disabled={pending}>Включить двухфакторную защиту</button>
      )}
      {enrollment && (
        <div className="security-enrollment">
          <p>Отсканируйте QR-код приложением-аутентификатором:</p>
          <img className="totp-qr" src={enrollment.qr_svg_data_uri} alt="QR-код для настройки TOTP" />
          <p><a href={enrollment.otpauth_uri}>Или открыть приложение-аутентификатор</a></p>
          <p>Секрет для TOTP-приложения:</p>
          <code>{enrollment.secret}</code>
          <form onSubmit={confirmEnrollment}>
            <label>Код подтверждения<input name="verificationCode" inputMode="numeric" autoComplete="one-time-code" required /></label>
            <button className="primary" disabled={pending}>Подтвердить и включить</button>
          </form>
        </div>
      )}
      {status?.totp_enabled && (
        <details>
          <summary>Управление резервными кодами и отключение</summary>
          <button type="button" onClick={() => void rotateRecoveryCodes()} disabled={pending}>Создать новые резервные коды</button>
          <form onSubmit={disable} className="security-form">
            <label>Одноразовый код<input name="verificationCode" inputMode="numeric" /></label>
            <label>Или резервный код<input name="recoveryCode" /></label>
            <button type="submit" className="danger" disabled={pending}>Отключить двухфакторную защиту</button>
          </form>
        </details>
      )}
      {recoveryCodes.length > 0 && (
        <div className="notice" role="status">
          <strong>Резервные коды показываются один раз:</strong>
          <ul className="recovery-codes">{recoveryCodes.map((code) => <li key={code}><code>{code}</code></li>)}</ul>
        </div>
      )}
      {message && <p role="status" className="notice">{message}</p>}
    </section>
  );
}
