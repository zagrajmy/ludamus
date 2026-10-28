import { gunzipSync } from "node:zlib";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// NOTE: rrweb's event type and incremental source numbers.
const INCREMENTAL_SNAPSHOT = 3;
const INPUT = 5;

type RecordedEvent = { type: number; data?: { source?: number; text?: string } };
type Capture = { event: string; properties: { $snapshot_data?: RecordedEvent[] } };

const captures = (body: Buffer): Capture[] => {
  const payload = JSON.parse((body[0] === 0x1f ? gunzipSync(body) : body).toString("utf8")) as
    | Capture
    | Capture[]
    | { batch: Capture[] };
  if (Array.isArray(payload)) return payload;
  return "batch" in payload ? payload.batch : [payload];
};

test.use({ consentSeed: null });

test.describe("Session replay masking", () => {
  test("records published Markdown as typed and masks a board listing", async ({
    page,
    context,
  }) => {
    const typed: string[] = [];
    let snapshots = 0;
    await page.addInitScript(() => {
      // NOTE: Both signals trigger PostHog's bot filter before the application's consent guard.
      Object.defineProperty(navigator, "webdriver", { get: () => false });
      Object.defineProperty(navigator, "userAgentData", { value: undefined });
    });
    await context.route(
      (url) =>
        url.pathname.startsWith("/array/phc_e2e_fake_key/") ||
        /^\/(?:flags|e|s)\/$/u.test(url.pathname),
      async (route) => {
        const body = route.request().postDataBuffer();
        if (new URL(route.request().url()).pathname === "/s/" && body) {
          for (const capture of captures(body)) {
            for (const event of capture.properties.$snapshot_data ?? []) {
              snapshots += 1;
              const text = event.data?.text;
              if (event.type === INCREMENTAL_SNAPSHOT && event.data?.source === INPUT && text) {
                typed.push(text);
              }
            }
          }
        }
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            featureFlags: {},
            sessionRecording: { endpoint: "/s/", sampleRate: 1 },
          }),
        });
      },
    );

    const published = "Bring **dice** and snacks";
    await page.goto("/encounters/create/");
    await page
      .getByRole("region", { name: "Cookie consent" })
      .getByRole("button", { name: "Cool" })
      .click();
    await expect.poll(() => snapshots, { timeout: 15_000 }).toBeGreaterThan(0);
    await page.getByLabel("Description").fill(published);
    await expect.poll(() => typed, { timeout: 15_000 }).toContain(published);

    const personal = "Ring me after nine";
    const seen = snapshots;
    await page.goto("/board/create/");
    await expect.poll(() => snapshots, { timeout: 15_000 }).toBeGreaterThan(seen);
    await page.getByLabel("Description").fill(personal);
    await expect.poll(() => typed, { timeout: 15_000 }).toContain("*".repeat(personal.length));
    expect(typed).not.toContain(personal);

    await attachArtifacts(test.info(), {
      name: "replay-input-events",
      region: page.getByLabel("Description"),
      facts: { typed },
    });
  });
});
