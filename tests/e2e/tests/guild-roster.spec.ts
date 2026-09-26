import { type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// NOTE: "Saltmarsh Moot" (bootstrap_data.py) holds Mira Kestrel twice,
// imported with no account, so one "Add presenter" places both of her rows.
// The two guilds are this spec's own; deleting a guild clears the mark off her
// rows, so each run starts with her unattached.
const FROM = "Czaple";
const TO = "Mewy";
const PRESENTER = "Mira Kestrel";
const EVENT = "Saltmarsh Moot";
const GUILDS_URL = "/multiverse/panel/guilds/";

const guildRow = (page: Page, name: string) =>
  page.getByRole("row").filter({ has: page.getByRole("cell", { name, exact: true }) });

const presenterRows = (page: Page) => page.getByRole("listitem").filter({ hasText: PRESENTER });

const deleteGuildIfPresent = async (page: Page, name: string): Promise<void> => {
  await page.goto(GUILDS_URL);
  if ((await guildRow(page, name).count()) === 0) return;
  await guildRow(page, name).getByRole("link", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete guild" }).click();
  await expect(guildRow(page, name)).toHaveCount(0);
};

const createGuild = async (page: Page, name: string): Promise<void> => {
  await page.goto(`${GUILDS_URL}create/`);
  await page.getByLabel("Guild name").fill(name);
  await page.getByRole("button", { name: "Create guild" }).click();
  await expect(guildRow(page, name)).toBeVisible();
};

const addPresenter = async (page: Page): Promise<void> => {
  await page.getByLabel("Name, email or Discord username").fill(PRESENTER);
  await page.getByRole("button", { name: "Add presenter" }).click();
};

test.describe("Guild roster", () => {
  test.beforeEach(async ({ page }) => {
    await signInAsManager(page);
    await deleteGuildIfPresent(page, FROM);
    await deleteGuildIfPresent(page, TO);
  });

  test("a manager moves a presenter to another guild, is told so, and cannot add her twice", async ({
    page,
  }, testInfo) => {
    await createGuild(page, FROM);
    await createGuild(page, TO);

    await guildRow(page, FROM).getByRole("link", { name: "Edit" }).click();
    await addPresenter(page);
    await expect(page.getByText("Presenter added.")).toBeVisible();
    await expect(presenterRows(page)).toHaveCount(2);

    await page.goto(GUILDS_URL);
    await guildRow(page, TO).getByRole("link", { name: "Edit" }).click();
    await addPresenter(page);
    await expect(page.getByText("Presenter moved to this guild from another one.")).toBeVisible();
    await expect(presenterRows(page)).toHaveCount(2);
    for (const row of await presenterRows(page).all()) {
      await expect(row).toContainText(EVENT);
    }

    await addPresenter(page);
    await expect(page.getByText("That presenter is already in this guild.")).toBeVisible();
    await page.reload();
    await expect(presenterRows(page)).toHaveCount(2);

    await page.goto(GUILDS_URL);
    await guildRow(page, FROM).getByRole("link", { name: "Edit" }).click();
    await expect(page.getByText("Nobody in this guild yet.")).toBeVisible();

    await page.goto(GUILDS_URL);
    await expect(guildRow(page, FROM).getByRole("cell").nth(1)).toHaveText("0");
    await expect(guildRow(page, TO).getByRole("cell").nth(1)).toHaveText("2");
    const facts = {
      presenter: PRESENTER,
      presentersPerGuild: {
        [FROM]: (await guildRow(page, FROM).getByRole("cell").nth(1).innerText()).trim(),
        [TO]: (await guildRow(page, TO).getByRole("cell").nth(1).innerText()).trim(),
      },
    };
    await attachArtifacts(testInfo, {
      name: "guild-roster",
      region: page.getByRole("table"),
      facts,
    });

    await test.step("a delete confirmed from a stale tab says the guild is gone", async () => {
      await guildRow(page, TO).getByRole("link", { name: "Delete" }).click();
      const staleTab = await page.context().newPage();
      await staleTab.goto(page.url());
      await page.getByRole("button", { name: "Delete guild" }).click();
      await expect(page.getByText("Guild deleted.")).toBeVisible();
      await staleTab.getByRole("button", { name: "Delete guild" }).click();
      await expect(staleTab.getByText("Guild not found.")).toBeVisible();
      await expect(guildRow(staleTab, TO)).toHaveCount(0);
      await staleTab.close();
    });
  });
});
