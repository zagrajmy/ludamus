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
