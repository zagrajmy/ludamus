import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// DSA notice and action, end to end: a signed-out visitor reports a session
// as illegal and gets a receipt, a root-sphere manager decides the report
// from the queue, and the decision reaches the reporter by email.
// bootstrap_data.py seeds "Cursed Scroll Swap" on an event of its own. Which
// content a sphere lets people report, the rate limit, the CSAM exception and
// foreign ids are covered by tests/integration/web/report/test_report.py and
// tests/integration/web/multiverse/test_reports.py.

const superuserState = path.join(__dirname, "..", ".auth-state-superuser.json");

test("a signed-out report reaches the queue and its decision reaches the reporter", async ({
  page,
  browser,
}, testInfo) => {
  const token = `${Date.now().toString(36)}${testInfo.workerIndex}`;
  const reporterEmail = `reporter-${token}@example.com`;
  const decision = `We removed the description (${token}).`;

  await page.goto("/event/content-report/");
  await page.getByRole("link", { name: "Open details for Cursed Scroll Swap" }).press("Enter");
  const modal = page.getByRole("dialog", { name: "Cursed Scroll Swap" });
  await expect(modal.getByRole("link", { name: "Report host" })).toBeVisible();
  await modal.getByRole("link", { name: "Report session" }).click();

  await expect(page.getByRole("heading", { name: "Report illegal content" })).toBeVisible();
  await expect(page.getByText("You are reporting the session “Cursed Scroll Swap”.")).toBeVisible();
  await page.getByRole("radio", { name: "Illegal hate speech" }).check();
  await page
    .getByLabel("Explain what is illegal and why")
    .fill("The description calls for violence against a group.");
  await page.getByLabel("Your name").fill("Rita Reporter");
  await page.getByLabel("Your email").fill(reporterEmail);
  await page.getByRole("checkbox", { name: /I believe in good faith/ }).check();
  await attachArtifacts(testInfo, {
    name: "content-report-form",
    region: page.locator("main"),
    facts: { content: "Cursed Scroll Swap", reason: "hate_speech", reporterEmail },
  });
  await page.getByRole("button", { name: "Send report" }).click();

  await expect(page).toHaveURL(/\/event\/content-report\/\?session=\d+$/);
  await expect(page.getByText("Report sent. We emailed you a receipt.")).toBeVisible();

  const managerContext = await browser.newContext({ storageState: undefined });
  const manager = await managerContext.newPage();
  await signInAsManager(manager);
  await manager.goto("/multiverse/panel/reports/");
  await manager
    .getByRole("row")
    .filter({ hasText: "Cursed Scroll Swap" })
    .last()
    .getByRole("link", { name: "Cursed Scroll Swap" })
    .click();
  await expect(manager.getByRole("link", { name: reporterEmail })).toBeVisible();
  const reportUrl = manager.url();
  await manager.getByRole("textbox", { name: /Your decision/ }).fill(decision);
  await manager.getByRole("button", { name: "Send decision" }).click();
  await expect(
    manager.getByText("Report decided. We emailed the reporter your decision."),
  ).toBeVisible();

  await manager.goto(reportUrl);
  const decisionCard = manager.getByRole("region", { name: "Decision" });
  await expect(decisionCard.getByText(decision)).toBeVisible();
  await expect(decisionCard.getByText("Decided by E2E Manager.")).toBeVisible();
  await expect(manager.getByRole("button", { name: "Send decision" })).toHaveCount(0);
  await attachArtifacts(testInfo, {
    name: "content-report-decided",
    region: manager.locator("main"),
    facts: { reporterEmail, decision, reportUrl },
  });
  await managerContext.close();

  const inboxContext = await browser.newContext({ storageState: superuserState });
  const inbox = await inboxContext.newPage();
  await inbox.goto(`/dev/emails/?q=${encodeURIComponent(reporterEmail)}`);
  const list = inbox.getByRole("navigation", { name: "Emails" });
  await expect(list.getByRole("link", { name: /Decision on your report #\d+/ })).toBeVisible();
  await expect(list.getByRole("link", { name: /We received your report #\d+/ })).toBeVisible();
  // The newest mail opens first: the decision, quoting what the manager wrote.
  const reader = inbox.getByRole("article");
  await expect(reader.getByRole("heading", { name: /Decision on your report #\d+/ })).toBeVisible();
  await expect(reader.getByText(`Our decision: ${decision}`).first()).toBeVisible();
  await inboxContext.close();
});
