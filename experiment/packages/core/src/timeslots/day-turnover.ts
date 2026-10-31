import { DateTime, Schema } from "effect";

export const PROGRAMME_DAY_STARTS_AT_HOUR = 6;

export interface DayTurnover {
  readonly hour: number;
}

export const MIDNIGHT: DayTurnover = { hour: 0 };

export const PROGRAMME_DAYS: DayTurnover = {
  hour: PROGRAMME_DAY_STARTS_AT_HOUR,
};

export const LocalDateTime = Schema.Struct({
  instant: Schema.DateTimeUtcFromString,
  wall: Schema.DateTimeUtcFromString,
});

export type LocalDateTime = typeof LocalDateTime.Type;

export const LocalWindow = Schema.Struct({
  end: LocalDateTime,
  start: LocalDateTime,
});

export type LocalWindow = typeof LocalWindow.Type;

export const CivilDate = Schema.String.check(
  Schema.isPattern(/^\d{4}-\d{2}-\d{2}$/u)
);

export type CivilDate = typeof CivilDate.Type;

const DAY_MILLIS = 86_400_000;

export const localize = (options: {
  readonly instant: DateTime.DateTime;
  readonly timeZone: DateTime.TimeZone;
}): LocalDateTime => {
  const zoned = DateTime.makeZonedUnsafe(options.instant, {
    timeZone: options.timeZone,
  });

  const parts = DateTime.toParts(zoned);

  return {
    instant: DateTime.toUtc(zoned),
    wall: DateTime.makeUnsafe({
      day: parts.day,
      hour: parts.hour,
      millisecond: parts.millisecond,
      minute: parts.minute,
      month: parts.month,
      second: parts.second,
      year: parts.year,
    }),
  };
};

export const dateOf = (options: {
  readonly turnover: DayTurnover;
  readonly local: LocalDateTime;
}): CivilDate =>
  DateTime.formatIsoDateUtc(
    DateTime.subtract(options.local.wall, { hours: options.turnover.hour })
  );

const civilParts = (
  day: CivilDate
): {
  readonly year: number;
  readonly month: number;
  readonly day: number;
} => {
  const [year = 0, month = 1, date = 1] = day.split("-").map(Number);

  return { day: date, month, year };
};

const addDays = (day: CivilDate, days: number): CivilDate =>
  DateTime.formatIsoDateUtc(
    DateTime.add(DateTime.makeUnsafe(civilParts(day)), { days })
  );

const daysBetween = (first: CivilDate, last: CivilDate): number =>
  Math.round(
    (DateTime.toEpochMillis(DateTime.makeUnsafe(civilParts(last))) -
      DateTime.toEpochMillis(DateTime.makeUnsafe(civilParts(first)))) /
      DAY_MILLIS
  );

export const opening = (options: {
  readonly turnover: DayTurnover;
  readonly day: CivilDate;
  readonly timeZone: DateTime.TimeZone;
}): LocalDateTime => {
  const parts = { ...civilParts(options.day), hour: options.turnover.hour };

  return {
    instant: DateTime.toUtc(
      DateTime.makeZonedUnsafe(parts, {
        adjustForTimeZone: true,
        disambiguation: "compatible",
        timeZone: options.timeZone,
      })
    ),
    wall: DateTime.makeUnsafe(parts),
  };
};

const laterOf = (first: LocalDateTime, second: LocalDateTime): LocalDateTime =>
  DateTime.isGreaterThan(second.instant, first.instant) ? second : first;

const earlierOf = (
  first: LocalDateTime,
  second: LocalDateTime
): LocalDateTime =>
  DateTime.isLessThan(second.instant, first.instant) ? second : first;

export const turnoverWindows = (options: {
  readonly turnover: DayTurnover;
  readonly start: DateTime.DateTime;
  readonly end: DateTime.DateTime;
  readonly timeZone: DateTime.TimeZone;
}): readonly LocalWindow[] => {
  const { turnover, timeZone } = options;
  const localStart = localize({ instant: options.start, timeZone });
  const localEnd = localize({ instant: options.end, timeZone });
  const firstDate = dateOf({ local: localStart, turnover });
  const lastDate = dateOf({ local: localEnd, turnover });

  if (firstDate === lastDate) {
    return DateTime.isLessThan(localStart.instant, localEnd.instant)
      ? [{ end: localEnd, start: localStart }]
      : [];
  }

  const windows: LocalWindow[] = [];
  const span = daysBetween(firstDate, lastDate);

  for (let offset = 0; offset <= span; offset += 1) {
    const day = addDays(firstDate, offset);
    const start = laterOf(localStart, opening({ day, timeZone, turnover }));

    const end = earlierOf(
      localEnd,
      opening({ day: addDays(day, 1), timeZone, turnover })
    );

    if (DateTime.isLessThan(start.instant, end.instant)) {
      windows.push({ end, start });
    }
  }

  return windows;
};

export const SlotSpan = Schema.Struct({
  endTime: Schema.DateTimeUtcFromString,
  startTime: Schema.DateTimeUtcFromString,
});

export type SlotSpan = typeof SlotSpan.Type;

export const DayOfWindows = Schema.Struct({
  date: CivilDate,
  windows: Schema.Array(LocalWindow),
});

export type DayOfWindows = typeof DayOfWindows.Type;

export const slotWindows = (options: {
  readonly slot: SlotSpan;
  readonly timeZone: DateTime.TimeZone;
}): readonly LocalWindow[] =>
  turnoverWindows({
    end: options.slot.endTime,
    start: options.slot.startTime,
    timeZone: options.timeZone,
    turnover: MIDNIGHT,
  });

export const slotWindowsByLocalDate = (options: {
  readonly slots: readonly SlotSpan[];
  readonly timeZone: DateTime.TimeZone;
}): readonly DayOfWindows[] => {
  const grouped = new Map<CivilDate, LocalWindow[]>();

  for (const slot of options.slots) {
    for (const window of slotWindows({ slot, timeZone: options.timeZone })) {
      const date = dateOf({ local: window.start, turnover: MIDNIGHT });
      grouped.set(date, [...(grouped.get(date) ?? []), window]);
    }
  }

  return [...grouped].map(([date, windows]) => ({ date, windows }));
};
