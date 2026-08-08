import { hashDocumentText } from "./state.js";

export async function fetchGoogleDocument(documentId, { interactive = false } = {}) {
  // Rather than using OAuth, we leverage the user's existing Google Docs session 
  // via host permissions to fetch the raw text export of the document.
  try {
    const response = await fetch(`https://docs.google.com/document/export?format=txt&id=${documentId}`);
    
    if (!response.ok) {
      if (response.status === 401 || response.status === 403 || response.status === 404) {
        throw new Error("Cannot access document. Ensure you are logged into Google Docs and have permission to view it.");
      }
      throw new Error(`Failed to fetch document text (HTTP ${response.status}).`);
    }

    const rawText = await response.text();
    
    return {
      documentId,
      documentTitle: "Google Document", // The UI normally overwrites this using currentContext.documentTitle
      documentRevision: Date.now().toString(), // No revision from export; mock it
      documentText: rawText,
      documentHash: await hashDocumentText(rawText),
    };
  } catch (error) {
    if (error.message === "Failed to fetch") {
      throw new Error("Network error when trying to read the Google Doc. Are you online?");
    }
    throw error;
  }
}
