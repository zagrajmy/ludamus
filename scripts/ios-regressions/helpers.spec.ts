import type { CaptureSnapshotResult, SnapshotNode } from "agent-device";

import { describe, expect, test } from "bun:test";

import type { Rect } from "./snapshot";

import { decodeEntities } from "./page";
import {
  centreOnScreen,
  collapse,
  contentEnd,
  describeNode,
  labelOf,
  lowestNodes,
  matchesScopeLabel,
  medianShift,
  pollUntil,
  scrollerViewport,
  viewportOf,
} from "./snapshot";

const screen = { x: 0, y: 0, width: 402, height: 874 };
const rect = (y: number) => ({ x: 100, y, width: 40, height: 20 });
// NOTE: the runner's node and snapshot types carry ~20 required fields these
// pure helpers never read; the cast keeps a fixture to the fields under test.
const node = (fields: Partial<SnapshotNode>): SnapshotNode =>
  ({ ref: "1", index: 0, ...fields }) as SnapshotNode;
const tree = (nodes: SnapshotNode[]): CaptureSnapshotResult =>
  ({ nodes, truncated: false }) as CaptureSnapshotResult;

describe("collapse", () => {
  test("squeezes whitespace runs the way an accessibility engine does", () => {
    expect(collapse("  Jump   to\n  time  ")).toBe("Jump to time");
  });

  test("leaves an already normal name alone", () => {
    expect(collapse("Close")).toBe("Close");
  });
});

describe("labelOf", () => {
  test("prefers the label and normalizes it", () => {
    expect(labelOf(node({ label: " Open  details " }))).toBe("Open details");
  });

  test("falls back to the value, then to an empty string", () => {
    expect(labelOf(node({ value: "42" }))).toBe("42");
    expect(labelOf(node({}))).toBe("");
  });
});

describe("matchesScopeLabel", () => {
  test("accepts the bare name and the name with the runner's role suffix", () => {
    expect(matchesScopeLabel("Jump to time", "Jump to time")).toBe(true);
    expect(matchesScopeLabel("Jump to time, navigation", "Jump to time")).toBe(true);
  });

  test("rejects a longer name that merely starts with the scope", () => {
    expect(matchesScopeLabel("Jump to timeline", "Jump to time")).toBe(false);
    expect(matchesScopeLabel("", "Jump to time")).toBe(false);
  });
});

describe("centreOnScreen", () => {
  test("accepts a rect centred clear of Safari's chrome", () => {
    expect(centreOnScreen(rect(400), screen)).toBe(true);
  });

  test("rejects rects centred inside the top and bottom chrome bands", () => {
    expect(centreOnScreen(rect(0), screen)).toBe(false);
    expect(centreOnScreen(rect(860), screen)).toBe(false);
  });
});

describe("viewportOf", () => {
  test("reads the root node's rect", () => {
    expect(viewportOf(tree([node({ rect: screen })]))).toEqual(screen);
  });

  test("falls back to a finite shape when the tree is empty", () => {
    expect(viewportOf(tree([])).width).toBeGreaterThan(0);
  });
});

describe("pollUntil", () => {
  test("returns the first non-null probe result", async () => {
    let calls = 0;
    const result = await pollUntil(async () => (++calls < 3 ? null : "found"), {
      timeoutMs: 1000,
      intervalMs: 1,
    });
    expect(result).toBe("found");
    expect(calls).toBe(3);
  });

  test("probes at least once and concludes null only after the window", async () => {
    let calls = 0;
    const started = Date.now();
    const result = await pollUntil(
      async () => {
        calls += 1;
        return null;
      },
      { timeoutMs: 50, intervalMs: 10 },
    );
    expect(result).toBeNull();
    expect(calls).toBeGreaterThan(1);
    expect(Date.now() - started).toBeGreaterThanOrEqual(50);
  });

  // The budgets in mobile.yml are all sized on this: a window bounds how many
  // more probes start, never how long one may run.
  test("accepts a result that arrives after the window closed", async () => {
    const result = await pollUntil(
      async () => {
        await Bun.sleep(30);
        return "late";
      },
      { timeoutMs: 5, intervalMs: 1 },
    );
    expect(result).toBe("late");
  });

  test("lets a throwing probe abort the poll", async () => {
    const boom = pollUntil(
      async () => {
        throw new Error("device in use");
      },
      { timeoutMs: 1000, intervalMs: 1 },
    );
    await expect(boom).rejects.toThrow("device in use");
  });
});

describe("decodeEntities", () => {
  test("decodes an escaped ampersand the way an aria-label serves it", () => {
    expect(decodeEntities("Open details for Research &amp; Development")).toBe(
      "Open details for Research & Development",
    );
  });

  test("does not double-unescape a served entity", () => {
    expect(decodeEntities("&amp;lt;script&amp;gt;")).toBe("&lt;script&gt;");
  });
});

describe("describeNode", () => {
  test("renders the fields a failure dump needs", () => {
    expect(
      describeNode(node({ ref: "7", type: "link", rect: rect(400), label: "Close" })),
    ).toContain('ref=@7 x=100 y=400 w=40 h=20 hittable=undefined label="Close"');
  });
});

describe("scrollerViewport", () => {
  // Verbatim from the device run on c6a77138, which is the only reason the
  // right node is knowable: four scroll views spanning the whole 874pt screen,
  // and one inset 62pt top and bottom by Safari's chrome.
  const SCREEN: Rect = { x: 0, y: 0, width: 402, height: 874 };
  const bar = (y: number, height: number): SnapshotNode =>
    node({ label: "Vertical scroll bar, 1 page", rect: { x: 396, y, width: 6, height } });
  const observed = [bar(0, 874), bar(0, 874), bar(0, 874), bar(0, 874), bar(62, 750)];

  test("passes over the scroll views that span the whole screen", () => {
    expect(scrollerViewport(observed, SCREEN)).toEqual({ x: 396, y: 62, width: 6, height: 750 });
  });

  test("takes the tallest of several inset scrollers, which is the outermost", () => {
    const nested = [bar(62, 750), bar(120, 400), bar(200, 90)];
    expect(scrollerViewport(nested, SCREEN)?.height).toBe(750);
  });

  test("reports nothing rather than guessing when every scroller spans the screen", () => {
    expect(scrollerViewport([bar(0, 874), bar(0, 874)], SCREEN)).toBeNull();
  });

  test("ignores nodes that are not scroll indicators, and ones with no rect", () => {
    const noise = [node({ label: "Log in" }), node({ label: "Vertical scroll bar, 1 page" })];
    expect(scrollerViewport([...noise, bar(62, 750)], SCREEN)?.height).toBe(750);
  });
});

describe("medianShift", () => {
  // Labelled nodes at known heights, so a fixture reads as a page position.
  const at = (label: string, y: number) => node({ label, rect: rect(y) });

  test("reports how far the page travelled between two snapshots", () => {
    const before = [at("Card A", 100), at("Card B", 300), at("Card C", 500)];
    const after = [at("Card A", -350), at("Card B", -150), at("Card C", 50)];
    expect(medianShift(before, after)).toBe(-450);
  });

  test("is not dragged off by the sticky elements that stay put", () => {
    // The header and the toolbar do not move; three cards do. A mean would
    // report -270 and read as a page half-scrolled.
    const before = [
      at("Filters", 70),
      at("Jump to time", 90),
      ...[100, 300, 500].map((y, i) => at(`Card ${i}`, y)),
    ];
    const after = [
      at("Filters", 70),
      at("Jump to time", 90),
      ...[-350, -150, 50].map((y, i) => at(`Card ${i}`, y)),
    ];
    expect(medianShift(before, after)).toBe(-450);
  });

  test("reports nothing rather than a number when too few nodes match", () => {
    expect(
      medianShift([at("Card A", 100), at("Card B", 200)], [at("Card A", 0), at("Card B", 100)]),
    ).toBeNull();
    expect(medianShift([at("Card A", 100)], [at("Card Z", 0)])).toBeNull();
  });

  test("drops labels that occur more than once, which cannot be matched up", () => {
    // Two "Close" buttons give no way to say which became which, so they are
    // not anchors; the three cards still are.
    const before = [
      at("Close", 10),
      at("Close", 800),
      ...[100, 300, 500].map((y, i) => at(`Card ${i}`, y)),
    ];
    const after = [
      at("Close", 800),
      at("Close", 10),
      ...[0, 200, 400].map((y, i) => at(`Card ${i}`, y)),
    ];
    expect(medianShift(before, after)).toBe(-100);
  });

  test("ignores nodes with no rect and nodes with no label", () => {
    const before = [
      node({ label: "Card A" }),
      at("Card B", 300),
      at("Card C", 500),
      at("Card D", 700),
      node({ rect: rect(0) }),
    ];
    const after = [
      node({ label: "Card A" }),
      at("Card B", 100),
      at("Card C", 300),
      at("Card D", 500),
      node({ rect: rect(9) }),
    ];
    expect(medianShift(before, after)).toBe(-200);
  });

  test("reads a page that did not move as zero, which is the failure it guards", () => {
    const still = [at("Card A", 100), at("Card B", 300), at("Card C", 500)];
    expect(medianShift(still, still)).toBe(0);
  });
});

describe("contentEnd", () => {
  const at = (label: string, y: number, height = 20) =>
    node({ label, rect: { x: 0, y, width: 300, height } });

  test("reports the labelled node that ends lowest", () => {
    const nodes = [at("Card A", 100), at("Card B", 300), at("Terms of Service", 780, 24)];
    expect(contentEnd(nodes)).toEqual({ bottom: 804, label: "Terms of Service" });
  });

  test("passes over the scroll views that span the screen, which end where the screen does", () => {
    // The 874pt container would otherwise win every time, and it says nothing
    // about where the page's content stops.
    const nodes = [
      node({ label: "Vertical scroll bar, 1 page", rect: { x: 0, y: 0, width: 402, height: 874 } }),
      at("Card A", 100),
    ];
    expect(contentEnd(nodes)?.label).toBe("Card A");
  });

  test("ignores unlabelled nodes and nodes with no rect", () => {
    const nodes = [
      node({ rect: { x: 0, y: 0, width: 402, height: 874 } }),
      node({ label: "Card Z" }),
      at("Card A", 100),
    ];
    expect(contentEnd(nodes)).toEqual({ bottom: 120, label: "Card A" });
  });

  test("reports nothing when there is no labelled content", () => {
    expect(contentEnd([node({ rect: { x: 0, y: 0, width: 1, height: 1 } })])).toBeNull();
  });
});

describe("lowestNodes", () => {
  const at = (label: string, y: number) =>
    node({ label, rect: { x: 0, y, width: 300, height: 20 } });

  test("lists the lowest labelled nodes, lowest first, capped", () => {
    const nodes = [
      at("Top", 0),
      at("Middle", 400),
      at("Bottom", 800),
      at("Vertical scroll bar", 0),
    ];
    expect(lowestNodes(nodes, 2)).toBe('800..820 "Bottom"; 400..420 "Middle"');
  });
});
