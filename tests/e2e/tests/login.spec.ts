import { expect, test } from "./helpers/fixtures";

// Signs in through scripts/workos_simulator.py, which .env.e2e's
// WORKOS_BASE_URL points the WorkOS SDK at.
test("a new person signs up through AuthKit and signs out again", async ({ page }, testInfo) => {
  const email = `login-${testInfo.project.name}-${Date.now()}@example.com`;

  await page.goto("/");
  await page.getByRole("link", { name: "Log in" }).first().click();

  await expect(page.getByRole("heading", { name: /WorkOS simulator/ })).toBeVisible();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Name").fill("Nowa Osoba");
  await page.getByRole("button", { name: "Sign in" }).click();

  // The name came through AuthKit, so no onboarding detour: straight home.
  await expect(page).toHaveURL(/localhost:8000\/$/);
  await expect(page.getByRole("heading", { name: "Your dashboard" })).toBeVisible();
  const menu = page.getByRole("button", { name: /Account menu/ });
  await expect(menu).toContainText("NO");
  await page.screenshot({ path: testInfo.outputPath("signed-in.png") });

  await menu.focus();
  await page.keyboard.press("Enter");
  const logout = page.getByRole("link", { name: /Log out/ });
  await expect(logout).toBeVisible();
  await logout.press("Enter");

  await expect(page).toHaveURL(/localhost:8000\/$/);
  await expect(page.getByRole("button", { name: /Account menu/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Log in" }).first()).toBeVisible();
});
