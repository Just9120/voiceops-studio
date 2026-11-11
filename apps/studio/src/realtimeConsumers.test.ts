import { describe, expect, it, vi } from "vitest";
import {
  deliverRealtimeConsumer,
  makeRealtimeCaptionMessage,
  parseRealtimeCaptionMessage,
  realtimeCaptionChannel,
} from "./realtimeConsumers";
import { api } from "./apiClient";

vi.mock("./apiClient", () => ({
  api: vi.fn(),
  mutateWithCsrfRetry: vi.fn().mockResolvedValue({ ok: true }),
}));

describe("realtime consumers", () => {
  it("bounds an overlay message to the latest three committed segments", () => {
    const message = makeRealtimeCaptionMessage(
      "project-1",
      ["one", "two", "three", "four"],
      "partial",
    );
    expect(message.committed).toEqual(["two", "three", "four"]);
    expect(parseRealtimeCaptionMessage(message)).toEqual(message);
    expect(parseRealtimeCaptionMessage({ ...message, committed: [1] })).toBeNull();
  });

  it("isolates different Live panels and rejects incomplete overlay addresses", () => {
    const first = realtimeCaptionChannel("8cdaea55-2ccb-4e11-a323-1864908f2769");
    const second = realtimeCaptionChannel("6c4e209f-bbf2-45a4-8055-8ee00153b26d");
    expect(first).toBeTruthy();
    expect(second).toBeTruthy();
    expect(first).not.toBe(second);
    expect(realtimeCaptionChannel("")).toBeNull();
    expect(realtimeCaptionChannel("some-project")).toBeNull();
    expect(parseRealtimeCaptionMessage(
      makeRealtimeCaptionMessage("project-1", ["a".repeat(2100)], "b".repeat(2100)),
    )?.partial).toHaveLength(2000);
  });

  it("sends one consumer independently with no endpoint persistence", async () => {
    await deliverRealtimeConsumer(
      "project-1",
      "webhook",
      "https://captions.example/live",
      "Ready",
      3,
      "csrf",
      vi.fn(),
    );
    expect(api).not.toHaveBeenCalled();
  });
});
