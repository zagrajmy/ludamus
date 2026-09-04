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

// The scrolling viewport, read off the accessibility tree.
//
// A device run reports several of these, and most are useless: on an 874pt
// screen the tree carried `0+874` four times over — scroll views spanning the
// whole window, which never move — alongside one `62+750`, inset by Safari's
// chrome top and bottom. That inset one is the viewport the page actually gets,
// so "tallest" is the wrong pick and "tallest that is shorter than the screen"
// is the right one. Collapsing the toolbar returns some of the bottom inset and
// this grows.
//
// Nothing here touches a device, which is the point: every earlier guess at a
// reference edge cost a 45-minute macOS job to disprove.
const SCROLL_INDICATOR = /vertical scroll bar/i;

export const scrollerViewport = (nodes: readonly SnapshotNode[], screen: Rect): Rect | null => {
  const inset = nodes
    .filter((node) => node.rect && SCROLL_INDICATOR.test(labelOf(node)))
    .map((node) => node.rect as Rect)
    .filter((rect) => rect.height < screen.height);
  if (inset.length === 0) return null;
  return inset.reduce((a, b) => (a.height >= b.height ? a : b));
};

// Labels that occur exactly once, with the y they occur at. Duplicates are
// dropped rather than guessed at: two nodes sharing a name give no way to say
// which of them moved where.
const uniquePositions = (nodes: readonly SnapshotNode[]): Map<string, number> => {
  const counts = new Map<string, number>();
  const positions = new Map<string, number>();
  for (const node of nodes) {
    const label = labelOf(node);
    if (!label || !node.rect) continue;
    counts.set(label, (counts.get(label) ?? 0) + 1);
    positions.set(label, node.rect.y);
  }
  for (const [label, count] of counts) if (count > 1) positions.delete(label);
  return positions;
};

// How far the page moved between two snapshots, by matching nodes on their
// labels. Median rather than mean: a sticky header and a fixed toolbar stay put
// while the content travels, and a mean splits the difference between those two
// populations and reports a page half-scrolled.
//
// This exists because "the scrolling viewport did not grow" has two causes and
// only one of them is the bug. Safari refusing to collapse its toolbar is the
// one under test; a scroll gesture that never landed produces the identical
// reading and means the run measured nothing. The first device run to get this
// far could not tell them apart.
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
  // Under three anchors the median is one or two nodes' worth of luck.
  if (deltas.length < 3) return null;
  deltas.sort((a, b) => a - b);
  const mid = Math.floor(deltas.length / 2);
  return deltas.length % 2 === 0 ? (deltas[mid - 1]! + deltas[mid]!) / 2 : deltas[mid]!;
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

export const describeNode = (node: SnapshotNode): string => {
  const rect = node.rect
    ? ` x=${Math.round(node.rect.x)} y=${Math.round(node.rect.y)} w=${Math.round(node.rect.width)} h=${Math.round(node.rect.height)}`
    : "";
  return `${node.type ?? "node"} ref=@${node.ref}${rect} hittable=${String(node.hittable)} label=${JSON.stringify(
    node.label ?? node.value ?? "",
  )}`;
};
