import { coerceErrorMessage, parseCheckResponse } from "./state.js";

async function requestJson(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 30000);

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers ?? {}),
      },
      signal: controller.signal,
    });

    const text = await response.text();
    let body = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
    }

    if (!response.ok) {
      const detail = body?.detail || body?.message || `Backend request failed with status ${response.status}.`;
      throw new Error(detail);
    }

    return body;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("The backend request timed out.");
    }
    throw new Error(coerceErrorMessage(error, "The backend request failed."));
  } finally {
    clearTimeout(timeout);
  }
}

function withProjectPath(backendUrl, projectId, suffix) {
  const base = backendUrl.replace(/\/$/, "");
  return `${base}/projects/${projectId}${suffix}`;
}

export function getBackendHealth(backendUrl) {
  const base = backendUrl.replace(/\/$/, "");
  return requestJson(`${base}/health`, { method: "GET", timeoutMs: 5000 });
}

export function listProjects(backendUrl) {
  const base = backendUrl.replace(/\/$/, "");
  return requestJson(`${base}/projects`, { method: "GET" });
}

export function createProject(backendUrl, payload) {
  const base = backendUrl.replace(/\/$/, "");
  return requestJson(`${base}/projects`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getExtensionStatus(backendUrl, projectId, params) {
  const url = new URL(withProjectPath(backendUrl, projectId, "/extension/status"));
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  return requestJson(url.toString(), { method: "GET" });
}

export async function getProjectRecall(backendUrl, projectId) {
  const body = await requestJson(withProjectPath(backendUrl, projectId, "/recall"), {
    method: "POST",
    body: JSON.stringify({}), // Send empty body just like viewer
  });
  return body;
}

export async function checkDocument(backendUrl, projectId, payload) {
  const body = await requestJson(withProjectPath(backendUrl, projectId, "/extension/check"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return parseCheckResponse(body);
}

export function syncDocument(backendUrl, projectId, payload) {
  return requestJson(withProjectPath(backendUrl, projectId, "/extension/sync"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
