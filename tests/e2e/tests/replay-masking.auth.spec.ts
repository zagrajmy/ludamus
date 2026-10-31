import { gunzipSync } from "node:zlib";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// NOTE: rrweb's event type and incremental source numbers.
const INCREMENTAL_SNAPSHOT = 3;
const META = 4;
const INPUT = 5;

type RecordedEvent = { type: number; data?: { source?: number; text?: string; href?: string } };
type Capture = { event: string; properties: { $snapshot_data?: RecordedEvent[] } };

const GZIP = "\u001f\u008b";

// NOTE: posthog gzips full snapshots and DOM mutations into latin1 strings
// inside the payload, so text that leaks there is invisible until inflated.
const inflate = (value: unknown): unknown => {
  if (typeof value === "string" && value.startsWith(GZIP)) {
    return inflate(JSON.parse(gunzipSync(Buffer.from(value, "latin1")).toString("utf8")));
  }
  if (Array.isArray(value)) return value.map(inflate);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, inner]) => [key, inflate(inner)]));
  }
  return value;
};

const captures = (body: Buffer): Capture[] => {
  const payload = inflate(
    JSON.parse((body[0] === 0x1f ? gunzipSync(body) : body).toString("utf8")),
  ) as Capture | Capture[] | { batch: Capture[] };
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
    const pages: string[] = [];
    let recording = "";
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
            recording += JSON.stringify(capture);
            for (const event of capture.properties.$snapshot_data ?? []) {
              const { href, source, text } = event.data ?? {};
              if (event.type === META && href) pages.push(new URL(href).pathname);
              if (event.type === INCREMENTAL_SNAPSHOT && source === INPUT && text) {
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
    await expect.poll(() => pages, { timeout: 15_000 }).toContain("/encounters/create/");
    await page.getByLabel("Description").fill(published);
    await expect.poll(() => typed, { timeout: 15_000 }).toContain(published);

    const personal = "Ring me after nine";
    await page.goto("/board/create/");
    await expect.poll(() => pages, { timeout: 15_000 }).toContain("/board/create/");
    await page.getByLabel("Description").fill(personal);
    await expect.poll(() => typed, { timeout: 15_000 }).toContain("*".repeat(personal.length));
    expect(recording.includes(published), "published text in the recording").toBe(true);
    expect(recording.includes(personal), "board text in the recording").toBe(false);

    await attachArtifacts(test.info(), {
      name: "replay-input-events",
      region: page.getByLabel("Description"),
      facts: { typed },
    });
  });
});
