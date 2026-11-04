import type { RealtimeTranscriptEvent } from "./realtimeProtocol";
import type { RealtimeSegmentMetadata } from "./realtimeTranscript";

type Commit = Extract<RealtimeTranscriptEvent, { kind: "committed" }>;

/** Correlate delayed timestamp messages and indexed refinements within one transport. */
export class RealtimeSegmentStream {
  private sequence = 0;
  private untimed: { id: string; text: string }[] = [];
  private timed = new Map<string, string>();
  private indexed = new Map<string, string>();
  private visible = new Set<string>();
  private retired = new Set<string>();
  private cutoff: number | null = null;
  private partialBlocked = false;

  private retire(id: string) {
    this.retired.add(id);
    while (this.retired.size > 5000) this.retired.delete(this.retired.values().next().value!);
  }

  constructor(private namespace: string, private offsetSeconds: number, private sessionId?: string) {}

  get clearBoundaryPending() { return this.partialBlocked; }

  clearBefore(seconds: number) {
    this.cutoff = Math.max(this.cutoff ?? 0, seconds);
    this.partialBlocked = this.cutoff > this.offsetSeconds;
    for (const id of this.indexed.keys()) this.retire(id);
    this.visible.clear();
  }

  partial(event: Extract<RealtimeTranscriptEvent, {kind:"partial"}>): string {
    if (this.cutoff === null) return event.text;
    if (event.words) return event.words.filter(word => word.start_seconds + this.offsetSeconds >= this.cutoff!).map(word => word.text).join(" ");
    return this.partialBlocked ? "" : event.text;
  }

  committed(event: Commit): { text: string; metadata: RealtimeSegmentMetadata; replaces: boolean } | null {
    const raw = event.metadata;
    let id: string;
    if (raw && raw.id !== "timed") {
      id = `${this.namespace}.${raw.id}`;
      const signature = JSON.stringify([event.text, raw]);
      if (this.indexed.get(id) === signature) return null;
      this.indexed.set(id, signature);
      if (this.indexed.size > 5000) this.indexed.delete(this.indexed.keys().next().value!);
    } else if (event.timestampUpdate && raw) {
      const signature = JSON.stringify([event.text, raw.start_seconds, raw.end_seconds]);
      if (this.timed.has(signature)) return null;
      const index = this.untimed.findIndex((item) => item.text === event.text);
      id = index >= 0 ? this.untimed.splice(index, 1)[0].id : `${this.namespace}.${this.sequence++}`;
      this.timed.set(signature, id);
      if (this.timed.size > 5000) this.timed.delete(this.timed.keys().next().value!);
    } else {
      id = `${this.namespace}.${this.sequence++}`;
      this.untimed.push({ id, text: event.text });
      // Same bounded transcript limit as local/server drafts; no unbounded event log.
      if (this.untimed.length > 5000) this.untimed.shift();
    }
    const metadata: RealtimeSegmentMetadata = { ...raw, id, ...(this.sessionId ? { session_id: this.sessionId } : {}) };
    if (raw?.start_seconds !== undefined && raw.end_seconds !== undefined) {
      metadata.start_seconds = this.offsetSeconds + raw.start_seconds;
      metadata.end_seconds = this.offsetSeconds + raw.end_seconds;
    }
    let text = event.text;
    if (this.cutoff !== null) {
      if (this.retired.has(id) || metadata.end_seconds === undefined || metadata.start_seconds === undefined) return null;
      if (metadata.end_seconds <= this.cutoff) {
        if (raw?.id && raw.id !== "timed") this.retire(id);
        return null;
      }
      if (metadata.start_seconds < this.cutoff) {
        const after = event.words?.filter(word => word.start_seconds + this.offsetSeconds >= this.cutoff!);
        if (!after?.length) return null;
        text = after.map(word => word.text).join(" ").replace(/\s+([,.;:!?])/g,"$1");
        metadata.start_seconds = this.offsetSeconds + after[0].start_seconds;
        metadata.end_seconds = this.offsetSeconds + after[after.length-1].end_seconds;
      }
      this.partialBlocked = false;
    }
    const replaces = this.visible.has(id);
    this.visible.add(id);
    if (this.visible.size > 5000) this.visible.delete(this.visible.values().next().value!);
    return { text, metadata, replaces };
  }
}
