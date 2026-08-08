(() => {
  function extractDocumentId() {
    const match = window.location.href.match(/\/document\/d\/([a-zA-Z0-9_-]+)/);
    return match?.[1] ?? null;
  }

  function extractDocumentTitle() {
    const rawTitle = document.title || "Untitled Document";
    return rawTitle.replace(/\s*-\s*Google Docs$/i, "").trim() || "Untitled Document";
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "GET_DOCUMENT_CONTEXT") {
      sendResponse({
        documentId: extractDocumentId(),
        documentTitle: extractDocumentTitle(),
        url: window.location.href,
      });
    }
  });
})();
