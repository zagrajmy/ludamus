import type { CaptureSnapshotResult, SnapshotNode } from "agent-device";

import { describe, expect, test } from "bun:test";

import {
  centreOnScreen,
  collapse,
  describeNode,
  labelOf,
  matchesScopeLabel,
  pollUntil,
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

  test("lets a throwing probe abort the poll", () => {
    const boom = pollUntil(
      async () => {
        throw new Error("device in use");
      },
      { timeoutMs: 1000, intervalMs: 1 },
    );
    expect(boom).rejects.toThrow("device in use");
  });
});

describe("describeNode", () => {
  test("renders the fields a failure dump needs", () => {
    expect(
      describeNode(node({ ref: "7", type: "link", rect: rect(400), label: "Close" })),
    ).toContain('ref=@7 x=100 y=400 w=40 h=20 hittable=undefined label="Close"');
  });
});
