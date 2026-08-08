import { extractDocumentIdFromUrl, stripGoogleDocsSuffix } from "./state.js";

export async function getActiveGoogleDocContext() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return null;

  try {
    const response = await chrome.tabs.sendMessage(tab.id, { type: "GET_DOCUMENT_CONTEXT" });
    if (response?.documentId) {
      return {
        ...response,
        tabId: tab.id,
      };
    }
  } catch {
    // Fall back to tab metadata if the content script is not ready yet.
  }

  const documentId = extractDocumentIdFromUrl(tab.url);
  if (!documentId) return null;
  return {
    documentId,
    documentTitle: stripGoogleDocsSuffix(tab.title),
    tabId: tab.id,
    url: tab.url,
  };
}

export async function openSidePanel(tabId) {
  await chrome.runtime.sendMessage({ type: "OPEN_SIDE_PANEL", tabId });
}
