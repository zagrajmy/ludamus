import type { CaptureSnapshotResult } from "agent-device";

import { afterAll, beforeAll, expect, test } from "bun:test";

import type { Rect } from "./harness";

import {
  baseUrl,
  centreOnScreen,
  createIosHarness,
  describeNode,
  hookTimeoutMs,
  pollUntil,
  sessionName,
} from "./harness";

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

// Accessibility engines collapse runs of whitespace in a name; markup keeps its
// indentation. Collapse both sides the same way before comparing.
const collapse = (value: string): string => value.replace(/\s+/g, " ").trim();

const namesFrom = (html: string, pattern: RegExp): Set<string> =>
  new Set(
    [...html.matchAll(pattern)].flatMap((m) => (m[1] ? [collapse(decodeEntities(m[1]))] : [])),
  );

// This page overflows the runner's 300-node snapshot budget, and the rail nav
// is the last element in the document — an unscoped snapshot truncates before
// ever reaching it (seven device runs of "no rail names appeared" traced back
// to exactly this). Scoping the snapshot to the nav's accessible name walks
// only its subtree — a few dozen nodes — so every rendered marker surfaces.
// Both marker name sets come from the served, already-translated markup: the
// links' bare hour text ("10") and their aria-labels, whichever the engine
// reports. The patterns are wed to the attribute order that
// templates/chronology/_compact_schedule.html renders; a reorder there fails
// the loud railNavName / markerNames guards below, never a device run.
const RAIL_NAV_NAME = /<nav class="schedule-rail[^"]*"\s+aria-label="([^"]+)"/;
const RAIL_HOUR_NAMES = /class="schedule-rail-hour[^"]*"[^>]*aria-label="([^"]+)"/g;
const RAIL_HOUR_TEXTS = /class="schedule-rail-hour[^"]*"[^>]*>([^<]+)<\/a>/g;

const railNavName = (html: string): string => {
  const name = RAIL_NAV_NAME.exec(html)?.[1];
  if (!name) throw new Error("The schedule rail nav rendered no aria-label to scope by.");
  return collapse(decodeEntities(name));
};

// A marker link and its own text node both match the name sets at the same
// spot; one press per spot is enough. The screen band drops markers that are
// rendered but not yet scrolled into view — before fitRail (event-timeline.ts)
// thins the rail, or before Safari applies the fragment scroll — so a press
// never lands on a clipped or off-screen target.
const railMarkersFrom = (
  snapshot: CaptureSnapshotResult,
  names: Set<string>,
  screen: Rect,
): RailHour[] => {
  const seen = new Set<number>();
  return snapshot.nodes.flatMap((node) => {
    const label = node.label ? collapse(node.label) : "";
    if (!label || !node.rect || !names.has(label)) return [];
    if (node.rect.width <= 0 || node.rect.height <= 0) return [];
    if (!centreOnScreen(node.rect, screen)) return [];
    const spot = Math.round((node.rect.y + node.rect.height / 2) / 4);
    if (seen.has(spot)) return [];
    seen.add(spot);
    return [{ label, rect: node.rect }];
  });
};

// Polled, not slept: Safari applies the fragment scroll somewhere after load,
// and a fixed wait is either too short on a slow runner or wasted on a fast
// one. Without the check the long-press would land on empty page and the spec
// would pass by finding no callout, which is not the same as the callout being
// suppressed.
const waitForRailMarkers = async (
  timeoutMs: number,
  navName: string,
  markerNames: Set<string>,
): Promise<RailHour[]> => {
  let screen: Rect | null = null;
  let lastSnapshotError: unknown = null;
  // A slot, not a plain `let`: the assignment happens inside the probe
  // closure, which TypeScript's flow analysis cannot see from out here.
  const last: { scoped: CaptureSnapshotResult | null } = { scoped: null };
  const markers = await pollUntil<RailHour[]>(
    async () => {
      // A snapshot taken while Safari is still launching throws; that is a
      // state to wait out, not to end the run on. The screen rect comes from
      // an unscoped snapshot's root node — the window frame, which truncation
      // cannot touch — and holds still for the rest of the run.
      try {
        screen ??= viewportOf(await takeSnapshot());
        last.scoped = await takeSnapshot(navName);
      } catch (error) {
        lastSnapshotError = error;
        console.warn("Snapshot failed while the page was settling; retrying.", error);
        return null;
      }
      const found = railMarkersFrom(last.scoped, markerNames, screen);
      return found.length > 0 ? found : null;
    },
    { timeoutMs },
  );
  if (markers) return markers;

  const scoped = last.scoped;
  if (!scoped) {
    throw new Error(
      `No snapshot succeeded in ${timeoutMs}ms; last error: ${String(lastSnapshotError)}`,
    );
  }
  // The scoped tree is small, so the dump can afford to show all of it. A
  // truncated or screen-sized root means the scope query missed the nav and
  // the runner fell back to the full tree.
  const sample = scoped.nodes.slice(0, 15).map(describeNode).join(" | ");
  throw new Error(
    `No on-screen rail markers in the ${JSON.stringify(navName)}-scoped snapshot: ` +
      `${scoped.nodes.length} nodes, truncated=${String(scoped.truncated)}, ` +
      `screen=${JSON.stringify(screen)}. ` +
      `Expected labels like ${JSON.stringify([...markerNames][0])}. Nodes: ${sample || "none"}.`,
  );
};

// A handful spread down the rail: the callout is a per-element behaviour, so
// one hour passing says little about the rest. Dedup keeps a short rail from
// pressing the same marker four times.
const pressTargets = (markers: RailHour[]): RailHour[] =>
  [...new Set([0.1, 0.35, 0.6, 0.85].map((f) => Math.floor(f * markers.length)))].map(
    (index) => markers[index],
  );

// Absence is the pass here, so both false-negative paths need closing. One: a
// snapshot taken before the callout has had time to appear reads as success —
// poll instead, and only conclude "nothing" once the window has elapsed. Two:
// the callout sheet joins a page that already overflows the snapshot's node
// budget, so ask for the sheet directly — the scope resolves via a live
// element query with no such cap. When no callout is up the scope misses and
// the runner falls back to the full tree, which then contains no signal.
const surfacedCallout = async (timeoutMs: number): Promise<string[]> =>
  (await pollUntil<string[]>(
    async () => {
      const labels = await snapshotLabels("Open in");
      const surfaced = calloutSignals.filter((signal) =>
        labels.some((label) => label.includes(signal)),
      );
      return surfaced.length > 0 ? surfaced : null;
    },
    { timeoutMs },
  )) ?? [];

let surfacedCalloutSignals: string[] = [];

beforeAll(async () => {
  const html = await fetchReadyPage(eventUrl, "schedule-rail");
  const udid = await prepareDevice();

  const navName = railNavName(html);
  const markerNames = new Set([
    ...namesFrom(html, RAIL_HOUR_NAMES),
    ...namesFrom(html, RAIL_HOUR_TEXTS),
  ]);
  if (markerNames.size === 0) {
    throw new Error(
      "The page rendered no rail markers; the spec needs them to know what to press.",
    );
  }

  const scheduleUrl = new URL(eventUrl);
  scheduleUrl.hash = `slot-${railSlotAnchor(html)}`;
  console.log(`Opening Safari at ${scheduleUrl.toString()}...`);
  await openUrl(scheduleUrl.toString(), udid);

  const markers = await waitForRailMarkers(90_000, navName, markerNames);

  for (const hour of pressTargets(markers)) {
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
