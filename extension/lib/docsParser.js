function extractParagraphText(paragraph) {
  if (!paragraph?.elements) return "";
  return paragraph.elements
    .map((element) => {
      if (element.textRun?.content) return element.textRun.content;
      if (element.autoText?.content) return element.autoText.content;
      if (element.person?.personProperties?.name) return element.person.personProperties.name;
      if (element.richLink?.richLinkProperties?.title) return element.richLink.richLinkProperties.title;
      if (element.dateElement?.date) return element.dateElement.date;
      return "";
    })
    .join("");
}

function extractFromStructuralElements(elements = []) {
  const parts = [];
  for (const element of elements) {
    if (element.paragraph) {
      parts.push(extractParagraphText(element.paragraph));
      continue;
    }
    if (element.table?.tableRows) {
      for (const row of element.table.tableRows) {
        for (const cell of row.tableCells ?? []) {
          parts.push(extractFromStructuralElements(cell.content ?? []));
        }
      }
      continue;
    }
    if (element.tableOfContents?.content) {
      parts.push(extractFromStructuralElements(element.tableOfContents.content));
    }
  }
  return parts.join("");
}

function extractFromTab(tab) {
  const parts = [];
  if (tab?.documentTab?.body?.content) {
    parts.push(extractFromStructuralElements(tab.documentTab.body.content));
  }
  for (const child of tab?.childTabs ?? []) {
    parts.push(extractFromTab(child));
  }
  return parts.join("\n");
}

export function extractDocumentText(documentPayload) {
  if (!documentPayload || typeof documentPayload !== "object") {
    throw new Error("Google Docs did not return a readable document payload.");
  }

  if (Array.isArray(documentPayload.tabs) && documentPayload.tabs.length > 0) {
    return documentPayload.tabs.map((tab) => extractFromTab(tab)).join("\n").trim();
  }

  return extractFromStructuralElements(documentPayload.body?.content ?? []).trim();
}
