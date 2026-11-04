import { describe, expect, it } from "vitest";
import { LOCAL_MODEL, localDeviceReady, localDeviceStatus, parseLocalDevice, parseLocalDevices } from "./localExecutionContracts";
import { buildBatchCreateRequest, composerSignature } from "./batchComposerModel";
import { parseSttProviderCatalog, sttModeExplanation } from "./sttContracts";

export const localDeviceFixture = (extra = {}) => ({ id: "00000000-0000-4000-8000-000000000001", label: "Тестовый ПК",
  credential_revision: 1, online: true, ready: true, runtime_status: "ready", runtime_version: "0.2.0",
  model: LOCAL_MODEL, last_seen_at: new Date().toISOString(), revoked_at: null, ...extra });

describe("local device selection contracts", () => {
  it("rejects contradictory readiness, foreign shape and duplicate devices", () => {
    expect(parseLocalDevice(localDeviceFixture())).not.toBeNull();
    for (const extra of [{ online: false }, { model: "other" }, { revoked_at: new Date().toISOString() }, { last_seen_at: null }, { runtime_status: "model_missing" }]) {
      expect(parseLocalDevice(localDeviceFixture(extra))).toBeNull();
    }
    expect(() => parseLocalDevices({ devices: [localDeviceFixture(), localDeviceFixture()] })).toThrow();
  });
  it("expires stale readiness and describes missing runtime without paid fallback", () => {
    const row = parseLocalDevice(localDeviceFixture())!;
    const now = Date.parse(row.last_seen_at!);
    expect(localDeviceReady(row, now + 89_999)).toBe(true);
    expect(localDeviceReady(row, now + 90_001)).toBe(false);
    expect(localDeviceStatus(row, now + 90_001)).toBe("Компьютер не на связи");
    expect(localDeviceStatus({ ...row, ready: false, runtime_status: "model_missing" }, now)).toBe("Файлы модели не найдены");
  });
  it("includes the exact PC in local requests and invalidates preflight on PC change", () => {
    const build = (pc: string) => buildBatchCreateRequest([], "cloud-key-left-in-state", "ru", true, "nemotron", "standard", [], pc);
    expect(build("pc-one")).toMatchObject({ provider: "nemotron", provider_credential_id: null, local_device_id: "pc-one" });
    expect(composerSignature([], "", "ru", true, "nemotron", "standard", [], "pc-one"))
      .not.toBe(composerSignature([], "", "ru", true, "nemotron", "standard", [], "pc-two"));
    expect(buildBatchCreateRequest([], "cloud", "ru", false, "elevenlabs", "standard", [], "pc-one"))
      .not.toHaveProperty("local_device_id");
  });
  it("accepts the local catalog without inventing auto language, Live or dictionaries", () => {
    const catalog = parseSttProviderCatalog({ providers: [{ provider: "nemotron", display_name: "NVIDIA Nemotron", byok_enabled: true,
      modes: [{ mode: "standard", model: LOCAL_MODEL, transport: "local_companion", languages: ["ru", "en"], diarization: true,
        dictionaries: false, file_constraints: { max_bytes: null, max_duration_seconds: 3600, audio_channels: [1] },
        health: { available: true, consecutive_failures: 0, retry_after_seconds: null } }] }] });
    expect(catalog).not.toBeNull();
    expect(sttModeExplanation(catalog![0].modes[0])).toContain("на выбранном компьютере");
    expect(catalog![0].modes.map(row => row.mode)).toEqual(["standard"]);
  });
});
