import type { Locator, Page } from "@playwright/test";

import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { visualDiff } from "./helpers/visual-diff";

const pastEventUrl = "/chronology/event/mothership-nights-1/";
const proposeUrl = "/event/mothership-nights-2/session/propose/";
const title = "First time at the table? Play Mothership";

// The facts row is labelled while proposing and bare in the modal, so it
// differs by design; everything under it has to read the same once the
// outlines that mark a field as editable are set aside.
const belowFacts = async (page: Page, info: Locator): Promise<Buffer> => {
  await info.evaluate((root) => {
    for (const el of root.querySelectorAll<HTMLElement>("input, textarea, select")) {
      el.style.outline = "none";
    }
  });
  const root = (await info.boundingBox())!;
  const facts = (await info.locator("[data-session-facts]").boundingBox())!;
  const top = Math.round(facts.y + facts.height);
  return page.screenshot({
    animations: "disabled",
    clip: {
      x: Math.round(root.x),
      y: top,
      width: Math.round(root.width),
      height: Math.round(root.y + root.height) - top,
    },
  });
};

test.use({
  storageState: path.join(__dirname, "..", ".auth-state-reuser.json"),
  // Tall enough that the whole modal body fits without scrolling under its footer.
  viewport: { width: 1280, height: 1400 },
});

test.describe("Proposing from an earlier session", () => {
  test("copies a past session in place and reads like its modal", async ({ page, browser }) => {
    await page.goto(pastEventUrl);
    await page.getByRole("link", { name: `Open details for ${title}` }).press("Enter");
    const modal = page.getByRole("dialog", { name: title });
    await expect(modal).toBeVisible();
    // The dialog springs open past its size; measure it once it has settled.
    await modal.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
    const modalInfo = await belowFacts(page, modal.locator("[data-session-info]"));

    await page.goto(proposeUrl);
    const form = page.locator("#propose-details-form");
    await expect(form.getByRole("textbox", { name: "Title" })).toHaveValue("");

    await page.getByText("Copy from an earlier session").click();
    await page.getByRole("button", { name: `Copy ${title}` }).click();

    await expect(form.getByRole("textbox", { name: "Title" })).toHaveValue(title);
    await expect(form.getByLabel("Presenter name")).toHaveValue("Ola Wrzos");
    await expect(form.getByLabel("About this session")).toHaveValue(/Prospero's mining station/);
    await expect(form.getByLabel("System")).toHaveValue("Mothership 1e");
    await expect(form.getByLabel("Audience")).toHaveValue("Beginners");
    await expect(form.getByLabel("Seats")).toHaveValue("4");
    await expect(form.getByLabel("Minimum age")).toHaveValue("16");
    await expect(form.getByLabel("Duration")).toHaveValue("PT2H");
    await expect(form.getByLabel("Anything the organizers should know?")).toHaveValue(
      "A table near a socket, please.",
    );
    const equipment = form.getByRole("group", { name: /What do you need at the table\?/ });
    await expect(equipment.getByRole("checkbox", { name: "Projector" })).toBeChecked();
    await expect(form.getByText("extension cord")).toBeVisible();

    await page.mouse.move(0, 0);
    await page
      .locator("body")
      .evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    const proposeInfo = await belowFacts(page, form.locator("[data-session-info]"));

    const diff = await visualDiff(browser, test.info(), {
      name: "session-info-modal-vs-propose",
      a: modalInfo,
      b: proposeInfo,
    });
    await attachArtifacts(test.info(), {
      name: "propose-copied",
      region: form,
      facts: { title, diff },
    });
    // Only the select's chevron may differ.
    expect(diff.ratio).toBeLessThan(0.01);

    await page.getByRole("button", { name: "Undo" }).click();
    await expect(form.getByRole("textbox", { name: "Title" })).toHaveValue("");
    await expect(form.getByLabel("System")).toHaveValue("");
    await expect(form.getByText("extension cord")).toHaveCount(0);

    await page.getByRole("button", { name: `Copy ${title}` }).click();
    await page.getByRole("button", { name: /Continue/ }).click();
    const wizard = page.locator('[id="wizard-content"]');
    await expect(wizard.getByRole("heading", { name: "Review & Submit" })).toBeVisible();
    await expect(wizard.getByText("Mothership 1e")).toBeVisible();
    await page.getByRole("button", { name: "Submit Proposal" }).click();
    await expect(page.getByText(title).first()).toBeVisible();
  });
});
