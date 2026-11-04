import { describe, expect, it } from "vitest";
import { RealtimeSegmentStream } from "./realtimeSegmentStream";

describe("Live provider stream correlation", () => {
  it("fences cleared identities and keeps the word-timed suffix of an in-flight utterance", () => {
    const stream = new RealtimeSegmentStream("capture.1", 20);
    stream.committed({kind:"committed",text:"старый индекс",metadata:{id:"index.0",start_seconds:1,end_seconds:2}});
    stream.clearBefore(25);
    expect(stream.partial({kind:"partial",text:"старый partial"})).toBe("");
    expect(stream.committed({kind:"committed",text:"позднее исправление",metadata:{id:"index.0",start_seconds:6,end_seconds:7}})).toBeNull();
    expect(stream.committed({kind:"committed",text:"до после"})).toBeNull();
    const filtered = stream.committed({kind:"committed",text:"до после",timestampUpdate:true,
      metadata:{id:"timed",start_seconds:4,end_seconds:7},words:[
        {text:"до",start_seconds:4,end_seconds:4.5},{text:"после",start_seconds:6,end_seconds:7}]});
    expect(filtered).toMatchObject({text:"после",replaces:false,metadata:{start_seconds:26,end_seconds:27}});
    expect(stream.partial({kind:"partial",text:"следующая реплика"})).toBe("следующая реплика");
    expect(stream.committed({kind:"committed",text:"до",timestampUpdate:true,metadata:{id:"timed",start_seconds:4,end_seconds:4.5}})).toBeNull();
    stream.clearBefore(28);
    expect(stream.committed({kind:"committed",text:"после",timestampUpdate:true,metadata:{id:"timed",start_seconds:6,end_seconds:7}})).toBeNull();
  });

  it("keeps the original clear boundary across a new transport and never guesses an untimed correction", () => {
    const stream = new RealtimeSegmentStream("capture.2", 20);
    stream.clearBefore(25);
    expect(stream.committed({kind:"committed",text:"старый финал",metadata:{id:"index.0",start_seconds:1,end_seconds:2}})).toBeNull();
    expect(stream.committed({kind:"committed",text:"фраза на границе",metadata:{id:"index.1",start_seconds:4,end_seconds:6}})).toBeNull();
    expect(stream.committed({kind:"committed",text:"новая фраза",metadata:{id:"index.2",start_seconds:5,end_seconds:6}}))
      .toMatchObject({text:"новая фраза",metadata:{start_seconds:25,end_seconds:26}});
    expect(stream.committed({kind:"committed",text:"исправлено",metadata:{id:"index.2",start_seconds:5,end_seconds:6}}))
      .toMatchObject({text:"исправлено",replaces:true});
  });
  it("carries one capture identity through separate transports", () => {
    const sessionId = "capture_session_123456";
    const event = { kind: "committed" as const, text: "фрагмент", metadata: { id: "index.0", start_seconds: 0, end_seconds: 1 } };
    for (const transport of [1, 2]) {
      expect(new RealtimeSegmentStream(`namespace.${transport}`, transport * 10, sessionId).committed(event)?.metadata)
        .toMatchObject({ session_id: sessionId, start_seconds: transport * 10 });
    }
  });
  it("adds delayed timestamps once without losing identical spoken repetitions", () => {
    const stream = new RealtimeSegmentStream("session.1", 20);
    const first = stream.committed({ kind: "committed", text: "да" });
    const second = stream.committed({ kind: "committed", text: "да" });
    const event = { kind: "committed" as const, text: "да", timestampUpdate: true, metadata: { id: "timed", start_seconds: 1, end_seconds: 2 } };
    expect(stream.committed(event)).toEqual({ text: "да", metadata: { id: first!.metadata.id, start_seconds: 21, end_seconds: 22 }, replaces: true });
    expect(stream.committed(event)).toBeNull();
    expect(stream.committed({ ...event, metadata: { ...event.metadata, start_seconds: 3, end_seconds: 4 } })?.metadata.id).toBe(second!.metadata.id);
    expect(first!.metadata.id).not.toBe(second!.metadata.id);
  });

  it("deduplicates indexed finals and preserves refinements with the same identity", () => {
    const stream = new RealtimeSegmentStream("session.2", 50);
    const event = { kind: "committed" as const, text: "первая версия", metadata: { id: "index.0", start_seconds: 0, end_seconds: 1 } };
    expect(stream.committed(event)?.metadata).toMatchObject({ id: "session.2.index.0", start_seconds: 50, end_seconds: 51 });
    expect(stream.committed(event)).toBeNull();
    expect(stream.committed({ ...event, text: "исправление" })).toMatchObject({ text: "исправление", metadata: { id: "session.2.index.0" } });
    expect(new RealtimeSegmentStream("session.3", 60).committed(event)?.metadata.id).toBe("session.3.index.0");
  });
});
