import type { ComposerRow, VerifiedOutputFolder } from "./batchComposerModel";

const bounded = (value: unknown, length: number) => typeof value === "string" && value.length <= length;
function folder(value: unknown): VerifiedOutputFolder | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (row.provider !== undefined && row.provider !== "google_drive" && row.provider !== "yandex_disk") return null;
  return bounded(row.folder_id, 256) && bounded(row.name, 512)
    ? { folder_id: row.folder_id as string, name: row.name as string, web_view_url: null,
        ...(row.provider === "yandex_disk" ? { provider: "yandex_disk" as const } : {}) } : null;
}

export function composerDraftRows(value: unknown): ComposerRow[] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > 50) return null;
  const ids = new Set<string>();
  const rows: ComposerRow[] = [];
  let count = 0;
  for (const candidate of value) {
    if (!candidate || typeof candidate !== "object") return null;
    const row = candidate as ComposerRow;
    if (!bounded(row.id, 100) || ids.has(row.id) || !bounded(row.source_id, 100)
      || !Array.isArray(row.segments) || row.segments.length < 1 || row.segments.length > 50) return null;
    ids.add(row.id);
    const segmentIds = new Set<string>();
    for (const segment of row.segments) {
      if (!segment || !bounded(segment.id, 100) || segmentIds.has(segment.id) || !bounded(segment.title, 160)
        || !bounded(segment.start_boundary, 40) || !bounded(segment.end_boundary, 40)
        || typeof segment.ends_at_source_end !== "boolean" || ++count > 50) return null;
      segmentIds.add(segment.id);
    }
    rows.push({ id: row.id, source_id: row.source_id, output_folder: folder(row.output_folder),
      segmentation_enabled: row.segmentation_enabled === true,
      segments: row.segments.map((s) => ({ id: s.id, title: s.title, start_boundary: s.start_boundary,
        end_boundary: s.end_boundary, ends_at_source_end: s.ends_at_source_end,
        reprocess_existing: false, output_folder: folder(s.output_folder) })) });
  }
  return rows;
}
