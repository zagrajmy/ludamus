import type { Locator, Page } from "@playwright/test";

import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { installCspViolationCollector } from "./helpers/csp";
import { assertDropzoneBlobPreview, labeledDropzone } from "./helpers/dropzone";
import { expect, test } from "./helpers/fixtures";
import { visualDiff } from "./helpers/visual-diff";

const PNG_BYTES = Buffer.from(
  "89504e470d0a1a0a0000000d4948445200000001000000010802000000" +
    "907753de0000000c49444154789c63606060000000040001f6173855" +
    "0000000049454e44ae426082",
  "hex",
);

const pastEventUrl = "/chronology/event/mothership-nights-1/";
const proposeUrl = "/event/mothership-nights-2/session/propose/";
const title = "First time at the table? Play Mothership";

// The facts row is labelled while proposing and bare in the modal, and the
// organizer's fields are asked as a form, so both differ by design; the
// description between them has to read the same once the outlines that mark
// a field as editable are set aside.
const belowFacts = async (page: Page, info: Locator): Promise<Buffer> => {
  await info.evaluate((root) => {
    for (const el of root.querySelectorAll<HTMLElement>("input, textarea, select")) {
      el.style.outline = "none";
    }
  });
  const root = (await info.boundingBox())!;
  const facts = (await info.locator("[data-session-facts]").boundingBox())!;
  const fields = (await info.locator("[data-session-fields]").boundingBox())!;
  const top = Math.round(facts.y + facts.height);
  return page.screenshot({
    animations: "disabled",
    clip: {
      x: Math.round(root.x),
      y: top,
      width: Math.round(root.width),
      height: Math.round(fields.y) - top,
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

    await page.getByRole("button", { name: "Copy from an earlier session" }).click();
    await page.getByRole("button", { name: title }).click();

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
    expect(diff.ratio).toBeLessThan(0.01);

    await page.getByRole("button", { name: "Undo" }).click();
    await expect(form.getByRole("textbox", { name: "Title" })).toHaveValue("");
    await expect(form.getByLabel("System")).toHaveValue("");
    await expect(form.getByText("extension cord")).toHaveCount(0);

    await page.getByRole("button", { name: "Copy from an earlier session" }).click();
    await page.getByRole("button", { name: title }).click();
    await page.getByRole("button", { name: /Continue/ }).click();
    const wizard = page.locator('[id="wizard-content"]');
    await expect(wizard.getByRole("heading", { name: "Review & Submit" })).toBeVisible();
    await expect(wizard.getByText("Mothership 1e")).toBeVisible();
    await page.getByRole("button", { name: "Submit Proposal" }).click();
    await expect(page.getByText(title).first()).toBeVisible();
  });

  test("previews a picked cover at the shape the help text asks for", async ({ page }) => {
    await installCspViolationCollector(page);
    await page.goto(proposeUrl);
    const dropzone = labeledDropzone(page, "Cover image");
    await page.getByLabel("Cover image", { exact: true }).setInputFiles({
      name: "cover.png",
      mimeType: "image/png",
      buffer: PNG_BYTES,
    });
    await assertDropzoneBlobPreview(page, dropzone);
    const guide = dropzone.locator("[data-dropzone-safe-zone]");
    await expect(guide).toBeVisible();

    const ratios: Record<number, number> = {};
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 1400 });
      const previewBox = (await dropzone.locator("[data-dropzone-preview]").boundingBox())!;
      const guideBox = (await guide.boundingBox())!;
      ratios[width] = previewBox.width / previewBox.height;
      expect(ratios[width]).toBeCloseTo(16 / 9, 1);
      expect(guideBox.height / previewBox.height).toBeCloseTo(0.28, 2);
    }
    await attachArtifacts(test.info(), {
      name: "propose-cover-preview",
      region: dropzone,
      facts: { ratios },
    });
  });

  test("keeps the age's + clear of whatever is typed", async ({ page }) => {
    await page.goto(proposeUrl);
    const age = page.locator("#propose-details-form").getByLabel("Minimum age");
    const gap: Record<string, number> = {};
    for (const value of ["0", "16", "1411", "99999999", "-5", "1e5"]) {
      await age.fill(value);
      await age.blur();
      // Where the centered value ends, measured in the input's own font,
      // against where the unit drawn beside it starts.
      gap[value] = await age.evaluate((input: HTMLInputElement) => {
        const style = getComputedStyle(input);
        const probe = document.createElement("span");
        probe.style.font = style.font;
        probe.style.letterSpacing = style.letterSpacing;
        probe.style.whiteSpace = "pre";
        probe.style.position = "absolute";
        probe.textContent = input.value;
        document.body.append(probe);
        const drawn = probe.getBoundingClientRect().width;
        probe.remove();
        const box = input.getBoundingClientRect();
        const left = box.left + parseFloat(style.paddingLeft);
        const room = box.right - parseFloat(style.paddingRight) - left;
        const textEnd = left + (room + drawn) / 2;
        const unit = input.nextElementSibling!.getBoundingClientRect();
        return unit.left - textEnd;
      });
    }
    await attachArtifacts(test.info(), {
      name: "propose-min-age-unit",
      region: age.locator("xpath=../.."),
      facts: { gap },
    });
    for (const [value, px] of Object.entries(gap)) {
      expect(px, `gap before + for ${value}`).toBeGreaterThanOrEqual(0);
    }
  });

  test("still offers earlier sessions after the step comes back with errors", async ({ page }) => {
    await page.goto(proposeUrl);
    const form = page.locator("#propose-details-form");
    // Past the browser's own checks, so the server answers with the step again.
    await form.evaluate((el: HTMLFormElement) => {
      el.noValidate = true;
    });
    await page.getByRole("button", { name: /Continue/ }).click();
    await expect(form.getByRole("textbox", { name: "Title" })).toHaveAttribute(
      "aria-invalid",
      "true",
    );

    await page.getByRole("button", { name: "Copy from an earlier session" }).click();
    await page.getByRole("button", { name: title }).click();
    await expect(form.getByRole("textbox", { name: "Title" })).toHaveValue(title);
  });
});
