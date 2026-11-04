import { describe, expect, it } from "vitest";
import { parseLongMediaPreflight, longMediaEstimate } from "./longMediaPreflight";

const known = { source_duration_seconds: 18000, selected_duration_seconds: 3600, nominal_cost: "0.22000000", currency: "USD", rate_per_hour: "0.220000", effective_date: "2026-10-06", source: "elevenlabs_public_api_pricing", provider: "elevenlabs", additional_source_count: 0, maximum_seconds_per_source: 43200, basis: "measured_duration_x_immutable_public_tariff", invoice_debit: false, confirmation_token: "a".repeat(64) };
describe("measured long-recording estimate", () => {
  it("uses the selected provider provenance and rejects a cross-provider tariff", () => {
    expect(parseLongMediaPreflight({ ...known, provider: "yandex", source: "yandex_public_api_pricing" })).not.toBeNull();
    expect(parseLongMediaPreflight({ ...known, provider: "yandex" })).toBeNull();
  });
  it("shows source versus requested duration and never calls the estimate a debit", () => {
    const quote = parseLongMediaPreflight(known)!;
    expect(longMediaEstimate(quote)).toContain("исходника: 300 мин; итоговая выбранная запись: 60 мин");
    expect(longMediaEstimate(quote)).toContain("Лимит итоговой записи после подготовки: 720 мин");
    expect(longMediaEstimate(quote)).toContain("Номинальная оценка: 0,22 USD");
    expect(longMediaEstimate(quote)).toContain("а не фактическое списание");
  });
  it("preserves unknown tariff and rejects missing, mixed and nonfinite price data", () => {
    const unknown = { ...known, nominal_cost: null, currency: null, rate_per_hour: null, effective_date: null, source: null };
    expect(longMediaEstimate(parseLongMediaPreflight(unknown)!)).toContain("не означает бесплатную обработку");
    expect(parseLongMediaPreflight({ ...known, source_duration_seconds: NaN })).toBeNull();
    expect(parseLongMediaPreflight({ ...known, nominal_cost: null })).toBeNull();
    expect(parseLongMediaPreflight({ ...known, confirmation_token: "stale" })).toBeNull();
  });
});
