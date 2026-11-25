import { type Locator, type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { foundParty } from "./helpers/parties";

const PHONE = { width: 390, height: 844 };
const INDEX_URL = "/crowd/profile/";

const sheet = (page: Page) => page.getByRole("dialog");
const row = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Profile sections" }).getByRole("link", { name });

// NOTE: the card is a plain div, so the innermost one holding both this party's link
// and a menu button is the card; its ancestors match too and come first. `has` is
// matched inside each div, so it takes page-level locators, not ones under `scope`.
const partyCard = (page: Page, scope: Locator, name: string) =>
  scope
    .locator("div")
    .filter({ has: page.getByRole("link", { name, exact: true }) })
    .filter({ has: page.getByRole("button", { name: "More actions" }) })
    .last();

const dragHandle = async (page: Page, deltaY: number) => {
  const box = await page.getByRole("button", { name: /full height|half height/ }).boundingBox();
  if (!box) throw new Error("The sheet has no handle.");
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + deltaY, { steps: 5 });
  await page.mouse.up();
};

test.describe("Profile on a phone", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(PHONE);
  });

  test("the index lists every section without sideways scrolling", async ({ page }, testInfo) => {
    await page.goto(INDEX_URL);

    await expect(sheet(page)).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Change avatar" })).toBeVisible();
    for (const name of ["Personal Information", "Parties", "Safety", "Notifications", "Privacy"]) {
      await expect(row(page, name)).toBeVisible();
    }
    const overflow = await page.evaluate(() => {
      const { scrollWidth, clientWidth } = document.documentElement;
      return scrollWidth - clientWidth;
    });
    expect(overflow).toBeLessThanOrEqual(0);

    await attachArtifacts(testInfo, {
      name: "profile-phone-index",
      region: page.locator("main"),
      facts: { viewport: PHONE, overflow },
    });
  });

  test("each section opens in a sheet and back returns to the index", async ({ page }) => {
    await page.goto(INDEX_URL);

    for (const [name, url] of [
      ["Parties", /profile\/parties\/$/],
      ["Safety", /profile\/safety\/$/],
      ["Notifications", /profile\/notifications\/$/],
      ["Privacy", /profile\/privacy\/$/],
    ] as const) {
      await row(page, name).click();
      await expect(page).toHaveURL(url);
      await expect(sheet(page).getByRole("heading", { name, level: 1 })).toBeVisible();
      await page.goBack();
      await expect(sheet(page)).toHaveCount(0);
    }
  });

  test("Personal Information opens in place and closes without a reload", async ({ page }) => {
    await page.goto(INDEX_URL);

    await row(page, "Personal Information").click();
    await expect(sheet(page).getByRole("button", { name: "Save" })).toBeVisible();

    await sheet(page).getByRole("link", { name: "Close" }).click();
    await expect(sheet(page)).toHaveCount(0);
    await expect(page).toHaveURL(/profile\/$/);
  });

  test("a direct link opens the sheet and Close lands on the index", async ({ page }) => {
    await page.goto("/crowd/profile/notifications/");

    await expect(sheet(page).getByRole("heading", { name: "Notifications" })).toBeVisible();
    await sheet(page).getByRole("link", { name: "Close" }).click();

    await expect(page).toHaveURL(/profile\/$/);
    await expect(row(page, "Notifications")).toBeVisible();
  });

  test("Escape closes the sheet", async ({ page }) => {
    await page.goto(INDEX_URL);
    await row(page, "Notifications").click();
    await expect(sheet(page)).toBeVisible();

    await page.keyboard.press("Escape");

    await expect(page).toHaveURL(/profile\/$/);
  });

  test("Parties opens full height, other sections half", async ({ page }) => {
    await page.goto("/crowd/profile/parties/");
    await expect(sheet(page)).toBeVisible();
    const full = (await sheet(page).boundingBox())?.height ?? 0;

    await page.goto("/crowd/profile/notifications/");
    await expect(sheet(page)).toBeVisible();
    const half = (await sheet(page).boundingBox())?.height ?? 0;

    expect(full).toBeGreaterThan(PHONE.height * 0.9);
    expect(half).toBeLessThan(PHONE.height * 0.7);
  });

  test("the handle resizes the sheet by drag and by keyboard", async ({ page }) => {
    await page.goto("/crowd/profile/notifications/");
    await expect(sheet(page)).toBeVisible();

    await dragHandle(page, -120);
    await expect(page.getByRole("button", { name: "Shrink to half height" })).toBeVisible();
    await expect(async () => {
      expect((await sheet(page).boundingBox())?.height).toBeGreaterThan(PHONE.height * 0.9);
    }).toPass();

    await page.getByRole("button", { name: "Shrink to half height" }).press("Enter");
    await expect(page.getByRole("button", { name: "Expand to full height" })).toBeVisible();
    await expect(async () => {
      expect((await sheet(page).boundingBox())?.height).toBeLessThan(PHONE.height * 0.7);
    }).toPass();

    await dragHandle(page, 120);
    await expect(page).toHaveURL(/profile\/$/);
  });

  test("a half-filled form asks before it is dragged away", async ({ page }) => {
    await page.goto(INDEX_URL);
    await row(page, "Personal Information").click();
    await sheet(page).getByLabel(/name/i).first().fill("Half typed");

    await sheet(page).getByRole("link", { name: "Close" }).click();

    const confirm = page.getByRole("alertdialog");
    await expect(confirm).toContainText("Discard your unsaved changes?");
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(sheet(page).getByLabel(/name/i).first()).toHaveValue("Half typed");

    await sheet(page).getByRole("link", { name: "Close" }).click();
    await confirm.getByRole("button", { name: "Discard" }).click();
    await expect(sheet(page)).toHaveCount(0);
  });

  test("a validation error reopens the sheet with the error in it", async ({ page }) => {
    await page.goto(INDEX_URL);
    await row(page, "Personal Information").click();
    const email = sheet(page).getByLabel("email address", { exact: true });
    await email.fill("not-an-email");
    await email.evaluate((input: HTMLInputElement) => {
      if (input.form) input.form.noValidate = true;
    });

    await sheet(page).getByRole("button", { name: "Save" }).click();

    await expect(
      sheet(page)
        .getByText(/valid email/i)
        .first(),
    ).toBeVisible();
  });

  test("an error opens at full height after the sheet was shrunk", async ({ page }) => {
    await page.goto(INDEX_URL);
    await row(page, "Personal Information").click();
    const email = sheet(page).getByLabel("email address", { exact: true });
    await email.fill("not-an-email");
    await email.evaluate((input: HTMLInputElement) => {
      if (input.form) input.form.noValidate = true;
    });
    await page.getByRole("button", { name: "Shrink to half height" }).press("Enter");
    await expect(page.getByRole("button", { name: "Expand to full height" })).toBeVisible();

    await sheet(page).getByRole("button", { name: "Save" }).click();

    await expect(
      sheet(page)
        .getByText(/valid email/i)
        .first(),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Shrink to half height" })).toBeVisible();
    await expect(async () => {
      expect((await sheet(page).boundingBox())?.height).toBeGreaterThan(PHONE.height * 0.9);
    }).toPass();
  });

  test("only a next page opens Personal Information from the address", async ({ page }) => {
    await page.goto(`${INDEX_URL}?utm_source=mail`);
    await expect(row(page, "Personal Information")).toBeVisible();
    await expect(sheet(page)).toHaveCount(0);

    await page.goto(`${INDEX_URL}?next=/`);
    await expect(sheet(page).getByRole("button", { name: "Save" })).toBeVisible();
  });

  test("a sub-page closes to its section, and modals, menus and flashes work over the sheet", async ({
    page,
  }) => {
    const { name } = await foundParty(page, "Sheet");
    await page.getByRole("dialog", { name }).getByRole("link", { name: "Close" }).click();
    await expect(page).toHaveURL(/profile\/parties\/$/);

    const sections = page.getByRole("dialog", { name: "Parties" });
    const card = partyCard(page, sections, name);
    await card.getByRole("button", { name: "More actions" }).click();
    await card.getByRole("button", { name: "Remove" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete party" }).click();

    await expect(page.getByText("Party deleted.")).toBeInViewport();
    await expect(sections.getByText(name)).toHaveCount(0);
  });
});

test.describe("Profile on a desktop", () => {
  test("the section stays a card with no sheet chrome", async ({ page }, testInfo) => {
    await page.goto("/crowd/profile/parties/");

    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Close" })).toBeHidden();
    await expect(page.getByRole("button", { name: /full height/ })).toBeHidden();
    await expect(row(page, "Parties")).toHaveAttribute("aria-current", "page");

    await attachArtifacts(testInfo, {
      name: "profile-desktop",
      region: page.locator("main"),
      facts: { section: "Parties" },
    });
  });
});
