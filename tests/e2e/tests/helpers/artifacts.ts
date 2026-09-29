import { type Locator, type TestInfo } from "@playwright/test";
import { writeFile } from "node:fs/promises";

export async function attachArtifacts(
  testInfo: TestInfo,
  { name, region, facts }: { name: string; region: Locator; facts: object },
): Promise<void> {
  const screenshotPath = testInfo.outputPath(`${name}.png`);
  await region.screenshot({ path: screenshotPath });
  await testInfo.attach(`${name}.png`, { path: screenshotPath, contentType: "image/png" });
  const factsPath = testInfo.outputPath(`${name}.json`);
  await writeFile(factsPath, `${JSON.stringify(facts, null, 2)}\n`);
  await testInfo.attach(`${name}.json`, { path: factsPath, contentType: "application/json" });
}
