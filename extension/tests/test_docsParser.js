import { strict as assert } from "node:assert";
import { extractDocumentText } from "../lib/docsParser.js";

async function runTests() {
  // Test basic paragraph extraction
  const simplePayload = {
    body: {
      content: [
        {
          paragraph: {
            elements: [
              { textRun: { content: "Hello " } },
              { textRun: { content: "world." } }
            ]
          }
        }
      ]
    }
  };
  assert.equal(extractDocumentText(simplePayload), "Hello world.");

  // Test tabs
  const tabbedPayload = {
    tabs: [
      {
        documentTab: {
          body: {
            content: [
              { paragraph: { elements: [{ textRun: { content: "Tab 1 Content" } }] } }
            ]
          }
        }
      },
      {
        documentTab: {
          body: {
            content: [
              { paragraph: { elements: [{ textRun: { content: "Tab 2 Content" } }] } }
            ]
          }
        }
      }
    ]
  };
  assert.equal(extractDocumentText(tabbedPayload), "Tab 1 Content\nTab 2 Content");

  console.log("All docsParser tests passed.");
}

runTests().catch(err => {
  console.error(err);
  process.exit(1);
});
