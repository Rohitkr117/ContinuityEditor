export const DEFAULT_BACKEND_URL = "http://localhost:8000";

export function extractDocumentIdFromUrl(url) {
  if (!url) return null;
  const match = url.match(/\/document\/d\/([a-zA-Z0-9_-]+)/);
  return match?.[1] ?? null;
}

export function stripGoogleDocsSuffix(title) {
  if (!title) return "Untitled Document";
  return title.replace(/\s*-\s*Google Docs\s*$/i, "").trim() || "Untitled Document";
}

export async function hashDocumentText(text) {
  const bytes = new TextEncoder().encode((text ?? "").trim());
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

export function updateDocumentRecord(existing = {}, patch = {}) {
  return {
    ...existing,
    ...patch,
    lastStatus: {
      ...(existing.lastStatus ?? {}),
      ...(patch.lastStatus ?? {}),
    },
    lastAnalysis: patch.lastAnalysis === undefined
      ? existing.lastAnalysis
      : patch.lastAnalysis,
    updatedAt: patch.updatedAt ?? new Date().toISOString(),
  };
}

export function deriveSyncState(record) {
  if (!record?.projectId) return "UNMAPPED";
  if (record?.lastAnalysis?.sync_state) return record.lastAnalysis.sync_state;
  if (record?.lastStatus?.syncState) return record.lastStatus.syncState;
  return "UNKNOWN";
}

export function isDuplicateContent(currentHash, lastSyncedHash) {
  return Boolean(currentHash && lastSyncedHash && currentHash === lastSyncedHash);
}

export function parseCheckResponse(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("The backend returned an invalid continuity analysis response.");
  }
  if (!Array.isArray(payload.issues)) {
    throw new Error("The backend response did not include an issues list.");
  }
  return {
    ...payload,
    message: typeof payload.message === "string" ? payload.message : "Continuity analysis finished.",
    issue_count: typeof payload.issue_count === "number" ? payload.issue_count : payload.issues.length,
  };
}

export function coerceErrorMessage(error, fallback = "Something went wrong.") {
  if (!error) return fallback;
  if (typeof error === "string") return error;
  if (error.message) return error.message;
  return fallback;
}
