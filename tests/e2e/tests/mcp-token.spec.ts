import { expect, test } from "./helpers/fixtures";

test("manager generates an event-scoped organizer MCP token", async ({ page }) => {
  await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Username:").fill("e2e-manager");
  await page.getByLabel("Password:").fill("e2e-manager-123");
  await page.getByRole("button", { name: /Log in/i }).click();

  await page.goto("/panel/event/frostfire-con/settings/mcp/");

  await expect(page.getByRole("heading", { name: "MCP access", exact: true })).toBeVisible();
  await expect(
    page.getByRole("main").getByText("Frostfire Game Convention", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Generate token" }).click();

  await expect(page.getByText("Copy the token now — it is shown only once.")).toBeVisible();
  const token = await page.locator("pre code").first().innerText();
  expect(token).not.toBe("");

  const ping = await page.request.post("/mcp/organizer/", {
    data: { jsonrpc: "2.0", id: 1, method: "ping" },
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(ping.ok()).toBe(true);
  await expect(ping.json()).resolves.toEqual({ jsonrpc: "2.0", id: 1, result: {} });
});
