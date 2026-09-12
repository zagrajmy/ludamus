import { describe, expect, it } from "vitest";

import { integer, normalizeMessage } from "../src/limits";

describe("normalizeMessage", () => {
  it("normalizes line endings and preserves internal line breaks", () => {
    expect(normalizeMessage("  hello\r\nworld  ")).toBe("hello\nworld");
  });

  it("rejects messages over 1,000 code points", () => {
    expect(normalizeMessage("🙂".repeat(1_001))).toBeNull();
  });

  it("rejects more than five web links", () => {
    expect(normalizeMessage("https://a.test ".repeat(6))).toBeNull();
  });
});

describe("integer", () => {
  it("accepts only positive safe integers", () => {
    expect(integer(4)).toBe(4);
    expect(integer(0)).toBeNull();
    expect(integer(1.5)).toBeNull();
  });
});
