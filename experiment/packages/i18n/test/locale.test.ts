import { Effect } from "effect";
import { describe, expect, it } from "vitest";

import {
  CurrentLocale,
  CurrentTranslator,
  negotiateLocale,
} from "../src/locale.js";

describe("negotiateLocale", () => {
  it("serves English to the en-US browsers the e2e suite runs", () => {
    expect(negotiateLocale("en-US,en;q=0.9")).toBe("en");
    expect(negotiateLocale("en-US")).toBe("en");
    expect(negotiateLocale("EN-gb")).toBe("en");
  });

  it("serves Polish to a Polish browser", () => {
    expect(negotiateLocale("pl-PL")).toBe("pl");
    expect(negotiateLocale("pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7")).toBe("pl");
  });

  it("falls back to Polish when no language is supported or none is sent", () => {
    expect(negotiateLocale("de")).toBe("pl");
    expect(negotiateLocale(null)).toBe("pl");
    expect(negotiateLocale("")).toBe("pl");
  });

  it("walks the list past unsupported languages", () => {
    expect(negotiateLocale("de-DE,de;q=0.9,en;q=0.8")).toBe("en");
  });

  it("orders by q-value, not by position", () => {
    expect(negotiateLocale("en;q=0.5, pl;q=0.9")).toBe("pl");
    expect(negotiateLocale("pl;q=0.1,en")).toBe("en");
  });

  it("keeps a q=0 language as Django does", () => {
    expect(negotiateLocale("fr;q=1.0, en;q=0")).toBe("en");
  });

  it("stops at a wildcard and uses the default", () => {
    expect(negotiateLocale("*, en")).toBe("pl");
    expect(negotiateLocale("de, *;q=0.5, en;q=0.1")).toBe("pl");
  });

  it("ignores the whole header when any part is malformed", () => {
    expect(negotiateLocale("en-US;q=abc")).toBe("pl");
    expect(negotiateLocale("en;q=2")).toBe("pl");
    expect(negotiateLocale("en_US")).toBe("pl");
  });

  it("parses only up to the last comma before 500 characters", () => {
    const filler = Array.from({ length: 100 }, () => "de-DE").join(",");
    expect(negotiateLocale(`${filler},en`)).toBe("pl");
    expect(negotiateLocale(`en,${filler}`)).toBe("en");
    expect(negotiateLocale(`en-${"x".repeat(600)}`)).toBe("pl");
  });
});

describe("CurrentLocale", () => {
  it("hands request code a translator for the provided locale", () => {
    const greeting = Effect.gen(function* greet() {
      const { t } = yield* CurrentTranslator;

      return t("Enrollment Open");
    });

    expect(
      Effect.runSync(greeting.pipe(Effect.provideService(CurrentLocale, "pl")))
    ).toBe("Zapisy otwarte");
    expect(
      Effect.runSync(greeting.pipe(Effect.provideService(CurrentLocale, "en")))
    ).toBe("Enrollment Open");
  });
});
