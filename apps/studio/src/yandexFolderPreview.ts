import type { DiskResource } from "./YandexDiskPicker";

export type DiskFolderPage = { folder: DiskResource; items: DiskResource[]; next_offset: number | null };
export type DiskFolderPreview = {
  root: DiskResource;
  resources: DiskResource[];
  excluded: { path: string; name: string; reason: string }[];
  folder_count: number;
  signature: string;
};

export function isDiskMedia(row: DiskResource) {
  return !row.is_folder && Boolean(row.mime_type && (/^(audio|video)\//.test(row.mime_type) || row.mime_type === "application/ogg"));
}

// Limits stop the entire preview rather than silently truncating a folder tree.
export async function collectDiskFolderPreview(
  root: DiskResource,
  load: (path: string, offset: number | null) => Promise<DiskFolderPage>,
  signal: AbortSignal,
): Promise<DiskFolderPreview> {
  const queue = [{ folder: root, depth: 0 }];
  const seen = new Set<string>();
  const resources: DiskResource[] = [];
  const excluded: DiskFolderPreview["excluded"] = [];
  const folderVersions: { path: string; fingerprint: string; modified: string | null }[] = [];
  let inspected = 0;
  while (queue.length) {
    signal.throwIfAborted();
    const { folder, depth } = queue.shift()!;
    if (seen.has(folder.path)) throw new Error("changed_disk_page");
    seen.add(folder.path);
    if (depth > 8 || seen.size > 100) throw new Error("disk_tree_over_limit");
    let offset: number | null = null;
    const paths = new Set<string>();
    do {
      signal.throwIfAborted();
      const page = await load(folder.path, offset);
      if (page.folder.path !== folder.path || page.folder.fingerprint !== folder.fingerprint || page.folder.modified !== folder.modified
          || (page.next_offset !== null && page.next_offset <= (offset ?? 0))) throw new Error("changed_disk_page");
      if (offset === null) folderVersions.push({ path: folder.path, fingerprint: folder.fingerprint, modified: folder.modified });
      for (const item of page.items) {
        signal.throwIfAborted();
        const prefix = folder.path.endsWith("/") ? folder.path : `${folder.path}/`;
        const tail = item.path.slice(prefix.length);
        if (!item.path.startsWith(prefix) || !tail || tail.includes("/") || tail === "." || tail === ".." || paths.has(item.path)) {
          throw new Error("changed_disk_page");
        }
        paths.add(item.path);
        if (++inspected > 500) throw new Error("disk_tree_over_limit");
        if (item.is_folder) queue.push({ folder: item, depth: depth + 1 });
        else if (!isDiskMedia(item)) excluded.push({ path: item.path, name: item.name, reason: "Неподдерживаемый тип файла" });
        else if (item.size_bytes === 0) excluded.push({ path: item.path, name: item.name, reason: "Пустой файл" });
        else resources.push(item);
        if (resources.length > 50) throw new Error("disk_folder_over_limit");
      }
      offset = page.next_offset;
    } while (offset !== null);
  }
  return { root, resources, excluded, folder_count: seen.size,
    signature: JSON.stringify({ folderVersions, resources, excluded }) };
}
