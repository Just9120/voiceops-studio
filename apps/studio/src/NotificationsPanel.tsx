import { useEffect, useState } from "react";

import { ApiError, api, mutateWithCsrfRetry } from "./apiClient";

type NotificationChannel = {
  enabled: boolean;
  configured: boolean;
};

type WebPushChannel = NotificationChannel & {
  subscription_count: number;
  vapid_public_key: string | null;
};

type Delivery = {
  id: string;
  job_id: string;
  terminal_status: "completed" | "failed";
  channel: "web_push" | "email" | "telegram";
  state: "pending" | "claimed" | "delivered" | "failed" | "suppressed";
  attempt_count: number;
  error_code: string | null;
  created_at: string;
  delivered_at: string | null;
};

export type NotificationPreferences = {
  channels: {
    web_push: WebPushChannel;
    email: NotificationChannel;
    telegram: NotificationChannel;
  };
  recent_deliveries: Delivery[];
};

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

export function parseNotificationPreferences(
  candidate: unknown,
): NotificationPreferences | null {
  if (!candidate || typeof candidate !== "object") return null;
  const root = candidate as Record<string, unknown>;
  if (!root.channels || typeof root.channels !== "object") return null;
  const channels = root.channels as Record<string, unknown>;
  const webPush = channels.web_push as Record<string, unknown> | undefined;
  const email = channels.email as Record<string, unknown> | undefined;
  const telegram = channels.telegram as Record<string, unknown> | undefined;
  if (
    !webPush ||
    !email ||
    !telegram ||
    !isBoolean(webPush.enabled) ||
    !isBoolean(webPush.configured) ||
    !Number.isInteger(webPush.subscription_count) ||
    Number(webPush.subscription_count) < 0 ||
    !(webPush.vapid_public_key === null ||
      typeof webPush.vapid_public_key === "string") ||
    !isBoolean(email.enabled) ||
    !isBoolean(email.configured) ||
    !isBoolean(telegram.enabled) ||
    !isBoolean(telegram.configured) ||
    !Array.isArray(root.recent_deliveries)
  ) {
    return null;
  }
  const deliveries: Delivery[] = [];
  for (const item of root.recent_deliveries) {
    if (!item || typeof item !== "object") return null;
    const row = item as Record<string, unknown>;
    if (
      typeof row.id !== "string" ||
      typeof row.job_id !== "string" ||
      !["completed", "failed"].includes(String(row.terminal_status)) ||
      !["web_push", "email", "telegram"].includes(String(row.channel)) ||
      !["pending", "claimed", "delivered", "failed", "suppressed"].includes(
        String(row.state),
      ) ||
      !Number.isInteger(row.attempt_count) ||
      !(row.error_code === null || typeof row.error_code === "string") ||
      typeof row.created_at !== "string" ||
      !(row.delivered_at === null || typeof row.delivered_at === "string")
    ) {
      return null;
    }
    deliveries.push(row as Delivery);
  }
  return {
    channels: {
      web_push: webPush as WebPushChannel,
      email: email as NotificationChannel,
      telegram: telegram as NotificationChannel,
    },
    recent_deliveries: deliveries,
  };
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.data && typeof error.data === "object") {
    const detail = (error.data as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.length <= 240) return detail;
  }
  return "Не удалось сохранить настройку. Повторите попытку.";
}

const CHANNEL_LABELS = {
  web_push: "Уведомления в браузере",
  email: "Email",
  telegram: "Telegram",
} as const;

const DELIVERY_STATE_LABELS: Record<Delivery["state"], string> = {
  pending: "ожидает отправки",
  claimed: "отправляется",
  delivered: "доставлено",
  failed: "будет повторено",
  suppressed: "остановлено",
};

export function NotificationsPanel({
  csrf,
  onCsrf,
}: {
  csrf: string;
  onCsrf: (csrf: string) => void;
}) {
  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [pendingChannel, setPendingChannel] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const load = async () => {
    setLoading(true);
    setMessage("");
    try {
      const parsed = parseNotificationPreferences(
        await api<unknown>("/notifications/preferences"),
      );
      if (!parsed) throw new Error("invalid_notification_preferences");
      setPreferences(parsed);
    } catch {
      setMessage("Не удалось загрузить настройки уведомлений.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const patchChannel = async (
    channel: "telegram",
    enabled: boolean,
  ) => {
    setPendingChannel(channel);
    setMessage("");
    try {
      const parsed = parseNotificationPreferences(
        await mutateWithCsrfRetry<unknown>(
          "/notifications/preferences",
          csrf,
          onCsrf,
          {
            method: "PATCH",
            body: JSON.stringify({ [`${channel}_enabled`]: enabled }),
          },
        ),
      );
      if (!parsed) throw new Error("invalid_notification_preferences");
      setPreferences(parsed);
      setMessage(enabled ? "Канал включён." : "Канал выключен.");
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setPendingChannel(null);
    }
  };

  return (
    <section aria-labelledby="notification-settings-title">
      <h2 id="notification-settings-title">Уведомления</h2>
      <p className="muted">
        Telegram сообщит о готовой транскрибации или ошибке. Уведомления
        выключены, пока вы сами их не включите.
      </p>
      {loading && <p role="status">Загружаем настройки уведомлений…</p>}
      {!loading && !preferences && (
        <button type="button" onClick={() => void load()}>
          Повторить
        </button>
      )}
      {preferences && (
        <div className="notification-channel-grid">
          {(
            ["telegram"] as const
          ).map((channelName) => {
            const channel = preferences.channels[channelName];
            const pending = pendingChannel === channelName;
            return (
              <article className="card notification-channel" key={channelName}>
                <div>
                  <h3>{CHANNEL_LABELS[channelName]}</h3>
                  <p className="muted">
                    {!channel.configured
                      ? "Пока не настроено на сервере"
                      : channel.enabled
                        ? "Включено"
                        : "Выключено"}
                  </p>
                </div>
                <button
                  type="button"
                  className={channel.enabled ? "secondary" : "primary"}
                  disabled={
                    pendingChannel !== null ||
                    (!channel.configured && !channel.enabled)
                  }
                  aria-busy={pending || undefined}
                  onClick={() => {
                    void patchChannel(channelName, !channel.enabled);
                  }}
                >
                  {pending ? "Сохраняем…" : channel.enabled ? "Выключить" : "Включить"}
                </button>
              </article>
            );
          })}
        </div>
      )}
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      {preferences && (
        <details className="card notification-history">
          <summary className="summary-row">Последние доставки</summary>
          {preferences.recent_deliveries.length === 0 ? (
            <p className="muted">Уведомления ещё не отправлялись.</p>
          ) : (
            <ul>
              {preferences.recent_deliveries.map((delivery) => (
                <li key={delivery.id}>
                  {CHANNEL_LABELS[delivery.channel]} · {delivery.terminal_status === "completed" ? "готово" : "ошибка"} · {DELIVERY_STATE_LABELS[delivery.state]} · {new Date(delivery.created_at).toLocaleString("ru-RU")}
                </li>
              ))}
            </ul>
          )}
        </details>
      )}
    </section>
  );
}
