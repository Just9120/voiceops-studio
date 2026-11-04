import { describe, expect, it, vi } from "vitest";
import { collectDiskFolderPreview, type DiskFolderPage } from "./yandexFolderPreview";
import type { DiskResource } from "./YandexDiskPicker";

const root: DiskResource = { path: "disk:/", name: "Мой диск", is_folder: true,
  fingerprint: "f".repeat(64), mime_type: null, size_bytes: null, modified: null };
const media = (path: string): DiskResource => ({ ...root, path, name: path.split("/").at(-1)!,
  is_folder: false, mime_type: "audio/flac", size_bytes: 20 });

describe("recursive Disk source preview", () => {
  it("includes nested media and all pages, explains unsupported/empty exclusions and preserves order", async () => {
    const child = { ...root, path: "disk:/nested", name: "nested" };
    const load = vi.fn(async (path: string, offset: number | null): Promise<DiskFolderPage> => {
      if (path === child.path) return { folder: child, items: [media("disk:/nested/two.flac")], next_offset: null };
      return { folder: root, items: offset === null
        ? [media("disk:/one.flac"), child]
        : [{ ...media("disk:/notes.txt"), mime_type: "text/plain" }, { ...media("disk:/empty.flac"), size_bytes: 0 }],
        next_offset: offset === null ? 2 : null };
    });
    const preview = await collectDiskFolderPreview(root, load, new AbortController().signal);
    expect(preview.resources.map(row => row.path)).toEqual(["disk:/one.flac", "disk:/nested/two.flac"]);
    expect(preview.folder_count).toBe(2);
    expect(preview.excluded.map(row => row.reason)).toEqual(["Неподдерживаемый тип файла", "Пустой файл"]);
  });

  it("rejects changed versions, duplicate pages and folders escaping the selected tree", async () => {
    for (const page of [
      { folder: { ...root, fingerprint: "a".repeat(64) }, items: [], next_offset: null },
      { folder: root, items: [media("disk:/a"), media("disk:/a")], next_offset: null },
      { folder: root, items: [{ ...root, path: "disk:/../other", name: "other" }], next_offset: null },
    ]) {
      await expect(collectDiskFolderPreview(root, async () => page, new AbortController().signal)).rejects.toThrow("changed_disk_page");
    }
  });

  it("refuses oversized selection as a whole and does not publish partial results", async () => {
    await expect(collectDiskFolderPreview(root, async () => ({ folder: root,
      items: Array.from({ length: 51 }, (_, index) => media(`disk:/${index}.flac`)), next_offset: null }),
      new AbortController().signal)).rejects.toThrow("disk_folder_over_limit");
  });

  it("stops before another request after cancellation", async () => {
    const controller = new AbortController();
    const load = vi.fn(async () => { controller.abort(); return { folder: root, items: [media("disk:/one.flac")], next_offset: null }; });
    await expect(collectDiskFolderPreview(root, load, controller.signal)).rejects.toThrow();
    expect(load).toHaveBeenCalledTimes(1);
  });
});
