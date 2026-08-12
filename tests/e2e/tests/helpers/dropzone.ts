import { expect, type Locator, type Page } from "@playwright/test";

import { assertNoCspViolations } from "./csp";

export const labeledDropzone = (page: Page, fieldLabel: string): Locator =>
  page.locator("label").filter({ has: page.getByLabel(fieldLabel, { exact: true }) });

export const shownFileName = (dropzone: Locator): Locator =>
  dropzone.locator("[data-dropzone-name]").filter({ visible: true });

export const assertDropzoneBlobPreview = async (page: Page, dropzone: Locator): Promise<void> => {
  const preview = dropzone.locator("[data-dropzone-preview]");
  await expect(preview).toHaveAttribute("src", /^blob:/);
  await expect(preview).not.toHaveJSProperty("naturalWidth", 0);
  await assertNoCspViolations(page);
};
