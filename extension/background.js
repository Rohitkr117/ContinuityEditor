const DOCS_URL_RE = /^https:\/\/docs\.google\.com\/document\//i;

async function updateSidePanel(tabId, url) {
  await chrome.sidePanel.setOptions({
    tabId,
    path: "sidebar/sidebar.html",
    enabled: DOCS_URL_RE.test(url ?? ""),
  });
}

chrome.runtime.onInstalled.addListener(async () => {
  const tabs = await chrome.tabs.query({});
  await Promise.all(tabs.map((tab) => updateSidePanel(tab.id, tab.url)));
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.url || changeInfo.status === "complete") {
    await updateSidePanel(tabId, changeInfo.url ?? tab.url);
  }
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId);
  await updateSidePanel(tabId, tab.url);
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "OPEN_SIDE_PANEL") {
    chrome.sidePanel.open({ tabId: message.tabId }).then(
      () => sendResponse({ ok: true }),
      (error) => sendResponse({ ok: false, error: error.message }),
    );
    return true;
  }
  return false;
});
