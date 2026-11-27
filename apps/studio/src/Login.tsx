import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./apiClient";
import { PublicInfoLinks } from "./PublicInfoLinks";
import {
  parseAuthenticatedLoginResponse,
  parseBootstrapStatusResponse,
  parseLoginContextResponse,
  type User,
} from "./authContracts";
import {
  cancelLatestRequests,
  LATEST_REQUEST_CANCEL_REASON,
  settleLatestRequest,
} from "./latestRequest";

const BOOTSTRAP_STATUS_TIMEOUT_MS = 15_000;
const LOGIN_ATTEMPT_TIMEOUT_MS = 20_000;

async function requestBootstrapStatus(signal?: AbortSignal): Promise<boolean> {
  const candidate = await api<unknown>("/auth/bootstrap-status", {
    signal,
    ignoredAbortReason: LATEST_REQUEST_CANCEL_REASON,
  });
  const bootstrapRequired = parseBootstrapStatusResponse(candidate);
  if (bootstrapRequired === null) {
    throw new Error("invalid_bootstrap_status_response");
  }
  return bootstrapRequired;
}

async function requestLogin(
  email: string,
  password: string,
  verificationCode: string,
  recoveryCode: string,
  signal?: AbortSignal,
): Promise<{ user: User; csrf: string }> {
  const contextCandidate = await api<unknown>("/auth/login-context", {
    method: "POST",
    signal,
    ignoredAbortReason: LATEST_REQUEST_CANCEL_REASON,
  });
  const loginCsrf = parseLoginContextResponse(contextCandidate);
  if (!loginCsrf) throw new Error("invalid_login_context_response");
  const responseCandidate = await api<unknown>("/auth/login", {
    method: "POST",
    signal,
    ignoredAbortReason: LATEST_REQUEST_CANCEL_REASON,
    body: JSON.stringify({
      email,
      password,
      login_csrf_token: loginCsrf,
      verification_code: verificationCode.trim() || undefined,
      recovery_code: recoveryCode.trim() || undefined,
    }),
  });
  const response = parseAuthenticatedLoginResponse(responseCandidate);
  if (!response) throw new Error("invalid_login_response");
  return response;
}

type BootstrapState = "checking" | "ready" | "required" | "error";

export function Login({
  onLogin,
}: {
  onLogin: (user: User, csrf: string) => void;
}) {
  const [bootstrap, setBootstrap] = useState<BootstrapState>("checking");
  const [error, setError] = useState("");
  const [loginPending, setLoginPending] = useState(false);
  const [secondFactorRequired, setSecondFactorRequired] = useState(false);
  const [recoveryCodeMode, setRecoveryCodeMode] = useState(false);
  const [recoveryInfo, setRecoveryInfo] = useState(false);
  const [rateLimited, setRateLimited] = useState(false);
  const factorInput = useRef<HTMLInputElement>(null);
  const loginPendingRef = useRef(false);
  const requestEpochsRef = useRef(new Map<string, number>());
  const requestControllersRef = useRef(new Map<string, AbortController>());

  const checkBootstrap = useCallback(() => {
    setError("");
    setBootstrap("checking");
    void settleLatestRequest(
      requestEpochsRef.current,
      "login:bootstrap-status",
      requestBootstrapStatus,
      (bootstrapRequired) =>
        setBootstrap(bootstrapRequired ? "required" : "ready"),
      () => {
        setBootstrap("error");
        setError("Не удалось проверить готовность входа. Повторите попытку.");
      },
      {
        controllers: requestControllersRef.current,
        timeoutMs: BOOTSTRAP_STATUS_TIMEOUT_MS,
      },
    );
  }, []);

  useEffect(() => {
    checkBootstrap();
    return () =>
      cancelLatestRequests(
        requestEpochsRef.current,
        requestControllersRef.current,
      );
  }, [checkBootstrap]);

  useEffect(() => {
    if (secondFactorRequired && !recoveryInfo) factorInput.current?.focus();
  }, [secondFactorRequired, recoveryCodeMode, recoveryInfo]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loginPendingRef.current) return;
    setError("");
    setRateLimited(false);
    const formData = new FormData(event.currentTarget);
    const email = String(formData.get("email") ?? "");
    const password = String(formData.get("password") ?? "");
    const verificationCode = String(formData.get("verificationCode") ?? "");
    const recoveryCode = String(formData.get("recoveryCode") ?? "");
    loginPendingRef.current = true;
    setLoginPending(true);
    await settleLatestRequest(
      requestEpochsRef.current,
      "login:submit",
      (signal) => requestLogin(email, password, verificationCode, recoveryCode, signal),
      (response) => {
        loginPendingRef.current = false;
        setLoginPending(false);
        onLogin(response.user, response.csrf);
      },
      (failure) => {
        loginPendingRef.current = false;
        setLoginPending(false);
        const detail =
          failure instanceof ApiError && failure.data && typeof failure.data === "object"
            ? (failure.data as { detail?: unknown }).detail
            : undefined;
        const reason = detail && typeof detail === "object" && "reason" in detail ? detail.reason : null;
        if (
          failure instanceof ApiError &&
          failure.status === 409 &&
          reason === "second_factor_required"
        ) {
          setSecondFactorRequired(true);
          setError("Введите код из приложения-аутентификатора или резервный код.");
          return;
        }
        if (
          failure instanceof ApiError &&
          failure.status === 401 &&
          (reason === "second_factor_invalid" || detail === "Не удалось подтвердить вход")
        ) {
          setSecondFactorRequired(true);
          setError("Неверный одноразовый или резервный код.");
          return;
        }
        setRateLimited(failure instanceof ApiError && failure.status === 429);
        setError(
          failure instanceof ApiError && failure.status === 401
            ? "Неверная почта или пароль."
            : failure instanceof ApiError && failure.status === 429
              ? "Слишком много попыток. Попробуйте позже."
              : "Не удалось войти. Проверьте данные и повторите.",
        );
      },
      {
        controllers: requestControllersRef.current,
        timeoutMs: LOGIN_ATTEMPT_TIMEOUT_MS,
      },
    );
  }

  if (bootstrap === "checking")
    return (
      <main className="auth">
        <section className="card" role="status">
          Проверяем готовность входа…
        </section>
      </main>
    );

  if (bootstrap === "error")
    return (
      <main className="auth">
        <section className="card">
          <p className="error" role="alert">{error}</p>
          <button type="button" className="primary" onClick={checkBootstrap}>
            Повторить
          </button>
        </section>
      </main>
    );

  if (bootstrap === "required")
    return (
      <main className="auth">
        <section className="card">
          <h1>Требуется первичная настройка</h1>
          <p className="notice">
            Публичной формы администратора нет. Обратитесь к оператору, чтобы
            выполнить bootstrap-admin команду на сервере.
          </p>
        </section>
      </main>
    );

  const title = recoveryInfo ? "Восстановление доступа"
    : rateLimited ? "Вход временно ограничен"
      : secondFactorRequired ? (recoveryCodeMode ? "Резервный код" : "Подтверждение входа")
        : "Вход в VoiceOps Studio";
  const intro = recoveryInfo ? "Выберите доступный для личного аккаунта способ."
    : secondFactorRequired ? "Второй шаг для аккаунта с включённой двухфакторной защитой."
      : "Введите данные личного аккаунта.";

  return (
    <main className="studio-login">
      <header className="studio-login-top">
        <img src="/icons/voiceops-brand.svg" width="32" height="32" alt="" />
        <strong>VoiceOps Studio</strong>
        <span className="app-personal-badge">Личный аккаунт</span>
      </header>
      <div className="studio-login-workspace">
        <div className="workspace-heading">
          <h1 className="page-title">{title}</h1>
          <p>{intro}</p>
        </div>
        {recoveryInfo ? (
          <>
            <section className="card studio-login-card">
              <h2>Вход с включённой 2FA</h2>
              <p>Введите пароль аккаунта. Затем на шаге подтверждения можно использовать ранее сохранённый резервный код.</p>
              <button type="button" onClick={() => {
                setRecoveryCodeMode(true);
                setRecoveryInfo(false);
              }}>Войти с резервным кодом</button>
            </section>
            <section className="card studio-login-card">
              <h2>Пароль утерян</h2>
              <p>Владелец может восстановить доступ через защищённую процедуру на сервере.</p>
            </section>
            <button type="button" onClick={() => setRecoveryInfo(false)}>Вернуться ко входу</button>
          </>
        ) : (
          <form className="card login studio-login-card" onSubmit={submit}>
            <div className="studio-login-fields" hidden={secondFactorRequired}>
              <label>
                Email
                <input name="email" type="email" autoComplete="username" required />
              </label>
              <label>
                Пароль
                <input name="password" type="password" autoComplete="current-password" required />
              </label>
            </div>
            {secondFactorRequired && (recoveryCodeMode ? (
              <>
                <label>
                  Резервный код
                  <input key="recovery" ref={factorInput} name="recoveryCode" autoComplete="off" required />
                </label>
                <p className="notice">Код одноразовый. После входа этот код будет использован.</p>
              </>
            ) : (
              <label>
                Одноразовый код
                <input key="totp" ref={factorInput} name="verificationCode" inputMode="numeric"
                  autoComplete="one-time-code" pattern="[0-9 ]{6,12}" required />
              </label>
            ))}
            {error && <p className="error" role="alert">{error}</p>}
            <div className="studio-login-actions">
              <button className="primary" disabled={loginPending}>
                {loginPending ? "Входим…" : secondFactorRequired ? "Подтвердить вход" : "Войти"}
              </button>
            </div>
            {secondFactorRequired ? (
              <div className="studio-login-controls">
                <button type="button" disabled={loginPending} onClick={() => {
                  setRecoveryCodeMode((current) => !current);
                  setError("");
                }}>{recoveryCodeMode ? "Использовать код из приложения" : "Использовать резервный код"}</button>
                <button type="button" disabled={loginPending} onClick={() => {
                  setSecondFactorRequired(false);
                  setRateLimited(false);
                  setError("");
                }}>Назад</button>
              </div>
            ) : (
              <>
                <button type="button" disabled={loginPending} onClick={() => setRecoveryInfo(true)}>Восстановить доступ</button>
                <PublicInfoLinks />
              </>
            )}
          </form>
        )}
      </div>
    </main>
  );
}
