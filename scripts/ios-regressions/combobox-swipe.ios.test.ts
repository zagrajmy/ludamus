import type { SnapshotNode } from "agent-device";

import { afterAll, beforeAll, expect, test } from "bun:test";

import { createIosHarness, hookTimeoutMs, resolveEventUrl, sessionName } from "./harness";
import {
  centreOf,
  fieldNamed,
  listSwipeVerdict,
  optionNodes,
  type Row,
  rowsBelow,
  rowsOf,
} from "./list-swipe";
import { decodeEntities, fetchReadyPage } from "./page";
import { collapse, describeNode, labelOf, medianShift, pollUntil } from "./snapshot";

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
const LABELS_IN_ERROR = 30;

const { client, deviceOptions, takeSnapshot, close, wait, openUrl, prepareDevice } =
  createIosHarness(session);

const hostNames = (html: string): Set<string> =>
  new Set(
    [...html.matchAll(CARD_HOSTS)].flatMap((m) => (m[1] ? [collapse(decodeEntities(m[1]))] : [])),
  );

const describeTree = (nodes: readonly SnapshotNode[]): string =>
  nodes.slice(0, LABELS_IN_ERROR).map(describeNode).join(" | ") || "none";

const nodeLabelled = (nodes: readonly SnapshotNode[], label: string): SnapshotNode | null =>
  nodes.find((node) => labelOf(node) === label) ?? null;

const tapCentre = async (node: SnapshotNode, what: string): Promise<void> => {
  if (!node.rect) throw new Error(`${what} has no rect to tap: ${describeNode(node)}`);
  const { x, y } = centreOf(node.rect);
  console.log(`Tapping ${what} at x=${Math.round(x)} y=${Math.round(y)}...`);
  await client.interactions.click({ ...deviceOptions, x, y });
};

// Polled, not slept: the sheet and the list both animate in, and a snapshot
// taken mid-way reads what is about to be there as missing.
const waitForNode = async (
  timeoutMs: number,
  what: string,
  find: (nodes: readonly SnapshotNode[]) => SnapshotNode | null,
): Promise<SnapshotNode> => {
  let last: readonly SnapshotNode[] = [];
  const found = await pollUntil(
    async () => {
      try {
        last = (await takeSnapshot()).nodes;
        return find(last);
      } catch (error) {
        console.warn("Snapshot failed while the page was settling; retrying.", error);
        return null;
      }
    },
    { timeoutMs },
  );
  if (found) return found;
  throw new Error(`${what} did not appear in ${timeoutMs}ms. Nodes: ${describeTree(last)}.`);
};

type ListState = { nodes: readonly SnapshotNode[]; options: SnapshotNode[]; value: string };

const readList = async (names: ReadonlySet<string>): Promise<ListState> => {
  const nodes = (await takeSnapshot()).nodes;
  const field = fieldNamed(nodes, HOST_FIELD_LABEL);
  return { nodes, options: optionNodes(nodes, names), value: field?.value ?? "" };
};

const waitForRows = async (timeoutMs: number, names: ReadonlySet<string>): Promise<ListState> => {
  let seen = 0;
  let nodes: readonly SnapshotNode[] = [];
  const ready = await pollUntil(
    async () => {
      const state = await readList(names);
      seen = state.options.length;
      nodes = state.nodes;
      return seen >= MIN_ROWS ? state : null;
    },
    { timeoutMs },
  );
  if (ready) return ready;
  throw new Error(
    `The host list did not show ${MIN_ROWS} rows in ${timeoutMs}ms; saw ${seen} of ` +
      `${names.size} host names. Nodes: ${describeTree(nodes)}.`,
  );
};

let issue: string | null = null;

beforeAll(async () => {
  const html = await fetchReadyPage(eventUrl, 'data-host="');
  const names = hostNames(html);
  if (names.size < MIN_ROWS) {
    throw new Error(
      `${eventUrl.toString()} rendered ${names.size} hosts; the spec needs at least ${MIN_ROWS} to scroll through.`,
    );
  }
  await prepareDevice();

  console.log(`Opening Safari at ${eventUrl.toString()}...`);
  await openUrl(eventUrl.toString(), { expectedLabels: [FILTERS_LABEL], scope: FILTERS_LABEL });

  const filters = await waitForNode(
    15_000,
    `The ${JSON.stringify(FILTERS_LABEL)} button`,
    (nodes) => nodeLabelled(nodes, FILTERS_LABEL),
  );
  await tapCentre(filters, "the Filters button");

  const field = await waitForNode(
    15_000,
    `The ${JSON.stringify(HOST_FIELD_LABEL)} field`,
    (nodes) => fieldNamed(nodes, HOST_FIELD_LABEL),
  );
  await tapCentre(field, "the host field");
  const fieldBottom = field.rect ? field.rect.y + field.rect.height : 0;

  const before = await waitForRows(15_000, names);
  const rows = rowsBelow(rowsOf(before.options), fieldBottom);
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

  let tapped: Row | null = null;
  let valueAfterTap: string | null = null;
  const target = rowsBelow(rowsOf(after.options), fieldBottom)[TAP_ROW] ?? null;
  if (after.value === before.value && target) {
    tapped = target;
    const { x, y } = centreOf(target.rect);
    console.log(
      `Tapping ${JSON.stringify(target.label)} at x=${Math.round(x)} y=${Math.round(y)}...`,
    );
    await client.interactions.click({ ...deviceOptions, x, y });
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
