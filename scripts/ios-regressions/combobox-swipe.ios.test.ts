import type { SnapshotNode } from "agent-device";

import { afterAll, beforeAll, expect, test } from "bun:test";

import { createIosHarness, hookTimeoutMs, resolveEventUrl, sessionName } from "./harness";
import { fieldNamed, listSwipeVerdict, optionNodes, rowsBelow } from "./list-swipe";
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

// A swipe from the fifth row to the second: long enough that the runner
// cannot deliver it as a tap, and inside the six-row box the list shows, so
// the list takes it rather than the sheet behind it.
const SWIPE_FROM_ROW = 4;
const SWIPE_TO_ROW = 1;
const SWIPE_DURATION_MS = 250;
// After the swipe the rendered window has moved; the third row below the
// field is inside the box whatever the overscan above it rendered.
const TAP_ROW = 2;
const MIN_ROWS = SWIPE_FROM_ROW + 1;
const SETTLE_MS = 800;
const WAIT_MS = 15_000;
const LABELS_IN_ERROR = 30;

const { client, deviceOptions, takeSnapshot, close, wait, openUrl, prepareDevice } =
  createIosHarness(session);

const describeTree = (nodes: readonly SnapshotNode[]): string =>
  nodes.slice(0, LABELS_IN_ERROR).map(describeNode).join(" | ") || "none";

const rectOf = (node: SnapshotNode, what: string): Rect => {
  if (!node.rect) throw new Error(`${what} has no rect to tap: ${describeNode(node)}`);
  return node.rect;
};

const tapCentre = async (rect: Rect, what: string): Promise<void> => {
  const { x, y } = centreOf(rect);
  console.log(`Tapping ${what} at x=${Math.round(x)} y=${Math.round(y)}...`);
  await client.interactions.click({ ...deviceOptions, x, y });
};

// Polled, not slept: the sheet and the list both animate in, and a snapshot
// taken mid-way reads what is about to be there as missing. A snapshot taken
// while Safari is still settling throws; that is a state to wait out, not to
// end the run on.
const waitFor = async <T>(
  what: string,
  probe: (nodes: readonly SnapshotNode[]) => T | null,
): Promise<T> => {
  let last: readonly SnapshotNode[] = [];
  const found = await pollUntil(
    async () => {
      try {
        last = (await takeSnapshot()).nodes;
      } catch (error) {
        console.warn("Snapshot failed while the page was settling; retrying.", error);
        return null;
      }
      return probe(last);
    },
    { timeoutMs: WAIT_MS },
  );
  if (found !== null) return found;
  throw new Error(`${what} did not appear in ${WAIT_MS}ms. Nodes: ${describeTree(last)}.`);
};

type ListState = { options: SnapshotNode[]; value: string };

const listFrom = (nodes: readonly SnapshotNode[], names: ReadonlySet<string>): ListState => ({
  options: optionNodes(nodes, names),
  value: fieldNamed(nodes, HOST_FIELD_LABEL)?.value ?? "",
});

const readList = async (names: ReadonlySet<string>): Promise<ListState> =>
  listFrom((await takeSnapshot()).nodes, names);

let issue: string | null = null;

beforeAll(async () => {
  const html = await fetchReadyPage(eventUrl, 'data-host="');
  const names = namesFrom(html, CARD_HOSTS);
  if (names.size < MIN_ROWS) {
    throw new Error(
      `${eventUrl.toString()} rendered ${names.size} hosts; the spec needs at least ${MIN_ROWS} to scroll through.`,
    );
  }
  await prepareDevice();

  console.log(`Opening Safari at ${eventUrl.toString()}...`);
  await openUrl(eventUrl.toString(), { expectedLabels: [FILTERS_LABEL], scope: FILTERS_LABEL });

  const filters = await waitFor(
    `The ${JSON.stringify(FILTERS_LABEL)} button`,
    (nodes) => nodes.find((node) => labelOf(node) === FILTERS_LABEL) ?? null,
  );
  await tapCentre(rectOf(filters, "the Filters button"), "the Filters button");

  const field = await waitFor(`The ${JSON.stringify(HOST_FIELD_LABEL)} field`, (nodes) =>
    fieldNamed(nodes, HOST_FIELD_LABEL),
  );
  // Logged so a device run says which way fieldNamed told the field from its
  // label, and the other way can go once one run has.
  console.log(`Host field: ${describeNode(field)}`);
  const fieldRect = rectOf(field, "the host field");
  await tapCentre(fieldRect, "the host field");
  const fieldBottom = fieldRect.y + fieldRect.height;

  const before = await waitFor(`The host list's first ${MIN_ROWS} rows`, (nodes) => {
    const state = listFrom(nodes, names);
    return state.options.length >= MIN_ROWS ? state : null;
  });
  const rows = rowsBelow(placed(before.options), fieldBottom);
  if (rows.length < MIN_ROWS) {
    throw new Error(
      `Only ${rows.length} rows sit below the field (y=${Math.round(fieldBottom)}); the swipe ` +
        `needs ${MIN_ROWS}. Rows: ${JSON.stringify(rows.map((row) => `${row.label}@${Math.round(row.rect.y)}`))}.`,
    );
  }
  const fromRow = rows[SWIPE_FROM_ROW];
  const toRow = rows[SWIPE_TO_ROW];
  const from = centreOf(fromRow.rect);
  const to = centreOf(toRow.rect);
  console.log(
    `Swiping from ${JSON.stringify(fromRow.label)} (y=${Math.round(from.y)}) up to ` +
      `${JSON.stringify(toRow.label)} (y=${Math.round(to.y)})...`,
  );
  await client.interactions.swipe({ ...deviceOptions, from, to, durationMs: SWIPE_DURATION_MS });
  await wait(SETTLE_MS);

  // NOTE: collected by mobile.yml's artifact upload, for a person to open.
  const shot = await client.capture.screenshot({
    ...deviceOptions,
    path: `${process.env.RUNNER_TEMP ?? "/tmp"}/ios-shots/host-list-after-swipe.png`,
    maxSize: 900,
  });
  console.log(`Screenshot after the swipe: ${shot.path}`);

  const after = await readList(names);
  const shift = medianShift(before.options, after.options);
  console.log(
    `SWIPE rowsBefore=${before.options.length} rowsAfter=${after.options.length} ` +
      `travelled=${shift === null ? "?" : Math.round(shift)}pt ` +
      `value=${JSON.stringify(before.value)} -> ${JSON.stringify(after.value)}`,
  );

  let tapped: Placed | null = null;
  let valueAfterTap: string | null = null;
  const target = rowsBelow(placed(after.options), fieldBottom)[TAP_ROW] ?? null;
  if (after.value === before.value && target) {
    tapped = target;
    await tapCentre(target.rect, JSON.stringify(target.label));
    await wait(SETTLE_MS);
    const picked = await readList(names);
    valueAfterTap = picked.value;
    console.log(
      `TAP value=${JSON.stringify(valueAfterTap)} rowsLeft=${picked.options.length} ` +
        `(a touch pick closes the list)`,
    );
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
