import fs from "node:fs";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// The captured-mail inbox at /dev/emails/ (staff only). The e2e server sends
// mail to files (EMAIL_URL=filemail://, .env.e2e), the same directory other
// specs' real flows write to. Each test seeds its own .log files with a unique
// recipient and works inside `?q=<that recipient>`, so neither side sees the
// other's mail.

const e2eDir = path.resolve(__dirname, "..");
const mailDir = path.join(e2eDir, ".e2e-mail");
const SEPARATOR = "-".repeat(79);

test.use({ storageState: path.join(e2eDir, ".auth-state-superuser.json") });

type Mail = { to: string; subject: string; body: string };

const written: string[] = [];

const rfc2822 = (date: Date): string => date.toUTCString().replace("GMT", "+0000");

const raw = ({ to, subject, body }: Mail): string =>
  [
    'Content-Type: text/plain; charset="utf-8"',
    "MIME-Version: 1.0",
    `Subject: ${subject}`,
    "From: Zagrajmy <noreply@zagrajmy.net>",
    `To: ${to}`,
    `Date: ${rfc2822(new Date())}`,
    "",
    body,
    "",
  ].join("\n");

// One file per "connection", as Django's backend writes them. Names sort by
// the sequence number, so a later write is the newer mail.
const deliver = (token: string, sequence: number, mails: Mail[]): void => {
  fs.mkdirSync(mailDir, { recursive: true });
  const file = path.join(mailDir, `20990101-00000${sequence}-${token}.log`);
  fs.writeFileSync(file, mails.map((mail) => `${raw(mail)}\n${SEPARATOR}\n`).join(""));
  written.push(file);
};

test.afterEach(() => {
  for (const file of written.splice(0)) fs.rmSync(file, { force: true });
});

const uniqueToken = (): string => `inbox${Date.now().toString(36)}${test.info().workerIndex}`;

test("the newest email opens with its link one click away", async ({ page }, testInfo) => {
  const token = uniqueToken();
  const confirmUrl = `https://test.zagrajmy.net/crowd/email/link/${token}`;
  deliver(token, 1, [
    {
      to: `old-${token}@example.com`,
      subject: "Your email address is changing",
      body: "Someone asked to move your account to a new address.",
    },
  ]);
  deliver(token, 2, [
    {
      to: `new-${token}@example.com`,
      subject: "Confirm your email address",
      body: `Use the link below to confirm this address.\n\n${confirmUrl}.`,
    },
  ]);

  await page.goto(`/dev/emails/?q=${token}`);

  const list = page.getByRole("navigation", { name: "Emails" });
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await expect(list.getByRole("listitem").first().getByRole("link")).toHaveAttribute(
    "aria-current",
    "true",
  );

  const reader = page.getByRole("article");
  await expect(reader.getByRole("heading", { name: "Confirm your email address" })).toBeVisible();
  // Trailing sentence punctuation is not part of the link.
  const open = reader.getByRole("link", { name: "Open link" });
  await expect(open).toHaveAttribute("href", confirmUrl);
  await expect(open).toHaveAttribute("target", "_blank");

  await list.getByRole("link", { name: /Your email address is changing/ }).click();
  await expect(page).toHaveURL(/[?&]m=/);
  await expect(
    reader.getByRole("heading", { name: "Your email address is changing" }),
  ).toBeVisible();
  await expect(reader.getByRole("link", { name: "Open link" })).toHaveCount(0);

  await reader.getByRole("link", { name: "Only this address" }).click();
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await expect(page.getByText(`1 match for “old-${token}@example.com”`)).toBeVisible();

  await attachArtifacts(testInfo, {
    name: "staging-inbox-reader",
    region: page.locator("main"),
    facts: { token, confirmUrl, listed: await list.getByRole("listitem").count() },
  });
});

test("new mail appears on its own and opens when following the newest", async ({ page }) => {
  const token = uniqueToken();
  deliver(token, 1, [{ to: `p-${token}@example.com`, subject: "First", body: "One." }]);

  await page.goto(`/dev/emails/?q=${token}`);
  await expect(page.getByText("Live: new emails show up on their own")).toBeVisible();
  const reader = page.getByRole("article");
  await expect(reader.getByRole("heading", { name: "First" })).toBeVisible();

  deliver(token, 2, [{ to: `p-${token}@example.com`, subject: "Second", body: "Two." }]);

  await expect(reader.getByRole("heading", { name: "Second" })).toBeVisible();
  const list = page.getByRole("navigation", { name: "Emails" });
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await expect(page.getByRole("status").filter({ hasText: "A new email arrived." })).toBeAttached();
});

test("new mail joins the list without replacing the email being read", async ({ page }) => {
  const token = uniqueToken();
  deliver(token, 1, [{ to: `p-${token}@example.com`, subject: "Picked", body: "Stay." }]);

  await page.goto(`/dev/emails/?q=${token}`);
  const list = page.getByRole("navigation", { name: "Emails" });
  await list.getByRole("link", { name: /Picked/ }).click();
  await expect(page).toHaveURL(/[?&]m=/);

  deliver(token, 2, [{ to: `p-${token}@example.com`, subject: "Later", body: "New." }]);

  await expect(list.getByRole("link", { name: /Later/ })).toBeVisible();
  await expect(list.getByRole("link", { name: /Picked/ })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("article").getByRole("heading", { name: "Picked" })).toBeVisible();
});

test("a link to a cleared email says so instead of failing", async ({ page }) => {
  const token = uniqueToken();
  deliver(token, 1, [{ to: `p-${token}@example.com`, subject: "Kept", body: "Here." }]);

  await page.goto(`/dev/emails/?q=${token}&m=19990101-000000-1-0`);

  await expect(page.getByRole("heading", { name: "This email is gone" })).toBeVisible();
});

test("a search with no matches explains what it searched", async ({ page }) => {
  const token = uniqueToken();
  deliver(token, 1, [{ to: `p-${token}@example.com`, subject: "Kept", body: "Here." }]);

  await page.goto(`/dev/emails/?q=${token}-nobody`);

  await expect(page.getByText("No email matches")).toBeVisible();
  await page.getByRole("link", { name: "Clear search" }).click();
  await expect(page).toHaveURL(/\/dev\/emails\/$/);
});
