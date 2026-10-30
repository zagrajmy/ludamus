import { describe, expect, it } from "@effect/vitest";
import { DateTime, Schema } from "effect";
import * as Arbitrary from "effect/Arbitrary";

import {
  MIDNIGHT,
  PROGRAMME_DAYS,
  dateOf,
  localize,
  turnoverWindows,
} from "../src/timeslots/index.js";
import { between } from "./support/arbitraries.js";

const ANCHOR = DateTime.makeUnsafe("2026-03-29T01:00:00Z");

const Interval = Schema.Struct({
  hours: between(0, 1),
  length: between(-4, 160),
  offset: between(-96, 96),
  zone: Schema.Literals([
    "UTC",
    "Europe/Warsaw",
    "America/New_York",
    "Australia/Lord_Howe",
    "America/Havana",
  ]),
});

const decode = (interval: typeof Interval.Type) => {
  const start = DateTime.add(ANCHOR, { minutes: 30 * interval.offset });

  return {
    end: DateTime.add(start, { minutes: 30 * interval.length }),
    start,
    timeZone: DateTime.zoneMakeNamedUnsafe(interval.zone),
    turnover: interval.hours === 0 ? MIDNIGHT : PROGRAMME_DAYS,
  };
};

const intervals = {
  interval: Arbitrary.map(Arbitrary.schema(Interval), decode),
};

const millis = (value: DateTime.DateTime): number =>
  DateTime.toEpochMillis(value);

describe("turnoverWindows", () => {
  it.prop(
    "windows cover the interval exactly, in order, without overlap",
    intervals,
    ({ interval }) => {
      const windows = turnoverWindows(interval);

      const covered = windows.reduce(
        (sum, w) => sum + millis(w.end.instant) - millis(w.start.instant),
        0
      );

      expect(covered).toBe(
        Math.max(0, millis(interval.end) - millis(interval.start))
      );

      for (const [index, window] of windows.entries()) {
        expect(millis(window.start.instant)).toBeLessThan(
          millis(window.end.instant)
        );
        expect(millis(window.start.instant)).toBeGreaterThanOrEqual(
          millis(interval.start)
        );
        expect(millis(window.end.instant)).toBeLessThanOrEqual(
          millis(interval.end)
        );
        const next = windows[index + 1];

        if (next !== undefined) {
          expect(millis(window.end.instant)).toBeLessThanOrEqual(
            millis(next.start.instant)
          );
        }
      }
    }
  );

  it.prop(
    "every window opens on a different programme day",
    intervals,
    ({ interval }) => {
      const days = turnoverWindows(interval).map((window) =>
        dateOf({
          local: localize({
            instant: window.start.instant,
            timeZone: interval.timeZone,
          }),
          turnover: interval.turnover,
        })
      );

      expect(new Set(days).size).toBe(days.length);
    }
  );
});
