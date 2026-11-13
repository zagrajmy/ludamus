import { createHmac } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { mailHeaders } from "./helpers/mail";

const e2eDir = path.join(__dirname, "..");
const mailDir = path.join(e2eDir, ".e2e-mail");
const superuserState = path.join(e2eDir, ".auth-state-superuser.json");
// NOTE: STAFF_MAIL_WEBHOOK_SECRET in .env.e2e.
const SECRET = "e2e-posta-secret";

const mailFiles = (): string[] => (fs.existsSync(mailDir) ? fs.readdirSync(mailDir) : []);
const readMailSince = (before: Set<string>): string[] =>
  mailFiles()
    .filter((file) => !before.has(file))
    .flatMap((file) => fs.readFileSync(path.join(mailDir, file), "utf8").split("-".repeat(79)));

function staffMail({ from, subject }: { from: string; subject: string }): string {
  return [
    `From: Ola W. <${from}>`,
    "To: staff@zagrajmy.net",
    `Subject: ${subject}`,
    `Message-ID: <${crypto.randomUUID()}@mail.example>`,
    "Content-Type: text/plain; charset=utf-8",
    "",
    "Someone keeps asking my brother for his phone number.",
    "",
  ].join("\r\n");
}

test.describe("Staff cases inbox", () => {
  test.use({ storageState: superuserState });

  test("staff answer an email by email and close its case", async ({ page }) => {
    const stamp = Date.now();
    const subject = `Question ${stamp}`;
    const from = `ola-${stamp}@example.com`;
    const body = staffMail({ from, subject });
    const timestamp = Math.floor(Date.now() / 1_000);
    const signature = createHmac("sha256", SECRET)
      .update(`${timestamp}.`)
      .update(body)
      .digest("hex");
    const filed = await page.request.post("/hooks/staff-mail", {
      data: body,
      headers: {
        "Content-Type": "message/rfc822",
        "X-Posta-Signature": `t=${timestamp},v1=${signature}`,
      },
    });
    expect(filed.status()).toBe(200);
    const { case: reference } = (await filed.json()) as { case: string; outcome: string };

    await page.goto("/staff/cases/");
    await expect(page.getByRole("heading", { name: "Cases", level: 1 })).toBeVisible();
    await page.getByRole("link", { name: new RegExp(subject) }).click();
    await expect(page.getByRole("heading", { name: subject, level: 2 })).toBeVisible();
    await expect(page.getByText("Someone keeps asking my brother")).toBeVisible();

    const mailBefore = new Set(mailFiles());
    await page.getByLabel("Reply as the staff address").fill("Thank you, we are on it.");
    await page.getByRole("button", { name: "Send by email" }).click();
    await expect(page.getByText("Reply sent.")).toBeVisible();
    await expect
      .poll(
        () =>
          readMailSince(mailBefore)
            .map(mailHeaders)
            .filter((headers) => headers.to === from && headers.subject?.includes(`[${reference}]`))
            .length,
        { timeout: 10_000 },
      )
      .toBe(1);
    await attachArtifacts(test.info(), {
      name: "staff-case-email",
      region: page.getByRole("main"),
      facts: { reference, subject, from },
    });

    await page.getByRole("button", { name: "Close case" }).click();
    await expect(page.getByText("Case closed.")).toBeVisible();
    await expect(page.getByRole("tab", { name: /Closed/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("staff decide a notice and its reporter hears the outcome", async ({ page }, testInfo) => {
    const reporter = `notice-${Date.now().toString(36)}-${testInfo.workerIndex}@example.com`;
    await page.setExtraHTTPHeaders({
      "CF-Connecting-IP": `203.0.113.${(Date.now() % 250) + 1}`,
    });
    await page.goto("/report/");
    await page.getByLabel("Address of the content").fill("https://zagrajmy.net/event/autumn-open/");
    await page
      .getByLabel("What is wrong with it")
      .selectOption({ label: "Fraud, scam or phishing" });
    await page.getByLabel("Why it is illegal").fill("The description asks for card numbers.");
    await page.getByLabel("Your name").fill("Ola Tester");
    await page.getByLabel("Your email").fill(reporter);
    await page.getByRole("checkbox", { name: /good faith/u }).check();
    await page.getByRole("button", { name: "Send report" }).click();
    const reference = await page.getByRole("main").locator("strong").innerText();

    await page.goto("/staff/cases/");
    await page
      .getByRole("link", { name: /The description asks for card numbers/ })
      .first()
      .click();
    await expect(page.getByRole("article").getByText(reference, { exact: true })).toBeVisible();

    await page.getByRole("radio", { name: "No action" }).check();
    await expect(
      page.getByText("None: with no action taken, only the reporters hear the outcome."),
    ).toBeVisible();
    await page.getByRole("radio", { name: "Warning" }).check();
    await page.getByLabel("Decision text").fill("The description was changed by its organizer.");
    await expect(page.getByText(/Zagrajmy staff decided on a warning/u)).toBeVisible();

    const mailBefore = new Set(mailFiles());
    await page.getByRole("button", { name: "Confirm decision" }).click();
    await expect(page.getByText("Decision recorded. The case is closed.")).toBeVisible();
    await expect
      .poll(
        () =>
          readMailSince(mailBefore)
            .map(mailHeaders)
            .filter(
              (headers) => headers.to === reporter && headers.subject?.includes(`[${reference}]`),
            ).length,
        { timeout: 10_000 },
      )
      .toBe(1);
    await attachArtifacts(test.info(), {
      name: "staff-case-decided",
      region: page.getByRole("main"),
      facts: { reference, decision: "warning", reporter },
    });
  });
});

test("the inbox is not there for anyone off staff", async ({ page }) => {
  const response = await page.goto("/staff/cases/");

  expect(response?.status()).toBe(404);
});
