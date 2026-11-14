import { describe, expect, it } from "@effect/vitest";
import { DateTime, Schema } from "effect";

import {
  SlotSpan,
  dateOf,
  localize,
  opening,
  slotWindowsByLocalDate,
  turnoverWindows,
} from "../src/timeslots/index.js";
import type { LocalDateTime, LocalWindow } from "../src/timeslots/index.js";
import turnoverCases from "./fixtures/differential/day_turnover.json" with { type: "json" };
import slotCases from "./fixtures/differential/slot_windows_by_local_date.json" with { type: "json" };
import { iso, replay } from "./support/differential.js";
import type { Json } from "./support/differential.js";

const zone = (name: string): DateTime.TimeZone =>
  DateTime.zoneMakeNamedUnsafe(name);

const localJson = (local: LocalDateTime): Json => ({
  utc: iso(local.instant),
  wall: iso(local.wall).slice(0, 19),
});

const windowJson = (window: LocalWindow): Json => ({
  end: localJson(window.end),
  start: localJson(window.start),
});

describe("differential: mills.timeslots", () => {
  it("DayTurnover dates, openings and windows match Python's zoneinfo", () => {
    const mismatches = replay({
      cases: turnoverCases.cases,
      input: Schema.Struct({
        end: Schema.DateTimeUtcFromString,
        hour: Schema.Int,
        start: Schema.DateTimeUtcFromString,
        timeZone: Schema.String,
      }),
      run: ({ start, end, hour, timeZone }) => {
        const turnover = { hour };
        const tz = zone(timeZone);

        const day = dateOf({
          local: localize({ instant: start, timeZone: tz }),
          turnover,
        });

        return {
          dateOfStart: day,
          opening: localJson(opening({ day, timeZone: tz, turnover })),
          windows: turnoverWindows({ end, start, timeZone: tz, turnover }).map(
            windowJson
          ),
        };
      },
    });

    expect(turnoverCases.cases.length).toBeGreaterThan(250);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });

  it("slot_windows_by_local_date groups slots under the same days", () => {
    const mismatches = replay({
      cases: slotCases.cases,
      input: Schema.Struct({
        slots: Schema.Array(SlotSpan),
        timeZone: Schema.String,
      }),
      run: ({ slots, timeZone }) =>
        slotWindowsByLocalDate({ slots, timeZone: zone(timeZone) }).map(
          (day) => ({
            date: day.date,
            windows: day.windows.map(windowJson),
          })
        ),
    });

    expect(slotCases.cases.length).toBeGreaterThan(250);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });
});
