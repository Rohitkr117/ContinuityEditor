import { getActiveGoogleDocContext } from "../lib/browser.js";
import { coerceErrorMessage, deriveSyncState } from "../lib/state.js";
import { getDocumentRecord, getSettings } from "../lib/storage.js";
import { getProjectRecall } from "../lib/backendApi.js";

const els = {
  docTitle: document.getElementById("docTitle"),
  summaryText: document.getElementById("summaryText"),
  projectLabel: document.getElementById("projectLabel"),
  syncLabel: document.getElementById("syncLabel"),
  issuesContainer: document.getElementById("issuesContainer"),
};

let currentDocumentId = null;

function setPill(text, tone = "muted") {
  els.syncLabel.textContent = text;
  els.syncLabel.className = `pill pill-${tone}`;
}

function renderEmpty(message) {
  els.issuesContainer.innerHTML = `<article class="empty-card"><p>${message}</p></article>`;
}

function renderIssues(issues) {
  if (!issues.length) {
    renderEmpty("No continuity issues found.");
    return;
  }

  els.issuesContainer.innerHTML = issues.map((issue) => `
    <article class="issue-card severity-${issue.severity}">
      <div class="issue-header">
        <div>
          <h2 class="issue-title">${issue.severity} - ${issue.issue_type}</h2>
          <p class="entity">${issue.affected_entity}</p>
        </div>
        <span class="pill ${issue.severity === "HARD" ? "pill-danger" : "pill-warning"}">${issue.severity}</span>
      </div>
      <p class="issue-body">${issue.explanation}</p>
      <div class="evidence-block">
        <span class="evidence-label">Previously established</span>
        <p class="evidence-text">${issue.previous_manuscript_evidence ?? "No previous evidence quote available."}</p>
      </div>
      <div class="evidence-block">
        <span class="evidence-label">Current text</span>
        <p class="evidence-text">${issue.current_text_evidence ?? "No current evidence quote available."}</p>
      </div>
      <div class="evidence-block">
        <span class="evidence-label">Source</span>
        <p class="source-text">${issue.source_context ?? "Document memory"}</p>
      </div>
    </article>
  `).join("");
}

async function renderFromStorage() {
  const context = await getActiveGoogleDocContext();
  if (!context) {
    els.docTitle.textContent = "No Google Doc selected";
    els.projectLabel.textContent = "Not mapped";
    setPill("Unavailable", "danger");
    renderEmpty("Open a Google Doc and run Continuity Editor from the popup.");
    return;
  }

  currentDocumentId = context.documentId;
  const record = await getDocumentRecord(context.documentId);

  els.docTitle.textContent = record?.documentTitle ?? context.documentTitle;
  els.projectLabel.textContent = record?.projectTitle ?? "Not mapped";

  const syncState = deriveSyncState(record);
  if (syncState === "SYNCED") {
    setPill("Synced", "success");
  } else if (syncState === "OUT_OF_SYNC") {
    setPill("Needs Sync", "warning");
  } else if (syncState === "UNMAPPED") {
    setPill("Unmapped", "muted");
  } else {
    setPill("Unknown", "muted");
  }

  els.summaryText.textContent = "Loading project memory...";
  
  try {
    const settings = await getSettings();
    const recallData = await getProjectRecall(settings.backendUrl, record.projectId);
    els.summaryText.textContent = "Project contradictions loaded from backend.";
    
    // Map ContradictionOut models to the sidebar issue format
    const issues = recallData.contradictions.map(c => ({
      severity: c.severity,
      issue_type: c.field,
      affected_entity: c.entity_name || `Entity #${c.entity_id}`,
      explanation: c.reason || `Changed from "${c.value_a}" to "${c.value_b}"`,
      previous_manuscript_evidence: c.quote_a,
      current_text_evidence: c.quote_b,
      source_context: `Chapter ${c.chapter_a_number || c.chapter_a_id} vs Chapter ${c.chapter_b_number || c.chapter_b_id}`,
    }));
    
    renderIssues(issues);
  } catch (error) {
    els.summaryText.textContent = coerceErrorMessage(error, "Could not load project memory.");
    renderEmpty("Ensure your backend is running and the project exists.");
  }
}

chrome.storage.onChanged.addListener(async (changes, areaName) => {
  if (areaName !== "local" || !changes.documents || !currentDocumentId) return;
  const nextRecords = changes.documents.newValue ?? {};
  if (nextRecords[currentDocumentId]) {
    await renderFromStorage();
  }
});

document.addEventListener("DOMContentLoaded", async () => {
  try {
    await renderFromStorage();
  } catch (error) {
    els.summaryText.textContent = coerceErrorMessage(error, "The side panel could not load its latest state.");
    renderEmpty("Try reopening the popup and running the analysis again.");
  }
});
