import { type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const managerState = path.join(__dirname, "..", "..", ".auth-state-manager.json");

// The seed (scripts/bootstrap_data.py) writes the manager's session cookie;
// loading it skips a page load and form round-trip through /admin/login/.
export const signInAsManager = async (page: Page): Promise<void> => {
  const { cookies } = JSON.parse(fs.readFileSync(managerState, "utf8"));
  await page.context().addCookies(cookies);
};
