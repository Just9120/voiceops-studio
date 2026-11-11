import { useEffect, useState } from "react";
import {
  REALTIME_CAPTION_READY,
  realtimeCaptionChannel,
  parseRealtimeCaptionMessage,
  type RealtimeCaptionMessage,
} from "./realtimeConsumers";
import "./styles.css";

export function RealtimeOverlay() {
  const [caption, setCaption] = useState<RealtimeCaptionMessage | null>(null);
  const supported = typeof BroadcastChannel !== "undefined";
  const projectId = new URLSearchParams(window.location.search).get("project") ?? "";
  const channelName = realtimeCaptionChannel(window.location.hash.slice(1));

  useEffect(() => {
    if (!supported || !channelName || !projectId) return;
    const channel = new BroadcastChannel(channelName);
    channel.onmessage = (event) => {
      const parsed = parseRealtimeCaptionMessage(event.data);
      if (parsed?.project_id === projectId) setCaption(parsed);
    };
    channel.postMessage(REALTIME_CAPTION_READY);
    return () => channel.close();
  }, [channelName, projectId, supported]);

  const lines = caption
    ? [...caption.committed, caption.partial].filter(Boolean).slice(-3)
    : [];
  return (
    <main className="realtime-overlay" aria-live="polite">
      {!projectId || !channelName ? (
        <p>Откройте overlay из нужного проекта Studio.</p>
      ) : !supported ? (
        <p>Этот браузер не поддерживает независимый канал субтитров.</p>
      ) : lines.length ? (
        <div className="realtime-overlay-caption">{lines.join("\n")}</div>
      ) : (
        <p className="realtime-overlay-waiting">Ожидаем Live-субтитры…</p>
      )}
    </main>
  );
}
