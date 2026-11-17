/** Helpers for the resume and cover-letter library. Pure functions are unit-tested; downloadBlob needs a DOM. */

export const MAX_UPLOAD_BYTES = 5_000_000;
export const ACCEPT = ".pdf,.docx,.odt,.rtf,.txt,.md";

const EXT: Record<string, string> = {
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "application/vnd.oasis.opendocument.text": "odt",
  "application/rtf": "rtf",
  "text/plain": "txt",
  "text/markdown": "md",
};

/** "Cloud and AI" + a Word file → "Cloud and AI.docx". Unknown types keep the name as is. */
export function fileName(label: string, mime: string): string {
  const ext = EXT[mime.split(";")[0]!.trim()];
  const base = label.replace(/[\\/:*?"<>|]+/g, " ").trim() || "document";
  return ext && !base.toLowerCase().endsWith(`.${ext}`) ? `${base}.${ext}` : base;
}

/** "312 KB", "1.4 MB". */
export function sizeLabel(bytes: number | null | undefined): string {
  if (!bytes) return "";
  if (bytes < 1_000_000) return `${Math.max(1, Math.round(bytes / 1000))} KB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

/** Why a file can't be uploaded, before sending it; null when it's fine. */
export function uploadProblem(file: { name: string; size: number }): string | null {
  if (file.size > MAX_UPLOAD_BYTES) return `${file.name} is larger than 5 MB.`;
  if (/\.doc$/i.test(file.name)) return `${file.name} is an old Word file: save it as .docx or PDF first.`;
  if (!/\.(pdf|docx|odt|rtf|txt|md)$/i.test(file.name)) return `${file.name}: only PDF, Word (.docx), OpenDocument, RTF or text files.`;
  return null;
}

export function downloadBlob(blob: Blob, label: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName(label, blob.type);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
