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

// Press the rail's own hour links rather than a coordinate derived from the
// viewport. The rail occupies x 344-382 of a 402pt screen, so the old
// `viewport.width - 4` landed in the gutter beside it: no callout appeared
// because nothing was pressed. Their labels ("Jump to <day> <time>") are the
// aria-labels the rail already carries for screen readers.
const railHourTargets = (snapshot: CaptureSnapshotResult): RailHour[] => {
  const hours = snapshot.nodes.flatMap((node) => {
    const label = node.label ?? "";
    // "Jump to time" is the <nav> itself, whose rect spans the whole rail.
    if (!label.startsWith("Jump to ") || label === "Jump to time") return [];
    return node.rect ? [{ label, rect: node.rect }] : [];
  });
  if (hours.length === 0) {
    throw new Error("The schedule rail exposed no hour links to press.");
  }
  // A handful spread down the rail: the callout is a per-element behaviour, so
  // one hour passing says little about the rest.
  return [0.1, 0.35, 0.6, 0.85]
    .map((fraction) => hours[Math.floor(fraction * hours.length)])
    .filter((hour): hour is RailHour => hour !== undefined);
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
