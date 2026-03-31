import { getExportDownloadUrl, triggerFileDownload } from "@/lib/api";

export function getCompletedExportId(result: unknown): string | null {
  if (typeof result !== "object" || result === null) {
    return null;
  }
  const exportId = (result as { export_id?: unknown }).export_id;
  return typeof exportId === "string" && exportId.trim() ? exportId : null;
}

export function downloadCompletedExport(exportId: string, artifactKey?: string): void {
  triggerFileDownload(getExportDownloadUrl(exportId, artifactKey));
}
