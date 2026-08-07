import type { CaptureSnapshotResult, SnapshotNode } from "agent-device";

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

// Attribute values arrive escaped; the rail's labels carry event and day names.
// `&amp;` goes last: unescaping it first would turn a served `&amp;lt;` (the
// literal text "&lt;") into "<" — CodeQL's double-unescape, and a name that
// would never match its device label.
const decodeEntities = (value: string): string =>
  value
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#x27;", "'")
    .replaceAll("&#39;", "'")
    .replaceAll("&amp;", "&");

const namesFrom = (html: string, pattern: RegExp): Set<string> =>
  new Set([...html.matchAll(pattern)].flatMap((m) => (m[1] ? [decodeEntities(m[1])] : [])));

// Take the accessible names the page actually renders rather than guessing at
// them. Two earlier rounds guessed: `viewport.width - 4` assumed where the rail
// sits, and matching a label ending in a time assumed only the rail carries one
// — the device then pressed the schedule body's own "11:00" headings in the
// left gutter. The served markup is ground truth for both the rail and the
// session links, needs no geometry, and is already translated, so this holds
// whether or not the message catalogue is ever compiled.
const RAIL_HOUR_NAMES = /class="schedule-rail-hour[^"]*"[^>]*aria-label="([^"]+)"/g;
const SESSION_LINK_NAMES =
  /<a[^>]*class="session-link[^"]*"[^>]*>\s*<span class="sr-only">([^<]+)<\/span>/g;

// The runner's `hittable` read like the principled visibility check, but the
// device falsified it: with it required, zero of 110 session links counted as
// visible in 90s, and the modal spec judged content "not visible" that its
// next step then tapped. It reads false for nodes inside Safari's web content.
// Rects, in contrast, have been populated and accurate in every device log so
// far — so the visibility question stays geometric. CHROME_INSET keeps presses
// clear of Safari's top and bottom bars; its exact size is unknowable from
// here, and being conservative only shifts which markers get pressed — set
// membership, not position, decides what they are.
const CHROME_INSET = 120;

const centreOnScreen = (rect: Rect, viewport: Rect): boolean => {
  const centreY = rect.y + rect.height / 2;
  return (
    centreY >= viewport.y + CHROME_INSET && centreY <= viewport.y + viewport.height - CHROME_INSET
  );
};

const pressable = (
  snapshot: CaptureSnapshotResult,
  node: SnapshotNode,
  names: Set<string>,
): boolean =>
  Boolean(
    node.label &&
    names.has(node.label) &&
    node.rect &&
    centreOnScreen(node.rect, viewportOf(snapshot)),
  );

const railHourTargets = (snapshot: CaptureSnapshotResult, names: Set<string>): RailHour[] => {
  const hours = snapshot.nodes.flatMap((node) =>
    pressable(snapshot, node, names) && node.label && node.rect
      ? [{ label: node.label, rect: node.rect }]
      : [],
  );
  if (hours.length === 0) {
    // Report the rail nodes that were found but rejected, with the runner's own
    // fields, so a failure says which property was missing instead of leaving
    // the next reader to infer it from a screenshot they cannot take.
    const rejected = snapshot.nodes
      .flatMap((node) => (node.label && names.has(node.label) ? [node] : []))
      .slice(0, 8)
      .map(
        (node) =>
          `${node.label} type=${node.type ?? "?"} hittable=${String(node.hittable)} rect=${
            node.rect ? `${Math.round(node.rect.x)},${Math.round(node.rect.y)}` : "none"
          }`,
      )
      .join(" | ");
    throw new Error(
      `No pressable rail hour among ${names.size} rendered markers.` +
        (rejected ? ` Rejected: ${rejected}` : " None appeared in the snapshot at all."),
    );
  }
  // A handful spread down the rail: the callout is a per-element behaviour, so
  // one hour passing says little about the rest. Dedup keeps a short rail from
  // pressing the same marker four times.
  return [...new Set([0.1, 0.35, 0.6, 0.85].map((f) => Math.floor(f * hours.length)))].map(
    (index) => hours[index],
  );
};

const scheduleOnScreen = (snapshot: CaptureSnapshotResult, names: Set<string>): boolean =>
  snapshot.nodes.some((node) => pressable(snapshot, node, names));

// Polled, not slept: Safari applies the fragment scroll somewhere after load,
// and a fixed wait is either too short on a slow runner or wasted on a fast
// one. Without the check the long-press would land on empty page and the spec
// would pass by finding no callout, which is not the same as the callout being
// suppressed.
const waitForSchedule = async (
  timeoutMs: number,
  sessionNames: Set<string>,
): Promise<CaptureSnapshotResult> => {
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
    if (snapshot && scheduleOnScreen(snapshot, sessionNames)) return snapshot;
    await wait(500);
  } while (Date.now() < deadline);

  const matched =
    snapshot?.nodes.filter((node) => node.label && sessionNames.has(node.label)) ?? [];
  const sample = matched
    .slice(0, 6)
    .map(
      (node) =>
        `${node.label} type=${node.type ?? "?"} hittable=${String(node.hittable)} rect=${
          node.rect ? `${Math.round(node.rect.x)},${Math.round(node.rect.y)}` : "none"
        }`,
    )
    .join(" | ");
  throw new Error(
    matched.length > 0
      ? `Session links matched by name but none within the viewport band: ${sample}`
      : `None of the ${sessionNames.size} rendered session names appeared in the snapshot ` +
          `(${snapshot?.nodes.length ?? 0} nodes).`,
  );
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

  const railNames = namesFrom(html, RAIL_HOUR_NAMES);
  const sessionNames = namesFrom(html, SESSION_LINK_NAMES);
  if (railNames.size === 0 || sessionNames.size === 0) {
    throw new Error(
      `The page rendered ${railNames.size} rail markers and ${sessionNames.size} session links; ` +
        "the spec needs both to know what to press and whether it landed.",
    );
  }

  const scheduleUrl = new URL(eventUrl);
  scheduleUrl.hash = `slot-${railSlotAnchor(html)}`;
  console.log(`Opening Safari at ${scheduleUrl.toString()}...`);
  await openUrl(scheduleUrl.toString(), udid);

  // The settled snapshot serves both the guard and the rail geometry below.
  const snapshot = await waitForSchedule(90_000, sessionNames);

  for (const hour of railHourTargets(snapshot, railNames)) {
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
