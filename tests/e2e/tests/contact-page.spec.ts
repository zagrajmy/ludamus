import { expect, test } from "./helpers/fixtures";

// .env.e2e sets no SUPPORT_EMAIL, so the page names the settings default.
const ADDRESS = "support@example.com";

const COPY = {
  en: {
    footerLink: "Contact",
    emergency: "In an emergency",
    users: "For users",
    report: "Report illegal content",
    authorities: "For authorities",
    languages: "You can write to us in Polish or English.",
    human: "A person, not a chatbot, reads and answers every message.",
  },
  pl: {
    footerLink: "Kontakt",
    emergency: "W nagłym wypadku",
    users: "Dla użytkowników",
    report: "Zgłoś nielegalne treści",
    authorities: "Dla organów publicznych",
    languages: "Możesz pisać do nas po polsku lub po angielsku.",
    human: "Każdą wiadomość czyta i odpowiada na nią człowiek, nie chatbot.",
  },
};

// DSA Art. 11 and 12: every page's footer reaches the points of contact, and
// the page names the mailbox, the languages it takes, where to report illegal
// content and 112, in each interface language.
test.describe("Contact page", () => {
  for (const [language, copy] of Object.entries(COPY)) {
    test(`the footer leads to both points of contact in ${language}`, async ({
      page,
    }, testInfo) => {
      await page
        .context()
        .addCookies([
          { name: "django_language", value: language, url: testInfo.project.use.baseURL! },
        ]);
      await page.goto("/");

      await page
        .getByRole("contentinfo")
        .getByRole("link", { name: copy.footerLink, exact: true })
        .click();

      await expect(page).toHaveURL(/\/contact\/$/);

      const emergency = page.getByRole("region", { name: copy.emergency });
      await expect(emergency.getByRole("link", { name: "112" })).toHaveAttribute("href", "tel:112");

      const users = page.getByRole("region", { name: copy.users });
      await expect(users.getByRole("link", { name: ADDRESS })).toHaveAttribute(
        "href",
        `mailto:${ADDRESS}`,
      );
      await expect(users).toContainText(copy.human);
      await expect(users).toContainText(copy.languages);

      const report = page.getByRole("region", { name: copy.report });
      await expect(report.getByRole("link", { name: ADDRESS })).toHaveAttribute(
        "href",
        `mailto:${ADDRESS}`,
      );

      const authorities = page.getByRole("region", { name: copy.authorities });
      await expect(authorities).toContainText("2022/2065");
      await expect(authorities.getByRole("link", { name: ADDRESS })).toHaveAttribute(
        "href",
        `mailto:${ADDRESS}`,
      );
      await expect(authorities).toContainText(copy.languages);

      // The document itself never scrolls (#app-scroll does), so a full-page
      // shot would stop at the viewport; the article is the whole page.
      await page.getByRole("article").screenshot({
        path: testInfo.outputPath(`contact-${language}.png`),
      });
    });
  }
});
