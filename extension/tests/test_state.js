import { strict as assert } from "node:assert";
import {
  hashDocumentText,
  stripGoogleDocsSuffix,
  coerceErrorMessage,
  deriveSyncState,
} from "../lib/state.js";

async function runTests() {
  // test stripGoogleDocsSuffix
  assert.equal(stripGoogleDocsSuffix("My Novel - Google Docs"), "My Novel");
  assert.equal(stripGoogleDocsSuffix("My Novel- Google Docs"), "My Novel");
  assert.equal(stripGoogleDocsSuffix("My Novel"), "My Novel");
  assert.equal(stripGoogleDocsSuffix("   My Novel   - Google Docs  "), "My Novel");

  // test hashDocumentText
  const hash1 = await hashDocumentText("Hello world");
  const hash2 = await hashDocumentText("Hello world");
  const hash3 = await hashDocumentText("Different");
  assert.equal(hash1, hash2, "Hashes of identical text should match");
  assert.notEqual(hash1, hash3, "Hashes of different text should not match");
  assert.equal(await hashDocumentText(""), await hashDocumentText("   "), "Empty or whitespace should hash identically");

  // test coerceErrorMessage
  assert.equal(coerceErrorMessage(new Error("Network failed"), "Fallback"), "Network failed");
  assert.equal(coerceErrorMessage(null, "Fallback"), "Fallback");

  // test deriveSyncState
  assert.equal(deriveSyncState(null), "UNMAPPED");
  assert.equal(deriveSyncState({}), "UNMAPPED");
  assert.equal(deriveSyncState({ projectId: 123 }), "UNKNOWN");
  
  const recordSynced = {
    projectId: 123,
    lastStatus: { syncState: "SYNCED" }
  };
  assert.equal(deriveSyncState(recordSynced), "SYNCED");
  
  const recordAnalysisSynced = {
    projectId: 123,
    lastAnalysis: { sync_state: "SYNCED" }
  };
  assert.equal(deriveSyncState(recordAnalysisSynced), "SYNCED");
  
  // Prefer analysis over status
  const conflictRecord = {
    projectId: 123,
    lastStatus: { syncState: "SYNCED" },
    lastAnalysis: { sync_state: "OUT_OF_SYNC" }
  };
  assert.equal(deriveSyncState(conflictRecord), "OUT_OF_SYNC");

  console.log("All state tests passed.");
}

runTests().catch(err => {
  console.error(err);
  process.exit(1);
});
