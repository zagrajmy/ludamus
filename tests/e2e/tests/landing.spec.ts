import { expect, test } from "./helpers/fixtures";

test.describe("Landing", () => {
  test("greets organizers on the root domain and switches to the player view", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveTitle("Zagrajmy • conventions and events");
    await expect(page.getByRole("heading", { name: /Event organization/ })).toBeVisible();

    await page.getByText("For players", { exact: true }).filter({ visible: true }).click();

    await expect(page).toHaveURL(/#gracze$/);
    await expect(page.getByRole("heading", { name: /Your table, your game/ })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Enrollment and the programme in one place" }),
    ).toBeVisible();

    await page.getByRole("link", { name: "Browse events" }).first().click();
    await expect(page).toHaveURL(/#g-conventions-heading$/);
    await expect(
      page.getByRole("heading", { name: "Enrollment and the programme in one place" }),
    ).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { name: /Your table, your game/ })).toBeVisible();
  });

  test("browses the player's conventions without JavaScript", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    try {
      const page = await context.newPage();
      await page.goto("/");
      await page.getByText("For players", { exact: true }).filter({ visible: true }).click();
      await page.getByRole("link", { name: "Browse events" }).first().click();

      await expect(page).toHaveURL(/#g-conventions-heading$/);
      await expect(
        page.getByRole("heading", { name: "Enrollment and the programme in one place" }),
      ).toBeVisible();
    } finally {
      await context.close();
    }
  });

  test("shows organizers' testimonials only in the organizer view", async ({ page }) => {
    await page.goto("/");

    const mamert = page.getByRole("figure", { name: "Mamert · Bachanalia Fantastyczne" });
    await expect(mamert).toContainText("Widzę jaki potencjał i pomoc jest w takiej aplikacji.");
    await expect(mamert.locator("img[src*='bachanalia-mark']")).toBeVisible();
    const avatar = mamert.locator("img[src*='mamert']");
    await expect(avatar).toBeVisible();
    await avatar.scrollIntoViewIfNeeded();
    await expect
      .poll(() => avatar.evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(0);

    for (const name of ["Hory-portier", "Gosia", "Sowa"]) {
      const quote = page.getByRole("figure", { name: `${name} · Kapitularz` });
      await expect(quote).toBeVisible();
      await expect(quote.locator("img")).toHaveAttribute("src", /kapitularz-mark.*\.svg/);
    }
    await expect(page.getByRole("figure", { name: "Sowa · Kapitularz" })).toContainText(
      "ponad 900 godzin programu",
    );
    await expect(
      page.getByRole("heading", { name: "Four questions you probably have in mind" }),
    ).toHaveCSS("text-wrap", "balance");

    await page.getByText("For players", { exact: true }).filter({ visible: true }).click();
    await expect(mamert).toBeHidden();
  });

  test("#gracze deep link opens the player view directly", async ({ page }) => {
    await page.goto("/#gracze");

    await expect(page.getByRole("heading", { name: /Your table, your game/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Event organization/ })).toBeHidden();
  });

  test("keeps the plain feed on a sphere domain, announcements first", async ({ page }) => {
    await page.goto("http://foreign.localhost:8000/");

    await expect(page.getByRole("heading", { name: "Upcoming" })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Event organization/ })).toBeHidden();

    // A sphere's announcements sit above its programme. The root sphere runs
    // no programme and shows none.
    await expect(page.getByRole("heading", { name: "Organization announcements" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Doors open at 9:00" })).toBeVisible();

    // The feed's cards reach their event — coverage that lived in
    // index.spec.ts, against the root domain, which is the pitch now. Located
    // by href: the sphere and its event share a name, so the navbar's brand
    // link answers to the same accessible name.
    await page.locator('#events a[href="/event/foreign-programme/"]').first().click();
    await expect(page).toHaveURL(/\/event\/foreign-programme\//);
  });
});
