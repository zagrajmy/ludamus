import { expect, test } from "./helpers/fixtures";

test("an unverifiable MCP client gets a readable error instead of a redirect", async ({ page }) => {
  await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Username:").fill("admin");
  await page.getByLabel("Password:").fill("admin");
  await page.getByRole("button", { name: /Log in/i }).click();

  const query = new URLSearchParams({
    response_type: "code",
    client_id: "client-123",
    redirect_uri: "https://evil.example/callback",
    code_challenge: "x".repeat(43),
    code_challenge_method: "S256",
    resource: new URL("/mcp/", page.url()).href,
  });
  const response = await page.goto(`/mcp/oauth/authorize/?${query}`);

  expect(response?.status()).toBe(400);
  expect(page.url()).toContain("/mcp/oauth/authorize/");
  await expect(page.getByRole("heading", { name: "This client can't connect" })).toBeVisible();
  await expect(
    page.getByText("The client_id must be an https URL of a client metadata document."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /^Connect/ })).toHaveCount(0);
});
