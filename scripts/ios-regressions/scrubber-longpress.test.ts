import { afterAll, beforeAll, expect, test } from "bun:test";

import type { Rect } from "./harness";

import {
  baseUrl,
  createIosHarness,
  FALLBACK_VIEWPORT,
  hookTimeoutMs,
  sessionName,
} from "./harness";

const env = process.env;
const session = sessionName("scrubber");
const eventPath = env.EVENT_PATH ?? "/chronology/event/kapitularz-2025-anonymized/";
const eventUrl = new URL(eventPath, baseUrl);

const calloutSignals = [
  "Hide preview",
  "Open in New Tab",
  "Open in Tab Group",
  "Add to Reading List",
  "Download Linked File",
];

const {
  client,
  deviceOptions,
  takeSnapshot,
  snapshotLabels,
  close,
  wait,
  openUrl,
  prepareDevice,
  assertPageReady,
} = await createIosHarness(session);

const viewportRect = async (): Promise<Rect> =>
  (await takeSnapshot()).nodes[0]?.rect ?? FALLBACK_VIEWPORT;

const scrollScheduleIntoView = async (): Promise<void> => {
  for (let attempt = 0; attempt < 14; attempt += 1) {
    const snapshot = await takeSnapshot();
    const viewportHeight = snapshot.nodes[0]?.rect?.height ?? FALLBACK_VIEWPORT.height;
    const sessionOnScreen = snapshot.nodes.some(
      (node) =>
        (node.label ?? "").startsWith("Open details for") &&
        node.rect !== undefined &&
        node.rect.y > 80 &&
        node.rect.y < viewportHeight - 120,
    );
    if (sessionOnScreen) return;
    await client.interactions.scroll({ ...deviceOptions, direction: "down", pixels: 450 });
    await wait(300);
  }
};

let surfacedCalloutSignals: string[] = [];

beforeAll(async () => {
  await assertPageReady(eventUrl, "schedule-rail");
  const udid = await prepareDevice();

  console.log(`Opening Safari at ${eventUrl.toString()}...`);
  await openUrl(eventUrl.toString(), udid);
  await wait(3000);

  await scrollScheduleIntoView();

  const viewport = await viewportRect();
  const x = viewport.x + viewport.width - 4;
  const fractions = [0.3, 0.45, 0.6, 0.75];
  for (const fraction of fractions) {
    const y = viewport.y + viewport.height * fraction;
    console.log(`Long-pressing the rail at x=${Math.round(x)} y=${Math.round(y)}...`);
    await client.interactions.longPress({ ...deviceOptions, x, y, durationMs: 800 });
    await wait(900);
    const labels = await snapshotLabels();
    const surfaced = calloutSignals.filter((signal) =>
      labels.some((label) => label.includes(signal)),
    );
    if (surfaced.length > 0) {
      surfacedCalloutSignals = surfaced;
      break;
    }
  }
}, hookTimeoutMs);

afterAll(close, 30_000);

test("long-pressing the hour rail does not open the iOS link callout", () => {
  expect(surfacedCalloutSignals).toEqual([]);
});
