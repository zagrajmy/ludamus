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
  fetchReadyPage,
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
  return slots[Math.min(3, slots.length - 1)];
};

type RailHour = { label: string; rect: Rect };

// Ending in a time is necessary but nowhere near sufficient: the schedule body
// labels its own hour headings "11:00" too, and the first device run pressed
// three of those (x=31, the left time gutter) instead of the rail. So pin the
// rail's two other properties as well — it is the right-hand column, and the
// snapshot carries nodes scrolled out of view, which is how that run came to
// press y=-481. Matching the time rather than the "Jump to " prefix keeps this
// working in either language: the prefix is translated ("Przejdź do ..."), and
// the e2e run only escapes that today because it never compiles the catalogue.
const RAIL_HOUR_LABEL = /\d{1,2}:\d{2}$/;
const RAIL_COLUMN_FRACTION = 0.6;

// Press those markers rather than a coordinate derived from the viewport: the
// old aim, `viewport.width - 4`, was a guess at where the rail sits, and a rect
// from the snapshot is not.
const railHourTargets = (snapshot: CaptureSnapshotResult): RailHour[] => {
  const viewport = viewportOf(snapshot);
  const onScreen = (rect: Rect): boolean =>
    rect.y >= viewport.y && rect.y + rect.height <= viewport.y + viewport.height;
  const inRailColumn = (rect: Rect): boolean =>
    rect.x > viewport.x + viewport.width * RAIL_COLUMN_FRACTION;

  const hours = snapshot.nodes.flatMap((node) => {
    const label = node.label ?? "";
    if (!RAIL_HOUR_LABEL.test(label) || !node.rect) return [];
    if (!onScreen(node.rect) || !inRailColumn(node.rect)) return [];
    return [{ label, rect: node.rect }];
  });
  if (hours.length === 0) {
    // Name what was on screen and where, so a run that finds no rail says why
    // rather than leaving the next reader to guess at the layout.
    const seen = snapshot.nodes
      .flatMap((node) =>
        node.label && node.rect
          ? [`${node.label}@${Math.round(node.rect.x)},${Math.round(node.rect.y)}`]
          : [],
      )
      .slice(0, 16)
      .join(" | ");
    throw new Error(
      `No hour markers in the rail column (x > ${Math.round(
        viewport.x + viewport.width * RAIL_COLUMN_FRACTION,
      )}) and on screen. Saw: ${seen}`,
    );
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
  let snapshot: CaptureSnapshotResult | null = null;
  do {
    // A snapshot taken while Safari is still launching throws; that is a state
    // to wait out, not to end the run on.
    try {
      snapshot = await takeSnapshot();
    } catch (error) {
      console.warn("Snapshot failed while the page was settling; retrying.", error);
    }
    if (snapshot && scheduleOnScreen(snapshot)) return snapshot;
    await wait(500);
  } while (Date.now() < deadline);

  throw new Error("The slot anchor did not bring the schedule into the viewport.");
};

// Absence is the pass here, so a snapshot taken before the callout has had time
// to appear reads as success — the same false result the fixed wait after each
// press used to risk. Poll instead: return as soon as something surfaces, and
// only conclude "nothing" once the window has actually elapsed.
const surfacedCallout = async (timeoutMs: number): Promise<string[]> => {
  const deadline = Date.now() + timeoutMs;
  do {
    await wait(500);
    const labels = await snapshotLabels();
    const surfaced = calloutSignals.filter((signal) =>
      labels.some((label) => label.includes(signal)),
    );
    if (surfaced.length > 0) return surfaced;
  } while (Date.now() < deadline);
  return [];
};

let surfacedCalloutSignals: string[] = [];

beforeAll(async () => {
  const html = await fetchReadyPage(eventUrl, "schedule-rail");
  const udid = await prepareDevice();

  const scheduleUrl = new URL(eventUrl);
  scheduleUrl.hash = `slot-${railSlotAnchor(html)}`;
  console.log(`Opening Safari at ${scheduleUrl.toString()}...`);
  await openUrl(scheduleUrl.toString(), udid);

  // The settled snapshot serves both the guard and the rail geometry below.
  const snapshot = await waitForSchedule(90_000);

  for (const hour of railHourTargets(snapshot)) {
    const x = hour.rect.x + hour.rect.width / 2;
    const y = hour.rect.y + hour.rect.height / 2;
    console.log(
      `Long-pressing ${JSON.stringify(hour.label)} at x=${Math.round(x)} y=${Math.round(y)}...`,
    );
    await client.interactions.longPress({ ...deviceOptions, x, y, durationMs: 800 });
    const surfaced = await surfacedCallout(2500);
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
