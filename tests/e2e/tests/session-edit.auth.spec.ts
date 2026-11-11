import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { DENSE_EVENT_URL } from "./helpers/urls";

const SEEDED_DESCRIPTION = "A session its presenter can edit from the modal.";

test.describe("Editing a scheduled session from its modal", () => {
  test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

  test("saving an edit closes the modal and the card shows it", async ({ page }) => {
    const edited = `Edited from the modal ${Date.now()}`;
    await page.goto("/event/facilitator-edit-demo/");
    const card = page.locator("[data-session-card]").filter({ hasText: "Own Table Demo" });
    await page.getByRole("link", { name: "Open details for Own Table Demo" }).press("Enter");
    const dialog = page.getByRole("dialog", { name: "Own Table Demo" });
    await dialog.getByRole("button", { name: "Edit session" }).click();

    try {
      await dialog.getByLabel("Description").fill(edited);
      await dialog.getByRole("button", { name: "Save changes" }).click();

      // No "Saved" state to read and dismiss: the dialog is done and goes.
      await expect(dialog).toBeHidden();
      await expect(page).not.toHaveURL(/[?&]session=/);
      await expect(card).toContainText(edited);

      // The swapped-in card answers the search like the cards booted with the page.
      const search = page.getByRole("textbox", { name: "Search by name or text..." });
      await search.fill("no session is called this");
      await expect(card).toBeHidden();
      await search.fill(edited);
      await expect(card).toBeVisible();
      await search.fill("");
      await attachArtifacts(test.info(), {
        name: "session-edit-saved-card",
        region: card,
        facts: { description: edited },
      });

      // Reopening shows the edit, not the dialog cached before it.
      await page.getByRole("link", { name: "Open details for Own Table Demo" }).press("Enter");
      await expect(dialog).toContainText(edited);
    } finally {
      await page.goto("/event/facilitator-edit-demo/");
      await page.getByRole("link", { name: "Open details for Own Table Demo" }).press("Enter");
      await dialog.getByRole("button", { name: "Edit session" }).click();
      await dialog.getByLabel("Description").fill(SEEDED_DESCRIPTION);
      await dialog.getByRole("button", { name: "Save changes" }).click();
      await expect(dialog).toBeHidden();
    }
  });

  test("an overnight session's rows each come back as their own day's", async ({ page }) => {
    await page.goto(DENSE_EVENT_URL);
    const sessionId = await page.locator("[data-session-card]").evaluateAll((cards) => {
      const days = new Map<string, Set<string>>();
      for (const card of cards as HTMLElement[]) {
        const id = card.dataset.sessionCard;
        const day = card.querySelector<HTMLElement>("[data-day]")?.dataset.day;
        if (id && day) days.set(id, (days.get(id) ?? new Set<string>()).add(day));
      }
      return [...days].find(([, seen]) => seen.size > 1)?.[0] ?? null;
    });
    if (!sessionId) throw new Error("The fixture needs an overnight session");
    const rows = page.locator(`[data-session-card="${sessionId}"]`);
    const startsOf = () =>
      rows
        .locator("[data-start]")
        .evaluateAll((els) => els.map((el) => el.getAttribute("data-start")));
    const starts = await startsOf();
    expect(starts).toHaveLength(2);

    const dialog = page.locator(`#session-${sessionId}`);
    await rows.first().locator("a.session-link").press("Enter");
    await expect(dialog).toBeVisible();
    // What a save answers with; only a session's own presenter can save one
    // from the modal, and this fixture's are not who browses it here.
    await page.evaluate((id) => {
      document.body.dispatchEvent(new CustomEvent("session-saved", { detail: { id: Number(id) } }));
    }, sessionId);
    await expect(dialog).toBeHidden();
    await page.waitForLoadState("networkidle");

    // One fresh row per day, not both pieces where the first one stood.
    await expect(rows).toHaveCount(2);
    expect(await startsOf()).toEqual(starts);
    await attachArtifacts(test.info(), {
      name: "overnight-session-refreshed",
      region: rows.first(),
      facts: { sessionId, starts },
    });
  });
});

test.describe("Editing a proposal still waiting for acceptance", () => {
  test.use({ storageState: path.join(__dirname, "..", ".auth-state-proposal-author.json") });

  test("its author edits it from their pending card", async ({ page }) => {
    const seeded = "Still Waiting Table";
    const title = `${seeded} ${Date.now()}`;
    await page.goto("/event/facilitator-edit-demo/");
    await page.getByRole("link", { name: `Edit proposal ${seeded}` }).click();
    await expect(page.getByRole("heading", { name: "Edit proposal", level: 1 })).toBeVisible();

    try {
      await page.getByLabel("Title").fill(title);
      await page.getByRole("button", { name: "Save changes" }).click();

      await expect(page).toHaveURL(/\/event\/facilitator-edit-demo\/$/);
      await expect(page.getByText("Your changes are saved.")).toBeVisible();
      const card = page.locator("[data-session-card]").filter({ hasText: title });
      await expect(card).toBeVisible();
      await attachArtifacts(test.info(), {
        name: "pending-proposal-edited",
        region: card,
        facts: { title },
      });
    } finally {
      // Put the seeded title back, saved or not, so a rerun finds the card.
      await page.goto("/event/facilitator-edit-demo/");
      await page.getByRole("link", { name: new RegExp(`^Edit proposal ${seeded}`) }).click();
      await page.getByLabel("Title").fill(seeded);
      await page.getByRole("button", { name: "Save changes" }).click();
      await expect(page.getByText("Your changes are saved.")).toBeVisible();
    }
  });
});
