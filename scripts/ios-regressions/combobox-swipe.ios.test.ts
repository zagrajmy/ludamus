import type { CaptureSnapshotResult, SnapshotNode } from "agent-device";

import { afterAll, beforeAll, expect, test } from "bun:test";

import { createIosHarness, hookTimeoutMs, resolveEventUrl, sessionName } from "./harness";
import { byTop, fieldNamed, listBox, listSwipeVerdict, optionNodes, rowsInBox } from "./list-swipe";
import { fetchReadyPage, namesFrom } from "./page";
import {
  centreOf,
  describeNode,
  labelOf,
  medianShift,
  type Placed,
  placed,
  pollUntil,
  type Rect,
  viewportOf,
} from "./snapshot";

// The reported symptom: on an iPhone the host list could not be scrolled,
// because every swipe began with a finger on a row and picked it. Swipe
// through the open list on a real Safari and require the list to scroll with
// nothing picked, then tap a row and require that to pick. The verdict is
// listSwipeVerdict, tested off the device; this file measures.
const session = sessionName("combobox");
const eventUrl = resolveEventUrl("/event/kapitularz-2025-anonymized/");

// The button that opens the filter sheet and the field inside it, by their
// accessible names. Both come from event.html; a rename fails the loud waits
// below, never a device run.
const FILTERS_LABEL = "Filters";
const HOST_FIELD_LABEL = "Host";
const CARD_HOSTS = /data-host="([^"]*)"/g;

// The swipe runs from the lowest row in the list's box to the highest, so it
// is as long as the box allows and never leaves it; three rows is the least
// worth swiping through. The list may sit above the field or below it: with
// the keyboard up there is rarely room below, and the placement flips.
const MIN_VISIBLE_ROWS = 3;
const SWIPE_DURATION_MS = 250;
const SETTLE_MS = 800;
const WAIT_MS = 15_000;
const LABELS_IN_ERROR = 30;
const KEYBOARD = /keyboard/i;
const shotsDir = `${process.env.RUNNER_TEMP ?? "/tmp"}/ios-shots`;

const { client, deviceOptions, takeSnapshot, close, wait, openUrl, prepareDevice } =
  createIosHarness(session);

const describeTree = (nodes: readonly SnapshotNode[]): string =>
  nodes.slice(0, LABELS_IN_ERROR).map(describeNode).join(" | ") || "none";

const describeRows = (rows: readonly Placed[]): string =>
  JSON.stringify(rows.map((row) => `${row.label}@${Math.round(row.rect.y)}`));

const rectOf = (node: SnapshotNode, what: string): Rect => {
  if (!node.rect) throw new Error(`${what} has no rect to tap: ${describeNode(node)}`);
  return node.rect;
};

const tapCentre = async (rect: Rect, what: string): Promise<void> => {
  const { x, y } = centreOf(rect);
  console.log(`Tapping ${what} at x=${Math.round(x)} y=${Math.round(y)}...`);
  await client.interactions.click({ ...deviceOptions, x, y });
};

// NOTE: collected by mobile.yml's artifact upload, for a person to open.
const screenshot = async (name: string): Promise<void> => {
  const shot = await client.capture.screenshot({
    ...deviceOptions,
    path: `${shotsDir}/${name}.png`,
    maxSize: 900,
  });
  console.log(`Screenshot ${name}: ${shot.path}`);
};

// Polled, not slept: the sheet and the list both animate in, and a snapshot
// taken mid-way reads what is about to be there as missing. A snapshot taken
// while Safari is still settling throws; that is a state to wait out, not to
// end the run on. The failure dump is capped, and the page's own chrome fills
// that cap before the sheet begins, so a wait names the nodes worth dumping.
const waitFor = async <T>(
  what: string,
  probe: (snapshot: CaptureSnapshotResult) => T | null,
  relevant: (node: SnapshotNode, screen: Rect) => boolean = () => true,
): Promise<T> => {
  const last: { snapshot: CaptureSnapshotResult | null } = { snapshot: null };
  const found = await pollUntil(
    async () => {
      try {
        last.snapshot = await takeSnapshot();
      } catch (error) {
        console.warn("Snapshot failed while the page was settling; retrying.", error);
        return null;
      }
      return probe(last.snapshot);
    },
    { timeoutMs: WAIT_MS },
  );
  if (found !== null) return found;
  const seen = last.snapshot;
  const shown = seen ? seen.nodes.filter((node) => relevant(node, viewportOf(seen))) : [];
  throw new Error(`${what} did not appear in ${WAIT_MS}ms. Nodes: ${describeTree(shown)}.`);
};

// Drawn inside the window rather than spanning it, which is what tells the
// sheet's nodes from the page containers above it in the tree.
const inset = (node: SnapshotNode, screen: Rect): boolean =>
  node.rect !== undefined &&
  node.rect.y > screen.y &&
  node.rect.y + node.rect.height <= screen.y + screen.height;

type ListState = {
  screen: Rect;
  options: SnapshotNode[];
  // The box the list shows its rows through, and the rows drawn inside it.
  box: Rect | null;
  shown: Placed[];
  value: string;
  keyboard: boolean;
};

const listFrom = (snapshot: CaptureSnapshotResult, names: ReadonlySet<string>): ListState => {
  const options = optionNodes(snapshot.nodes, names);
  const rows = placed(options);
  const box = listBox(snapshot.nodes, rows);
  return {
    screen: viewportOf(snapshot),
    options,
    box,
    shown: box ? rowsInBox(rows, box) : [],
    value: fieldNamed(snapshot.nodes, HOST_FIELD_LABEL)?.value ?? "",
    keyboard: snapshot.nodes.some((node) => KEYBOARD.test(`${node.type ?? ""} ${labelOf(node)}`)),
  };
};

const readList = async (names: ReadonlySet<string>): Promise<ListState> =>
  listFrom(await takeSnapshot(), names);

const describeBox = (box: Rect | null): string =>
  box ? `${Math.round(box.y)}+${Math.round(box.height)}` : "none";

const describeList = (state: ListState): string =>
  `screen=${Math.round(state.screen.width)}x${Math.round(state.screen.height)} ` +
  `keyboard=${String(state.keyboard)} value=${JSON.stringify(state.value)} ` +
  `box=${describeBox(state.box)} shown=${describeRows(state.shown)} ` +
  `rendered=${describeRows(byTop(placed(state.options)))}`;

let issue: string | null = null;

beforeAll(async () => {
  const html = await fetchReadyPage(eventUrl, 'data-host="');
  const names = namesFrom(html, CARD_HOSTS);
  if (names.size < MIN_VISIBLE_ROWS) {
    throw new Error(
      `${eventUrl.toString()} rendered ${names.size} hosts; the spec needs at least ${MIN_VISIBLE_ROWS} to scroll through.`,
    );
  }
  await prepareDevice();

  console.log(`Opening Safari at ${eventUrl.toString()}...`);
  await openUrl(eventUrl.toString(), { expectedLabels: [FILTERS_LABEL], scope: FILTERS_LABEL });

  const filters = await waitFor(
    `The ${JSON.stringify(FILTERS_LABEL)} button`,
    (snapshot) => snapshot.nodes.find((node) => labelOf(node) === FILTERS_LABEL) ?? null,
  );
  await tapCentre(rectOf(filters, "the Filters button"), "the Filters button");

  const field = await waitFor(
    `The ${JSON.stringify(HOST_FIELD_LABEL)} field`,
    (snapshot) => fieldNamed(snapshot.nodes, HOST_FIELD_LABEL),
    inset,
  );
  console.log(`Host field: ${describeNode(field)}`);
  await tapCentre(rectOf(field, "the host field"), "the host field");

  const opened = await waitFor(
    `The host list's first ${MIN_VISIBLE_ROWS} rows`,
    (snapshot) => {
      const state = listFrom(snapshot, names);
      return state.options.length >= MIN_VISIBLE_ROWS ? state : null;
    },
    inset,
  );
  console.log(`LIST ${describeList(opened)}`);
  await screenshot("host-list-open");
  // The rows are in the tree before they settle: the keyboard animates in
  // and the placement follows it, so where the list ends up is known only
  // once it stops moving. Polled for the rows a finger can reach.
  const last = { state: opened };
  const before = await pollUntil(
    async () => {
      last.state = await readList(names);
      return last.state.shown.length >= MIN_VISIBLE_ROWS ? last.state : null;
    },
    { timeoutMs: WAIT_MS },
  );
  if (!before) {
    throw new Error(
      `Only ${last.state.shown.length} of the list's ${last.state.options.length} rows are ` +
        `inside its box after ${WAIT_MS}ms, and the swipe needs ${MIN_VISIBLE_ROWS}: the list ` +
        `opened where a finger cannot reach it. ${describeList(last.state)}.`,
    );
  }
  const rows = before.shown;
  const fromRow = rows[rows.length - 1];
  const toRow = rows[0];
  const from = centreOf(fromRow.rect);
  const to = centreOf(toRow.rect);
  console.log(
    `Swiping from ${JSON.stringify(fromRow.label)} (y=${Math.round(from.y)}) up to ` +
      `${JSON.stringify(toRow.label)} (y=${Math.round(to.y)})...`,
  );
  await client.interactions.swipe({ ...deviceOptions, from, to, durationMs: SWIPE_DURATION_MS });
  await wait(SETTLE_MS);
  await screenshot("host-list-after-swipe");

  const after = await readList(names);
  const shift = medianShift(before.options, after.options);
  console.log(
    `SWIPE travelled=${shift === null ? "?" : Math.round(shift)}pt ${describeList(after)}`,
  );

  // The box does not move when its rows scroll, so the rows now inside the
  // box before the swipe are the ones a finger can tap.
  let tapped: Placed | null = null;
  let valueAfterTap: string | null = null;
  const reachable = before.box ? rowsInBox(placed(after.options), before.box) : [];
  const target = reachable[Math.floor(reachable.length / 2)] ?? null;
  if (after.value === before.value && target) {
    tapped = target;
    await tapCentre(target.rect, JSON.stringify(target.label));
    await wait(SETTLE_MS);
    const picked = await readList(names);
    valueAfterTap = picked.value;
    console.log(`TAP ${describeList(picked)} (a touch pick closes the list)`);
  }

  issue = listSwipeVerdict({
    rowsBefore: before.options.length,
    shift,
    valueBefore: before.value,
    valueAfterSwipe: after.value,
    openAfterSwipe: after.options.length > 0,
    tapped: tapped?.label ?? null,
    valueAfterTap,
  });
}, hookTimeoutMs);

afterAll(close, 30_000);

test("a swipe scrolls the host list without picking, and a tap still picks", () => {
  expect(issue).toBeNull();
});
