export function isApprovedTranscriptUrl(value: string | null, outputKind?: string | null) {
  if (!value) return false;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.port) return false;
    if (url.hostname === "disk.yandex.ru") {
      return (outputKind == null || outputKind === "yandex_disk_docx_transcript") &&
        url.pathname.startsWith("/client/disk/") && !url.search && !url.hash;
    }
    return outputKind !== "yandex_disk_docx_transcript" && (url.hostname === "docs.google.com" || url.hostname === "drive.google.com");
  } catch {
    return false;
  }
}
