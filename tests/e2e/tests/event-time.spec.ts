import { programmeDate } from "../../../src/ludamus/client/src/event-time";
import { expect, test } from "./helpers/fixtures";

// Pure date arithmetic, so no page: the fold script decides which programme
// days are over from this, and it has to agree with the server's local_date
// (mills/timeslots.py) on the nights the clocks change.
test.describe("programmeDate", () => {
  const warsaw = "Europe/Warsaw";

  test("the small hours belong to the evening before", () => {
    expect(programmeDate(Date.parse("2026-07-11T02:00:00+02:00"), warsaw, 6)).toBe("2026-07-10");
    expect(programmeDate(Date.parse("2026-07-11T06:00:00+02:00"), warsaw, 6)).toBe("2026-07-11");
  });

  test("the spring-forward morning still turns over at the wall-clock hour", () => {
    // 04:30Z is 06:30 CEST, the clocks having jumped from 02:00 to 03:00 that
    // night: only five hours have elapsed since midnight, but the day is open.
    expect(programmeDate(Date.parse("2026-03-29T04:30:00Z"), warsaw, 6)).toBe("2026-03-29");
    expect(programmeDate(Date.parse("2026-03-29T03:30:00Z"), warsaw, 6)).toBe("2026-03-28");
  });

  test("the autumn night gives the evening an extra hour", () => {
    // 04:30Z is 05:30 CET after the clocks went back: seven hours since
    // midnight, yet still before the turnover.
    expect(programmeDate(Date.parse("2026-10-25T04:30:00Z"), warsaw, 6)).toBe("2026-10-24");
  });

  test("a midnight turnover is the calendar date", () => {
    expect(programmeDate(Date.parse("2026-07-11T00:30:00+02:00"), warsaw, 0)).toBe("2026-07-11");
  });
});
