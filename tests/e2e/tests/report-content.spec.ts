import fs from "node:fs";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { mailHeaders } from "./helpers/mail";

const mailDir = path.join(path.resolve(__dirname, ".."), ".e2e-mail");
const mailFiles = (): string[] => (fs.existsSync(mailDir) ? fs.readdirSync(mailDir) : []);
const readMailSince = (before: Set<string>): string[] =>
  mailFiles()
    .filter((file) => !before.has(file))
    .flatMap((file) => fs.readFileSync(path.join(mailDir, file), "utf8").split("-".repeat(79)));

const EVENT_URL = "/event/autumn-open/";

test.beforeEach(async ({ page }, testInfo) => {
  const octet = (testInfo.workerIndex * 7 + testInfo.retry + Date.now()) % 250;
  await page.setExtraHTTPHeaders({ "CF-Connecting-IP": `198.51.100.${octet + 1}` });
});

test("anyone reports an event and gets a case reference by mail", async ({ page }, testInfo) => {
  const reporter = `reporter-${Date.now().toString(36)}-${testInfo.workerIndex}@example.com`;
  const mailBefore = new Set(mailFiles());

  await page.goto(EVENT_URL);
  await page.getByRole("link", { name: "Report this event" }).click();

  await expect(page.getByRole("heading", { name: "Report illegal content" })).toBeVisible();
  await expect(page.getByLabel("Address of the content")).toHaveValue(
    new RegExp(`${EVENT_URL}$`, "u"),
  );
  await page.getByLabel("What is wrong with it").selectOption({ label: "Fraud, scam or phishing" });
  await page
    .getByLabel("Why it is illegal")
    .fill("The description asks for card numbers to hold a seat.");
  await page.getByLabel("Your name").fill("Ola Tester");
  await page.getByLabel("Your email").fill(reporter);
  await page.getByRole("checkbox", { name: /good faith/u }).check();
  await attachArtifacts(testInfo, {
    name: "report-content-form",
    region: page.getByRole("main"),
    facts: { reporter },
  });
  await page.getByRole("button", { name: "Send report" }).click();

  await expect(page.getByRole("heading", { name: "Report sent" })).toBeVisible();
  const reference = await page.getByRole("main").locator("strong").innerText();
  expect(reference).toMatch(/^Z-\d+$/u);

  const subjects = async () =>
    readMailSince(mailBefore)
      .map(mailHeaders)
      .filter((headers) => headers.subject?.includes(`[${reference}]`))
      .map((headers) => `${headers.to} ${headers.subject}`);
  await expect
    .poll(subjects, { timeout: 10_000 })
    .toEqual(
      expect.arrayContaining([
        `staff@zagrajmy.net [${reference}] Nowe zgłoszenie nielegalnej treści: Oszustwo, wyłudzenie lub phishing`,
        `${reporter} [${reference}] We received your report`,
      ]),
    );
  await attachArtifacts(testInfo, {
    name: "report-content-sent",
    region: page.getByRole("main"),
    facts: { reference, mail: await subjects() },
  });
});

test("a report needs a name and email unless it is of child sexual abuse material", async ({
  page,
}, testInfo) => {
  await page.goto("/report/?url=https%3A%2F%2Fzagrajmy.net%2Fevent%2Fx%2F");

  await page.getByLabel("What is wrong with it").selectOption({ label: "Other illegal content" });
  await page.getByLabel("Why it is illegal").fill("It names a private address.");
  await page.getByRole("checkbox", { name: /good faith/u }).check();
  await page.getByRole("button", { name: "Send report" }).click();

  await expect(page.getByText("Enter your name.")).toBeVisible();
  await expect(page.getByText("Enter your email.")).toBeVisible();
  await expect(page.getByLabel("Why it is illegal")).toHaveValue("It names a private address.");
  await attachArtifacts(testInfo, {
    name: "report-content-contact-required",
    region: page.getByRole("main"),
    facts: { errors: ["Enter your name.", "Enter your email."] },
  });

  await page
    .getByLabel("What is wrong with it")
    .selectOption({ label: "Child sexual abuse material" });
  await page.getByRole("checkbox", { name: /good faith/u }).check();
  await page.getByRole("button", { name: "Send report" }).click();

  await expect(page.getByRole("heading", { name: "Report sent" })).toBeVisible();
});

test("the footer offers the form for the page being read", async ({ page }) => {
  await page.goto("/about/");

  const link = page.getByRole("contentinfo").getByRole("link", { name: "Report illegal content" });
  await link.click();

  await expect(page.getByLabel("Address of the content")).toHaveValue(/\/about\/$/u);
});
