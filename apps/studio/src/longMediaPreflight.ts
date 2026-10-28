export type LongMediaPreflight = {
  source_duration_seconds: number; selected_duration_seconds: number;
  nominal_cost: string | null; currency: "USD" | null; rate_per_hour: string | null;
  effective_date: string | null; source: "elevenlabs_public_api_pricing" | "yandex_public_api_pricing" | null;
  provider: "elevenlabs" | "yandex" | "tbank" | "mistral" | "gemini"; additional_source_count: number; maximum_seconds_per_source: number;
  basis: "measured_duration_x_immutable_public_tariff"; invoice_debit: false; confirmation_token: string;
};

export function parseLongMediaPreflight(value: unknown): LongMediaPreflight | null {
  if (!value || typeof value !== "object") return null;
  const p = value as LongMediaPreflight;
  if (!Number.isFinite(p.source_duration_seconds) || p.source_duration_seconds <= 0
    || !Number.isFinite(p.selected_duration_seconds) || p.selected_duration_seconds < 0 || p.selected_duration_seconds > p.source_duration_seconds
    || !Number.isFinite(p.maximum_seconds_per_source) || p.maximum_seconds_per_source <= 0
    || !Number.isInteger(p.additional_source_count) || p.additional_source_count < 0 || p.additional_source_count > 50
    || !["elevenlabs", "yandex", "tbank", "mistral", "gemini"].includes(p.provider) || p.basis !== "measured_duration_x_immutable_public_tariff"
    || p.invoice_debit !== false || typeof p.confirmation_token !== "string" || !/^[a-f0-9]{64}$/.test(p.confirmation_token)) return null;
  const priced = p.nominal_cost !== null;
  const decimal = (value: unknown) => typeof value === "string" && /^\d{1,9}(?:\.\d{1,8})?$/.test(value);
  if (priced ? (!decimal(p.nominal_cost) || !decimal(p.rate_per_hour) || Number(p.rate_per_hour) <= 0
    || p.currency !== "USD" || p.source !== (p.provider === "elevenlabs" ? "elevenlabs_public_api_pricing" : "yandex_public_api_pricing")
    || typeof p.effective_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(p.effective_date))
    : [p.currency, p.rate_per_hour, p.effective_date, p.source].some((value) => value !== null)) return null;
  return p;
}

export function longMediaEstimate(p: LongMediaPreflight) {
  const minutes = (value: number) => `${(value / 60).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} мин`;
  const price = p.nominal_cost !== null ? `Номинальная оценка: ${Number(p.nominal_cost).toLocaleString("ru-RU", { maximumFractionDigits: 6 })} ${p.currency} по сохранённому тарифу ${p.rate_per_hour} ${p.currency}/ч (${p.effective_date}).`
    : "Денежная оценка неизвестна: тариф не настроен. Это не означает бесплатную обработку.";
  return `Измеренная длительность исходника: ${minutes(p.source_duration_seconds)}; выбранная часть: ${minutes(p.selected_duration_seconds)}. ${price} Это оценка без учёта стыков разбиения, подписки и квоты, а не фактическое списание.${p.additional_source_count ? ` Ещё исходников в задаче: ${p.additional_source_count}; их длительность и расход пока не определены. Лимит каждого: ${minutes(p.maximum_seconds_per_source)}.` : ""}`;
}
