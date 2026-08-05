import type { CaptureSnapshotResult } from "agent-device";

import { afterAll, beforeAll, expect, test } from "bun:test";

import type { Rect } from "./harness";

import { baseUrl, createIosHarness, hookTimeoutMs, sessionName } from "./harness";

const env = process.env;
const session = sessionName("scrubber");
const eventPath = env.EVENT_PATH ?? "/event/kapitularz-2025-anonymized/";
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
  viewportOf,
  close,
  wait,
  openUrl,
  prepareDevice,
  assertPageReady,
} = createIosHarness(session);

// The rail's own hour links are anchors (#slot-YYYYMMDD-HH), so Safari can land
// mid-schedule on load. Reaching the same place with scroll gestures cost up to
// 14 of them, and a single gesture on this page — 110 sessions, ~400 KB — runs
// past the runner's 180s per-command ceiling, which is what made this spec
// flaky. The ids are derived from the seed's start date, so read one from the
// markup rather than hardcoding it.
const railSlotAnchor = (html: string): string => {
  const slots = [...html.matchAll(/data-rail-hour="([\w-]+)"/g)].map((match) => match[1]);
  if (slots.length === 0) throw new Error("The schedule rail rendered no hour anchors.");
  // A few hours in, so sessions fill the viewport above and below the rail.
  return slots[Math.min(3, slots.length - 1)] as string;
};

type RailHour = { label: string; rect: Rect };

// The rail's hour markers are the only things on this page whose accessible
// name ends in a time — 31 of 260 names, all of them rail hours. Matching that
// rather than the "Jump to " prefix keeps the spec working whichever language
// the page renders: the prefix is translated ("Przejdź do ..."), and the e2e
// run only escapes it today because it never compiles the catalogue. It also
// drops the <nav>'s own label, which carries no time.
const RAIL_HOUR_LABEL = /\d{1,2}:\d{2}$/;

// Press those markers rather than a coordinate derived from the viewport: the
// rail occupies x 344-382 of a 402pt screen, so the old `viewport.width - 4`
// landed in the gutter beside it and pressed nothing at all.
const railHourTargets = (snapshot: CaptureSnapshotResult): RailHour[] => {
  const hours = snapshot.nodes.flatMap((node) => {
    const label = node.label ?? "";
    if (!RAIL_HOUR_LABEL.test(label) || !node.rect) return [];
    return [{ label, rect: node.rect }];
  });
  if (hours.length === 0) {
    throw new Error("The schedule rail exposed no hour markers to press.");
  }
  // A handful spread down the rail: the callout is a per-element behaviour, so
  // one hour passing says little about the rest. Dedup keeps a short rail from
  // pressing the same marker four times.
  return [...new Set([0.1, 0.35, 0.6, 0.85].map((f) => Math.floor(f * hours.length)))].flatMap(
    (index) => {
      const hour = hours[index];
      return hour ? [hour] : [];
    },
  );
};

const scheduleOnScreen = (snapshot: CaptureSnapshotResult): boolean => {
  const viewportHeight = viewportOf(snapshot).height;
  return snapshot.nodes.some(
    (node) =>
      (node.label ?? "").startsWith("Open details for") &&
      node.rect !== undefined &&
      node.rect.y > 80 &&
      node.rect.y < viewportHeight - 120,
  );
};

// Polled, not slept: Safari applies the fragment scroll somewhere after load,
// and a fixed wait is either too short on a slow runner or wasted on a fast
// one. Without the check the long-press would land on empty page and the spec
// would pass by finding no callout, which is not the same as the callout being
// suppressed.
const waitForSchedule = async (timeoutMs: number): Promise<CaptureSnapshotResult> => {
  const deadline = Date.now() + timeoutMs;
  let snapshot = await takeSnapshot();
  while (!scheduleOnScreen(snapshot) && Date.now() < deadline) {
    await wait(500);
    snapshot = await takeSnapshot();
  }
  if (!scheduleOnScreen(snapshot)) {
    throw new Error("The slot anchor did not bring the schedule into the viewport.");
  }
  return snapshot;
};

let surfacedCalloutSignals: string[] = [];

beforeAll(async () => {
  const html = await assertPageReady(eventUrl, "schedule-rail");
  const udid = await prepareDevice();

  const scheduleUrl = new URL(eventUrl);
  scheduleUrl.hash = `slot-${railSlotAnchor(html)}`;
  console.log(`Opening Safari at ${scheduleUrl.toString()}...`);
  await openUrl(scheduleUrl.toString(), udid);

  // The settled snapshot serves both the guard and the rail geometry below.
  const snapshot = await waitForSchedule(30_000);

  for (const hour of railHourTargets(snapshot)) {
    const x = hour.rect.x + hour.rect.width / 2;
    const y = hour.rect.y + hour.rect.height / 2;
    console.log(
      `Long-pressing ${JSON.stringify(hour.label)} at x=${Math.round(x)} y=${Math.round(y)}...`,
    );
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
