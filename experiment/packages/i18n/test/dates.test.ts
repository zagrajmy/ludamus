import { Option } from "effect";
import { describe, expect, it } from "vitest";

import {
  dateLeaf,
  formatDate,
  formatDateRange,
  shortDate,
} from "../src/dates.js";

const FRIDAY_AFTERNOON = "2026-09-04 14:00:00";

const NOW = "2026-10-30 19:18:49.274130";

describe("event page header", () => {
  it("prints each endpoint as short_date plus |time:'G:i', the Fri Sep 4, 16:00 the spec matches", () => {
    const endpoint = (value: string) =>
      `${shortDate("en", value)}, ${formatDate({ format: "G:i", locale: "en", value })}`;

    expect(endpoint(FRIDAY_AFTERNOON)).toBe("Fri Sep 4, 16:00");
    expect(endpoint("2026-09-05 18:00:00")).toBe("Sat Sep 5, 20:00");
  });

  it("puts the Polish short date day first with a lowercase month", () => {
    expect(shortDate("pl", FRIDAY_AFTERNOON)).toBe("Pt 4 wrz");
  });

  it("writes the datetime attribute as |date:'c' in Warsaw time", () => {
    expect(
      formatDate({ format: "c", locale: "en", value: FRIDAY_AFTERNOON })
    ).toBe("2026-09-04T16:00:00+02:00");
    expect(
      formatDate({ format: "c", locale: "pl", value: "2026-12-24 23:30:00" })
    ).toBe("2026-12-25T00:30:00+01:00");
    expect(
      formatDate({
        format: "c",
        locale: "en",
        value: "2026-01-03 23:00:07.123456",
      })
    ).toBe("2026-01-04T00:00:07.123456+01:00");
  });

  it("renders the single-day line |date:'l, j E' with the Polish genitive month", () => {
    expect(
      formatDate({ format: "l, j E", locale: "pl", value: FRIDAY_AFTERNOON })
    ).toBe("Piątek, 4 września");
    expect(
      formatDate({ format: "l, j E", locale: "en", value: FRIDAY_AFTERNOON })
    ).toBe("Friday, 4 September");
    expect(
      formatDate({ format: "l, j F", locale: "pl", value: FRIDAY_AFTERNOON })
    ).toBe("Piątek, 4 Wrzesień");
  });
});

describe("formatDate", () => {
  it("accepts ISO strings with an offset as the same instant", () => {
    expect(
      formatDate({
        format: "H:i",
        locale: "en",
        value: "2026-09-04T16:00:00+02:00",
      })
    ).toBe("16:00");
    expect(
      formatDate({ format: "H:i", locale: "en", value: "2026-09-04T14:00:00Z" })
    ).toBe("16:00");
  });

  it("crosses the spring DST change at 01:00 UTC", () => {
    expect(
      formatDate({ format: "c T", locale: "en", value: "2026-03-29 00:30:00" })
    ).toBe("2026-03-29T01:30:00+01:00 CET");
    expect(
      formatDate({ format: "c T", locale: "en", value: "2026-03-29 01:30:00" })
    ).toBe("2026-03-29T03:30:00+02:00 CEST");
  });

  it("prints Django's English TIME_FORMAT with noon and midnight", () => {
    const time = (value: string) =>
      formatDate({ format: "TIME_FORMAT", locale: "en", value });

    expect(time("2026-01-04 11:00:00")).toBe("noon");
    expect(time("2026-01-03 23:00:00")).toBe("midnight");
    expect(time("2026-01-04 12:05:00")).toBe("1:05 p.m.");
    expect(time("2026-01-04 08:00:00")).toBe("9 a.m.");
    expect(
      formatDate({ format: "P", locale: "pl", value: "2026-01-04 12:05:00" })
    ).toBe("1:05 po południu");
  });

  it("resolves the named locale formats", () => {
    expect(
      formatDate({
        format: "DATETIME_FORMAT",
        locale: "en",
        value: FRIDAY_AFTERNOON,
      })
    ).toBe("Sept. 4, 2026, 4 p.m.");
    expect(
      formatDate({
        format: "DATETIME_FORMAT",
        locale: "pl",
        value: FRIDAY_AFTERNOON,
      })
    ).toBe("4 września 2026 16:00");
    expect(
      formatDate({
        format: "SHORT_DATETIME_FORMAT",
        locale: "pl",
        value: FRIDAY_AFTERNOON,
      })
    ).toBe("04-09-2026  16:00");
  });

  it("keeps backslash-escaped letters literal", () => {
    expect(
      formatDate({
        format: "Y-m-d\\TH:i",
        locale: "en",
        value: FRIDAY_AFTERNOON,
      })
    ).toBe("2026-09-04T16:00");
  });

  it("names every month and weekday as Django's catalogs do", () => {
    const months = Array.from({ length: 12 }, (_, index) => {
      const value = `2026-${String(index + 1).padStart(2, "0")}-04 14:00:00`;

      return formatDate({ format: "F|E|N|M|b|D|l", locale: "pl", value });
    });

    expect(months[0]).toBe("Styczeń|stycznia|Sty.|Sty|sty|Nd|Niedziela");
    expect(months[4]).toBe("Maj|maja|Maj|Maj|maj|Pon|Poniedziałek");
    expect(months[9]).toBe(
      "Październik|października|Paź.|Paź|paź|Nd|Niedziela"
    );
    expect(months[11]).toBe("Grudzień|grudnia|Gru|Gru|gru|Pt|Piątek");
    expect(
      formatDate({
        format: "F|E|N|M|b|D|l",
        locale: "en",
        value: FRIDAY_AFTERNOON,
      })
    ).toBe("September|September|Sept.|Sep|sep|Fri|Friday");
  });

  it("echoes input it cannot read instead of inventing a date", () => {
    expect(formatDate({ format: "c", locale: "en", value: "not a date" })).toBe(
      "not a date"
    );
    expect(
      formatDate({ format: "c", locale: "en", value: "2026-02-30 10:00:00" })
    ).toBe("2026-02-30 10:00:00");
  });
});

describe("formatDateRange", () => {
  it("drops the repeated date of a same-day range", () => {
    expect(
      formatDateRange({
        end: "2026-09-04 18:00:00",
        locale: "en",
        now: NOW,
        start: FRIDAY_AFTERNOON,
      })
    ).toBe("Sep 4, 4 p.m. – 8 p.m.");
    expect(
      formatDateRange({
        end: "2026-09-04 18:00:00",
        locale: "pl",
        now: NOW,
        start: FRIDAY_AFTERNOON,
      })
    ).toBe("4 wrz, 16:00 – 20:00");
  });

  it("names both dates of a multi-day range", () => {
    expect(
      formatDateRange({
        end: "2026-09-05 18:00:00",
        locale: "en",
        now: NOW,
        start: FRIDAY_AFTERNOON,
      })
    ).toBe("Sep 4, 4 p.m. – Sep 5, 8 p.m.");
  });

  it("adds the year outside the current one", () => {
    const harvest = {
      end: "2031-11-01 17:00:00",
      now: NOW,
      start: "2031-10-30 09:00:00",
    };

    expect(formatDateRange({ locale: "en", ...harvest })).toBe(
      "Oct 30, 2031, 10 a.m. – Nov 1, 2031, 6 p.m."
    );
    expect(formatDateRange({ locale: "pl", ...harvest })).toBe(
      "30 paź 2031, 10:00 – 1 lis 2031, 18:00"
    );
  });
});

describe("dateLeaf", () => {
  it("lays a month-crossing range out like the feed card spec reads it", () => {
    expect(
      dateLeaf({
        end: "2031-11-01 17:00:00",
        locale: "en",
        now: NOW,
        start: "2031-10-30 09:00:00",
      })
    ).toEqual(
      Option.some({
        band: "oct–nov",
        bandIsLong: true,
        datetime: "2031-10-30T10:00:00+01:00",
        day: "30–1",
        hour: "10:00",
        isOngoing: false,
        isRange: true,
        isSunday: false,
        isToday: false,
        label: "Oct 30, 2031, 10 a.m. – Nov 1, 2031, 6 p.m.",
        weekday: "Thu–Sat",
      })
    );
  });

  it("carries the year in the band of a single day outside this year", () => {
    expect(
      dateLeaf({ locale: "pl", now: NOW, start: "2031-11-09 12:00:00" })
    ).toEqual(
      Option.some({
        band: "lis 2031",
        bandIsLong: true,
        datetime: "2031-11-09T13:00:00+01:00",
        day: "9",
        hour: "13:00",
        isOngoing: false,
        isRange: false,
        isSunday: true,
        isToday: false,
        label: "9 lis 2031, 13:00",
        weekday: "Nd",
      })
    );
  });

  it("counts the small hours towards the evening before", () => {
    const lateNight = dateLeaf({
      end: "2026-11-04 00:30:00",
      locale: "en",
      now: NOW,
      start: "2026-11-03 18:00:00",
    });

    expect(
      Option.map(lateNight, (leaf) => [leaf.day, leaf.weekday, leaf.isRange])
    ).toEqual(Option.some(["3", "Tue", false]));
  });

  it("says ongoing and today in the reader's language", () => {
    const running = dateLeaf({
      end: "2026-11-01 18:00:00",
      locale: "pl",
      now: NOW,
      start: "2026-10-29 08:00:00",
    });

    const tonight = dateLeaf({
      locale: "en",
      now: NOW,
      start: "2026-10-30 20:00:00",
    });

    expect(
      Option.map(running, (leaf) => [
        leaf.hour,
        leaf.isOngoing,
        leaf.bandIsLong,
      ])
    ).toEqual(Option.some(["trwa", true, true]));
    expect(
      Option.map(tonight, (leaf) => [leaf.weekday, leaf.isToday, leaf.band])
    ).toEqual(Option.some(["today", true, "oct"]));
  });

  it("has no leaf for a start it cannot read", () => {
    expect(dateLeaf({ locale: "en", now: NOW, start: "soon" })).toEqual(
      Option.none()
    );
  });
});
