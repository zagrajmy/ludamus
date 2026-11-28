import type { Page } from "@playwright/test";

import fs from "node:fs";
import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { attachArtifacts } from "./helpers/artifacts";
import { assertNoCspViolations, installCspViolationCollector } from "./helpers/csp";
import { expect, test } from "./helpers/fixtures";
import {
  bootstrap,
  type Conversation,
  FakeWorker,
  launcherOf,
  panelOf,
  routeBootstrap,
} from "./helpers/parley";

// A board is a Little Table room in a frame, with Zagrajmy's own chat beside
// it. .env.e2e points LITTLE_TABLE_URL here, and each test answers for this
// origin itself, so the frame loads a real https document and nothing leaves
// the machine. bootstrap_data.py seeds "Crew board", which the e2e-tester has
// opened, and its chat; .board.json names them.
const LITTLE_TABLE = "https://littletable.example.test";
const seeded = JSON.parse(fs.readFileSync(path.join(__dirname, "..", ".board.json"), "utf8")) as {
  chatId: number;
  shareCode: string;
};

async function serveLittleTable(page: Page): Promise<void> {
  await page.route(`${LITTLE_TABLE}/**`, (route) =>
    route.fulfill({
      body: `<h1>Room ${new URL(route.request().url()).pathname}</h1>`,
      contentType: "text/html",
    }),
  );
}

test.describe("Boards", () => {
  test("a board added from its Little Table link opens in a frame and joins the list", async ({
    page,
  }, testInfo) => {
    await serveLittleTable(page);
    await installCspViolationCollector(page);
    const title = `Heist night ${Date.now()}`;

    await page.goto("/boards/");
    await expect(page.getByRole("heading", { name: "My boards", level: 1 })).toBeVisible();
    await page.getByRole("link", { name: "Add board" }).click();

    await expect(page.getByRole("heading", { name: "Add board", level: 1 })).toBeVisible();
    await page.getByLabel("Board name").fill(title);
    // A link to anywhere but Little Table is refused, and says what it wants.
    await page.getByLabel("Little Table link").fill("https://elsewhere.example.test/b/x");
    await page.getByRole("button", { name: "Add board" }).click();
    await expect(
      page.getByText(`Paste a Little Table board link, like ${LITTLE_TABLE}/b/…`),
    ).toBeVisible();

    await page.getByLabel("Little Table link").fill(`${LITTLE_TABLE}/b/heist-42`);
    await page.getByRole("button", { name: "Add board" }).click();

    await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
    // SAFETY: with default-src 'none' the frame loads only when the page's
    // policy names Little Table, so this heading proves the override.
    const frame = page.getByTitle(`${title} on Little Table`);
    await expect(
      frame.contentFrame().getByRole("heading", { name: "Room /b/heist-42" }),
    ).toBeVisible();
    const newTab = page.getByRole("link", { name: "Open in a new tab" });
    await expect(newTab).toHaveAttribute("href", `${LITTLE_TABLE}/b/heist-42?lang=en`);
    await expect(newTab).toHaveAttribute("target", "_blank");
    await assertNoCspViolations(page);
    await analyzePageAccessibility(page);

    // Its creator edits it with the link it was added from.
    await page.getByRole("link", { name: "Edit board" }).click();
    await expect(page.getByLabel("Board name")).toHaveValue(title);
    await expect(page.getByLabel("Little Table link")).toHaveValue(`${LITTLE_TABLE}/b/heist-42`);

    await page.goto("/boards/");
    const listed = page.getByRole("link", { name: new RegExp(`^${title} Yours`, "u") });
    await expect(listed).toBeVisible();
    await expect(page.getByRole("link", { name: /^Crew board Opened/u })).toBeVisible();

    await attachArtifacts(testInfo, {
      facts: { added: title, href: await listed.getAttribute("href"), room: "heist-42" },
      name: "boards-list",
      region: page.getByRole("main"),
    });
  });

  test("the board's chat opens beside the frame", async ({ page }) => {
    const chat: Conversation = {
      canWrite: true,
      id: `conversation:${seeded.chatId}`,
      isAdmin: false,
      kind: "board",
      members: [
        { avatarUrl: "", id: "1", name: bootstrap.user.name },
        { avatarUrl: "", id: "2", name: "Board Host" },
      ],
      name: "Crew board",
      state: "active",
      title: "Crew board",
    };
    await serveLittleTable(page);
    await routeBootstrap(page, [{ conversations: [chat] }]);
    await FakeWorker.install(page);

    await page.goto(`/b/${seeded.shareCode}/`);
    await expect(
      page
        .getByTitle("Crew board on Little Table")
        .contentFrame()
        .getByRole("heading", { name: "Room /b/crew-room" }),
    ).toBeVisible();
    // Not the creator: nothing here changes the board.
    await expect(page.getByRole("link", { name: "Edit board" })).toHaveCount(0);

    await launcherOf(page).click();
    const panel = panelOf(page);
    // The chat opens on this page's own conversation, the board's.
    await expect(panel.getByRole("heading", { name: "Crew board" })).toBeVisible();
    await expect(panel.getByText(bootstrap.copy.emptyBoard)).toBeVisible();
    await analyzePageAccessibility(page);
  });

  test("a guest with the link sees the board and is asked to log in for the chat", async ({
    browser,
  }) => {
    // NOTE: storageState undefined, not {}: the signed-in state must not leak.
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();
    await serveLittleTable(page);

    await page.goto(`/b/${seeded.shareCode}/`);

    await expect(page.getByRole("heading", { name: "Crew board", level: 1 })).toBeVisible();
    await expect(page.getByTitle("Crew board on Little Table")).toBeVisible();
    await expect(page.getByRole("main").getByRole("link", { name: "Log in" })).toHaveAttribute(
      "href",
      new RegExp(`\\?next=/b/${seeded.shareCode}/$`, "u"),
    );
    await expect(page.getByRole("button", { name: "Open chat" })).toHaveCount(0);
    await context.close();
  });
});
