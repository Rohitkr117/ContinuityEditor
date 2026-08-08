import { getActiveGoogleDocContext, openSidePanel } from "../lib/browser.js";
import {
  createProject,
  getBackendHealth,
  listProjects,
  syncDocument,
} from "../lib/backendApi.js";
import { fetchGoogleDocument } from "../lib/googleDocs.js";
import { coerceErrorMessage, deriveSyncState } from "../lib/state.js";
import { getDocumentRecord, getSettings, saveDocumentRecord, setBackendUrl } from "../lib/storage.js";

const els = {
  projectName: document.getElementById("projectName"),
  backendStatus: document.getElementById("backendStatus"),
  documentStatus: document.getElementById("documentStatus"),
  backendUrl: document.getElementById("backendUrl"),
  saveBackendButton: document.getElementById("saveBackendButton"),
  projectSelect: document.getElementById("projectSelect"),
  newProjectTitle: document.getElementById("newProjectTitle"),
  createProjectButton: document.getElementById("createProjectButton"),
  syncButton: document.getElementById("syncButton"),
  openPanelButton: document.getElementById("openPanelButton"),
  feedbackTitle: document.getElementById("feedbackTitle"),
  feedbackBody: document.getElementById("feedbackBody"),
};

let backendUrl = "http://localhost:8000";
let currentContext = null;
let currentRecord = null;
let projects = [];

function setBadge(element, text, tone = "muted") {
  element.textContent = text;
  element.className = `badge badge-${tone}`;
}

function setFeedback(title, body) {
  els.feedbackTitle.textContent = title;
  els.feedbackBody.textContent = body;
}

function setBusy(isBusy, title, body) {
  els.syncButton.disabled = isBusy;
  els.createProjectButton.disabled = isBusy;
  els.saveBackendButton.disabled = isBusy;
  els.projectSelect.disabled = isBusy;
  if (title) setFeedback(title, body);
}

function getSelectedProjectId() {
  const value = Number(els.projectSelect.value);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function getSelectedProjectTitle() {
  const selected = projects.find((project) => project.id === getSelectedProjectId());
  return selected?.title ?? "Not mapped";
}

function renderProjectName() {
  const projectTitle = currentRecord?.projectTitle ?? getSelectedProjectTitle() ?? "Not mapped";
  els.projectName.textContent = projectTitle;
}

function renderDocumentState() {
  const state = deriveSyncState(currentRecord);
  if (state === "SYNCED") {
    setBadge(els.documentStatus, "Synced", "success");
    return;
  }
  if (state === "OUT_OF_SYNC") {
    setBadge(els.documentStatus, "Needs Sync", "warning");
    return;
  }
  if (state === "UNMAPPED") {
    setBadge(els.documentStatus, "Unmapped", "muted");
    return;
  }
  setBadge(els.documentStatus, "Unknown", "muted");
}

function renderProjectSelect() {
  els.projectSelect.innerHTML = "";

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = projects.length ? "Select a project" : "No projects found";
  els.projectSelect.appendChild(placeholder);

  for (const project of projects) {
    const option = document.createElement("option");
    option.value = String(project.id);
    option.textContent = project.title;
    els.projectSelect.appendChild(option);
  }

  if (currentRecord?.projectId) {
    els.projectSelect.value = String(currentRecord.projectId);
  }
}

async function refreshProjects() {
  projects = await listProjects(backendUrl);
  renderProjectSelect();
  renderProjectName();
}

async function mapCurrentDocument(projectId, projectTitle, patch = {}) {
  if (!currentContext) return;
  currentRecord = await saveDocumentRecord(currentContext.documentId, {
    projectId,
    projectTitle,
    documentTitle: currentContext.documentTitle,
    ...patch,
  });
  renderProjectName();
  renderDocumentState();
}

async function ensureMappedProject() {
  const projectId = getSelectedProjectId() ?? currentRecord?.projectId ?? null;
  const projectTitle = getSelectedProjectTitle() || currentRecord?.projectTitle || null;
  if (!projectId || !projectTitle) {
    throw new Error("Select or create a ContinuityEditor project for this Google Doc first.");
  }
  await mapCurrentDocument(projectId, projectTitle);
  return { projectId, projectTitle };
}

async function loadBackendHealth() {
  try {
    await getBackendHealth(backendUrl);
    setBadge(els.backendStatus, "Connected", "success");
  } catch (error) {
    setBadge(els.backendStatus, "Offline", "danger");
    setFeedback("Backend unavailable", coerceErrorMessage(error, "The backend is not responding."));
  }
}

async function initialize() {
  const settings = await getSettings();
  backendUrl = settings.backendUrl;
  els.backendUrl.value = backendUrl;

  currentContext = await getActiveGoogleDocContext();
  if (!currentContext) {
    setFeedback("Open a Google Doc", "The extension only activates on Google Docs manuscript pages.");
    setBadge(els.documentStatus, "Unavailable", "danger");
    els.syncButton.disabled = true;
    els.projectSelect.disabled = true;
    els.openPanelButton.disabled = true;
    return;
  }

  currentRecord = await getDocumentRecord(currentContext.documentId);
  renderProjectName();
  renderDocumentState();
  setFeedback("Ready", "Open the Continuity Panel to view project contradictions, or sync your document.");

  await loadBackendHealth();
  try {
    await refreshProjects();
  } catch (error) {
    setFeedback("Could not load projects", coerceErrorMessage(error, "Check the backend URL and try again."));
  }
}

async function handleSaveBackend() {
  backendUrl = els.backendUrl.value.trim() || backendUrl;
  await setBackendUrl(backendUrl);
  setFeedback("Backend saved", `Using ${backendUrl}`);
  await loadBackendHealth();
  await refreshProjects();
}

async function handleCreateProject() {
  const title = els.newProjectTitle.value.trim();
  if (!title) {
    setFeedback("Project title required", "Enter a manuscript project title first.");
    return;
  }

  setBusy(true, "Creating project", "Preparing a new ContinuityEditor manuscript project.");
  try {
    const project = await createProject(backendUrl, { title });
    els.newProjectTitle.value = "";
    await refreshProjects();
    els.projectSelect.value = String(project.id);
    await mapCurrentDocument(project.id, project.title);
    setFeedback("Project created", `Mapped this Google Doc to ${project.title}.`);
  } catch (error) {
    setFeedback("Could not create project", coerceErrorMessage(error, "The project could not be created."));
  } finally {
    setBusy(false);
  }
}

async function handleProjectSelection() {
  const projectId = getSelectedProjectId();
  const projectTitle = getSelectedProjectTitle();
  if (!projectId) return;
  await mapCurrentDocument(projectId, projectTitle);
  setFeedback("Project mapped", `This Google Doc now points to ${projectTitle}.`);
}

async function runDocumentAction(action) {
  if (!currentContext) {
    throw new Error("Open a Google Doc before using Continuity Editor.");
  }

  const { projectId, projectTitle } = await ensureMappedProject();
  const doc = await fetchGoogleDocument(currentContext.documentId, { interactive: true });
  currentContext.documentTitle = doc.documentTitle;

  if (!doc.documentText.trim()) {
    throw new Error("The Google Doc does not contain any text yet.");
  }

  const response = await syncDocument(backendUrl, projectId, {
    document_id: doc.documentId,
    document_title: doc.documentTitle,
    document_text: doc.documentText,
    document_revision: doc.documentRevision,
  });

  currentRecord = await saveDocumentRecord(doc.documentId, {
    projectId,
    projectTitle,
    documentTitle: doc.documentTitle,
    lastStatus: {
      syncState: response.sync_state,
      currentHash: doc.documentHash,
      currentRevision: doc.documentRevision,
      lastIssueCount: currentRecord?.lastStatus?.lastIssueCount ?? 0,
    },
  });

  renderProjectName();
  renderDocumentState();
  return response;
}



async function handleSync() {
  setBusy(true, "Syncing document...", "Sending the newest manuscript content to the backend memory layer.");
  try {
    const response = await runDocumentAction("sync");
    setFeedback("Sync complete", response.message);
  } catch (error) {
    setFeedback("Sync failed", coerceErrorMessage(error, "The document could not be synced."));
  } finally {
    setBusy(false);
  }
}

async function handleOpenPanel() {
  if (!currentContext) return;
  await openSidePanel(currentContext.tabId);
}

els.saveBackendButton.addEventListener("click", handleSaveBackend);
els.createProjectButton.addEventListener("click", handleCreateProject);
els.projectSelect.addEventListener("change", handleProjectSelection);
els.syncButton.addEventListener("click", handleSync);
els.openPanelButton.addEventListener("click", handleOpenPanel);

document.addEventListener("DOMContentLoaded", initialize);
