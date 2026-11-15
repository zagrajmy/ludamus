import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// slot-con lists two time slots (10:00–14:00 and 14:00–18:00), so proposers
// pick from those instead of parts of a day, and the slot a proposal picked
// travels to its card and to the accept page. Submitting adds a proposal, so
// the scenarios run in order.
test.describe.configure({ mode: "serial" });

const EVENT_URL = "/event/slot-con/";
const SEEDED = "Afternoon Block Proposal";

test.describe("Time slots as availability", () => {
  test("a proposer picks one of the event's slots, not a part of a day", async ({ page }) => {
    await page.goto(`${EVENT_URL}session/propose/`);

    const wizard = page.locator('[id="wizard-content"]');
    await expect(wizard.getByRole("heading", { name: "Your Information" })).toBeVisible();
    await page.getByLabel(/contact email/i).fill("slots@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();

    await expect(wizard.getByRole("heading", { name: "When could you host?" })).toBeVisible();
    await expect(wizard.getByRole("checkbox", { name: "10:00–14:00" })).toBeVisible();
    await expect(wizard.getByRole("checkbox", { name: "Evening" })).toHaveCount(0);
    await wizard.getByRole("checkbox", { name: "14:00–18:00" }).check();
    await page.getByRole("button", { name: /Continue/ }).click();

    await expect(wizard.getByRole("heading", { name: "Session Details" })).toBeVisible();
    await page.getByLabel(/title/i).fill("Picked Block");
    await page.getByLabel(/about this session/i).fill("Runs in the afternoon block.");
    await page.getByLabel(/seats/i).fill("4");
    await page.getByLabel(/presenter name/i).fill("Block Host");
    await page.getByRole("button", { name: /Continue/ }).click();

    await expect(wizard.getByRole("heading", { name: "Review & Submit" })).toBeVisible();
    await expect(wizard.getByText("14:00–18:00")).toBeVisible();
    await expect(wizard.getByText("10:00–14:00")).toHaveCount(0);
    await page.getByRole("button", { name: "Submit Proposal" }).click();

    await expect(page.getByText("Picked Block")).toBeVisible();
  });

  test.describe("as the organizer", () => {
    test.use({ storageState: managerState });

    test("the card names the slot the proposal picked", async ({ page }) => {
      await page.goto(EVENT_URL);

      const card = page
        .getByRole("region", { name: "Proposals to review" })
        .getByRole("article")
        .filter({ has: page.getByRole("heading", { name: SEEDED }) });
      await expect(card).toContainText("14:00–18:00");
    });

    test("the accept page opens where the picked slot opens", async ({ page }) => {
      await page.goto(EVENT_URL);
      await page.getByRole("link", { name: `Review proposal ${SEEDED}` }).click();
      const decision = page.getByRole("heading", { name: "Schedule it" }).locator("..");

      const startsAt = decision.getByLabel("Starts at");
      await expect(startsAt).toHaveValue(/T14:00$/);
      await expect(decision).toContainText(/The facilitator offered: .+ 14:00–18:00/);

      await attachArtifacts(test.info(), {
        name: "slot-availability-accept",
        region: decision,
        facts: { proposal: SEEDED, startsAt: await startsAt.inputValue() },
      });
    });
  });
});
