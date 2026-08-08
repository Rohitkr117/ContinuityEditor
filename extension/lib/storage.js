import {
  DEFAULT_BACKEND_URL,
  updateDocumentRecord,
} from "./state.js";

const SETTINGS_KEY = "settings";
const DOCUMENTS_KEY = "documents";

export async function getSettings() {
  const stored = await chrome.storage.local.get(SETTINGS_KEY);
  return {
    backendUrl: stored[SETTINGS_KEY]?.backendUrl ?? DEFAULT_BACKEND_URL,
  };
}

export async function setBackendUrl(backendUrl) {
  await chrome.storage.local.set({
    [SETTINGS_KEY]: { backendUrl },
  });
}

export async function getDocumentRecords() {
  const stored = await chrome.storage.local.get(DOCUMENTS_KEY);
  return stored[DOCUMENTS_KEY] ?? {};
}

export async function getDocumentRecord(documentId) {
  const records = await getDocumentRecords();
  return records[documentId] ?? null;
}

export async function saveDocumentRecord(documentId, patch) {
  const records = await getDocumentRecords();
  const nextRecord = updateDocumentRecord(records[documentId], patch);
  records[documentId] = nextRecord;
  await chrome.storage.local.set({ [DOCUMENTS_KEY]: records });
  return nextRecord;
}
