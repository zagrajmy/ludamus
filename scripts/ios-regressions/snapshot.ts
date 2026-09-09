import type { CaptureSnapshotResult, SnapshotNode } from "agent-device";

export type Rect = { x: number; y: number; width: number; height: number };

// NOTE: only reached when a snapshot comes back with no nodes to read a rect
// from. A shape that keeps arithmetic finite, not this run's screen.
const FALLBACK_VIEWPORT: Rect = { x: 0, y: 0, width: 402, height: 874 };

// The root node is the window frame, which truncation cannot touch.
export const viewportOf = (snapshot: CaptureSnapshotResult): Rect =>
  snapshot.nodes[0]?.rect ?? FALLBACK_VIEWPORT;

// The one poll-to-deadline loop: probe until it yields a value or the window
// closes, and only conclude "nothing" (null) once the window has actually
// elapsed -- which is what specs asserting absence rely on. The window ends on
// a probe, not a sleep, so its final interval is observed rather than slept
// away. A throwing probe aborts the poll.
export const pollUntil = async <T>(
  probe: () => Promise<T | null>,
  { timeoutMs, intervalMs = 500 }: { timeoutMs: number; intervalMs?: number },
): Promise<T | null> => {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const result = await probe();
    if (result !== null) return result;
    if (Date.now() >= deadline) return null;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
};

// SAFETY: the band for Safari's top and bottom chrome. Its exact size is
// unknowable from this sandbox; being conservative only narrows what counts as
// visible, which specs must treat as "press/check something else", never as a
// pass. The runner's `hittable` is NOT this check -- it reads false inside
// Safari's web content.
const CHROME_INSET = 120;

type Placed = { rect: Rect; label: string };

// Labelled nodes with a rect, which is every node the geometry helpers below
// can reason about.
const placed = (nodes: readonly SnapshotNode[]): Placed[] =>
  nodes.flatMap((node) => {
    const label = labelOf(node);
    return node.rect && label ? [{ rect: node.rect, label }] : [];
  });

const SCROLL_INDICATOR = /vertical scroll bar/i;

export const scrollBars = (nodes: readonly SnapshotNode[]): Rect[] =>
  placed(nodes)
    .filter(({ label }) => SCROLL_INDICATOR.test(label))
    .map(({ rect }) => rect);

// NOTE: the tree carries several vertical scroll views, and the ones spanning
// the whole window are containers that never move. The one inset from the
// screen is the viewport the page is actually given.
export const scrollerViewport = (bars: readonly Rect[], screen: Rect): Rect | null => {
  const inset = bars.filter((rect) => rect.height < screen.height);
  if (inset.length === 0) return null;
  return inset.reduce((a, b) => (a.height >= b.height ? a : b));
};

// NOTE: labels that occur more than once are dropped rather than guessed at;
// two nodes sharing a name give no way to say which moved where.
const uniquePositions = (nodes: readonly SnapshotNode[]): Map<string, number> => {
  const counts = new Map<string, number>();
  const positions = new Map<string, number>();
  for (const { rect, label } of placed(nodes)) {
    counts.set(label, (counts.get(label) ?? 0) + 1);
    positions.set(label, rect.y);
  }
  for (const [label, count] of counts) if (count > 1) positions.delete(label);
  return positions;
};

// How far the page moved between two snapshots, matching nodes on their labels.
// NOTE: median, not mean: sticky chrome stays put while the content travels,
// and a mean of the two populations reads as a page half-scrolled. Null under
// three anchors, where a median is one or two nodes' worth of luck.
export const medianShift = (
  before: readonly SnapshotNode[],
  after: readonly SnapshotNode[],
): number | null => {
  const start = uniquePositions(before);
  const deltas: number[] = [];
  for (const [label, y] of uniquePositions(after)) {
    const was = start.get(label);
    if (was !== undefined) deltas.push(y - was);
  }
  if (deltas.length < 3) return null;
  deltas.sort((a, b) => a - b);
  const mid = Math.floor(deltas.length / 2);
  return deltas.length % 2 === 0 ? (deltas[mid - 1]! + deltas[mid]!) / 2 : deltas[mid]!;
};

const LABEL_EXCERPT = 40;

// The lowest labelled content nodes, lowest first, as one log line.
export const lowestNodes = (nodes: readonly SnapshotNode[], count: number): string =>
  placed(nodes)
    .filter(({ label }) => !SCROLL_INDICATOR.test(label))
    .sort((a, b) => b.rect.y + b.rect.height - (a.rect.y + a.rect.height))
    .slice(0, count)
    .map(
      ({ rect, label }) =>
        `${Math.round(rect.y)}..${Math.round(rect.y + rect.height)} ${JSON.stringify(label.slice(0, LABEL_EXCERPT))}`,
    )
    .join("; ");

// Where Safari's bottom toolbar begins: the highest labelled node in the lower
// half of the screen that runs to the screen's bottom edge. NOTE: content
// rects are not clipped, so content never ends exactly at that edge; the
// toolbar's buttons do. Null when no such node is on screen.
export const toolbarTop = (nodes: readonly SnapshotNode[], screen: Rect): number | null => {
  const bottom = screen.y + screen.height;
  const tops = placed(nodes)
    .map(({ rect }) => rect)
    .filter((rect) => rect.y > screen.y + screen.height / 2 && rect.y + rect.height >= bottom)
    .map((rect) => rect.y);
  return tops.length === 0 ? null : Math.min(...tops);
};

export const centreOnScreen = (rect: Rect, viewport: Rect): boolean => {
  const centreX = rect.x + rect.width / 2;
  const centreY = rect.y + rect.height / 2;
  return (
    centreX >= viewport.x &&
    centreX <= viewport.x + viewport.width &&
    centreY >= viewport.y + CHROME_INSET &&
    centreY <= viewport.y + viewport.height - CHROME_INSET
  );
};

// NOTE: the runner reports a scoped container's accessible name with its role
// appended -- a nav named "Jump to time" comes back as "Jump to time,
// navigation" -- so an equality check reads a resolved scope as a miss.
export const matchesScopeLabel = (label: string, scope: string): boolean =>
  label === scope || label.startsWith(`${scope}, `);

// NOTE: accessibility engines collapse runs of whitespace in a name; markup
// keeps its indentation. Device labels are read through `labelOf` and names
// read from markup through `collapse`, so both sides of a comparison normalize
// alike.
export const collapse = (value: string): string => value.replace(/\s+/g, " ").trim();

export const labelOf = (node: SnapshotNode): string => collapse(node.label ?? node.value ?? "");

export const describeRect = (rect: Rect): string =>
  `${Math.round(rect.y)}+${Math.round(rect.height)}`;

export const describeNode = (node: SnapshotNode): string => {
  const rect = node.rect
    ? ` x=${Math.round(node.rect.x)} y=${Math.round(node.rect.y)} w=${Math.round(node.rect.width)} h=${Math.round(node.rect.height)}`
    : "";
  return `${node.type ?? "node"} ref=@${node.ref}${rect} hittable=${String(node.hittable)} label=${JSON.stringify(
    node.label ?? node.value ?? "",
  )}`;
};
