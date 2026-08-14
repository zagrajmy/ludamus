import { expect, type Locator, type Page } from "@playwright/test";

import { assertNoCspViolations } from "./csp";

export const labeledDropzone = (page: Page, fieldLabel: string): Locator =>
  page.locator("label").filter({ has: page.getByLabel(fieldLabel, { exact: true }) });

export const shownFileName = (dropzone: Locator, fileName: string): Locator =>
  dropzone.getByText(fileName, { exact: true }).filter({ visible: true });

export const assertDropzoneBlobPreview = async (page: Page, dropzone: Locator): Promise<void> => {
  const preview = dropzone.locator("[data-dropzone-preview]");
  await expect(preview).toHaveAttribute("src", /^blob:/);
  await expect(preview).not.toHaveJSProperty("naturalWidth", 0);
  await assertNoCspViolations(page);
};
