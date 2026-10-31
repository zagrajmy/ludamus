import type { Location } from "@zagrajmy/core/contracts";
import {
  PROGRAMME_DAYS,
  dateOf,
  localize,
  opening,
  turnoverWindows,
} from "@zagrajmy/core/timeslots/day-turnover";
import { formatDate } from "@zagrajmy/i18n";
import type { Locale } from "@zagrajmy/i18n";
import { DateTime } from "effect";

import type {
  CardDay,
  LedgerDay,
  LedgerHour,
  RoomColumn,
  RoomGrid,
  RoomRow,
  RoomTile,
  ScheduleDay,
} from "../../client/event-page/flags.js";

export const EVENT_TIME_ZONE = "Europe/Warsaw";

export const eventZone = DateTime.zoneMakeNamedUnsafe(EVENT_TIME_ZONE);

const FOLD_MIN_MINUTES = 180;

const HOUR_MILLIS = 3_600_000;

export type Booked = Readonly<{
  end: DateTime.Utc;
  id: number;
  isEnded: boolean;
  location: Location;
  start: DateTime.Utc;
  title: string;
}>;

const millis = (instant: DateTime.DateTime) => DateTime.toEpochMillis(instant);

const utcOf = (epochMillis: number) => DateTime.makeUnsafe(epochMillis);

export const isoOf = (epochMillis: number) =>
  DateTime.formatIso(utcOf(epochMillis));

export const localFormat = (options: {
  readonly at: number;
  readonly format: string;
  readonly locale: Locale;
}) =>
  formatDate({
    format: options.format,
    locale: options.locale,
    value: isoOf(options.at),
  });

const wallParts = (epochMillis: number) =>
  DateTime.toParts(
    DateTime.makeZonedUnsafe(utcOf(epochMillis), { timeZone: eventZone })
  );

const hourFloor = (epochMillis: number) => {
  const parts = wallParts(epochMillis);

  return (
    epochMillis -
    parts.minute * 60_000 -
    parts.second * 1000 -
    parts.millisecond
  );
};

const isRepeatedHour = (epochMillis: number) => {
  const { hour } = wallParts(epochMillis);

  return (
    wallParts(epochMillis - HOUR_MILLIS).hour === hour ||
    wallParts(epochMillis + HOUR_MILLIS).hour === hour
  );
};

const zoneName = (epochMillis: number) =>
  wallParts(epochMillis).hour === wallParts(epochMillis - HOUR_MILLIS).hour
    ? "CET"
    : "CEST";

export const slotKeyOf = (epochMillis: number) =>
  String(Math.floor(epochMillis / 1000));

const dayOf = (options: {
  readonly date: string;
  readonly locale: Locale;
}): ScheduleDay => {
  const opened = millis(
    opening({
      day: options.date,
      timeZone: eventZone,
      turnover: PROGRAMME_DAYS,
    }).instant
  );

  const label = (format: string) =>
    localFormat({ at: opened, format, locale: options.locale });

  return {
    date: options.date,
    dateLabel: label("j F"),
    name: label("l"),
    panelId: `schedule-day-${options.date}`,
    shortName: label("D"),
  };
};

export const programmeDate = (epochMillis: number) =>
  dateOf({
    local: localize({ instant: utcOf(epochMillis), timeZone: eventZone }),
    turnover: PROGRAMME_DAYS,
  });

type Tile = Readonly<{ booked: Booked; end: number; start: number }>;

type Day = Readonly<{ date: string; tiles: readonly Tile[] }>;

const programmeDays = (sessions: readonly Booked[]): readonly Day[] => {
  const byDate = new Map<string, Tile[]>();

  for (const booked of sessions.toSorted(
    (left, right) => millis(left.start) - millis(right.start)
  )) {
    for (const window of turnoverWindows({
      end: booked.end,
      start: booked.start,
      timeZone: eventZone,
      turnover: PROGRAMME_DAYS,
    })) {
      const start = millis(window.start.instant);
      const date = programmeDate(start);
      const tiles = byDate.get(date) ?? [];
      tiles.push({ booked, end: millis(window.end.instant), start });
      byDate.set(date, tiles);
    }
  }

  return [...byDate.keys()]
    .toSorted()
    .map((date) => ({ date, tiles: byDate.get(date) ?? [] }));
};

const clock = (options: {
  readonly at: number;
  readonly locale: Locale;
  readonly zoned: boolean;
}) => {
  const time = localFormat({
    at: options.at,
    format: "H:i",
    locale: options.locale,
  });

  return options.zoned ? `${time} ${zoneName(options.at)}` : time;
};

const tileClocks = (options: {
  readonly end: number;
  readonly locale: Locale;
  readonly start: number;
}) => {
  const zoned =
    DateTime.toParts(
      DateTime.makeZonedUnsafe(utcOf(options.start), { timeZone: eventZone })
    ).hour !== wallParts(options.start).hour ||
    zoneName(options.start) !== zoneName(options.end);

  return {
    endClock: clock({ at: options.end, locale: options.locale, zoned }),
    startClock: clock({ at: options.start, locale: options.locale, zoned }),
  };
};

export const buildLedger = (options: {
  readonly locale: Locale;
  readonly sessions: readonly Booked[];
}): readonly LedgerDay[] =>
  programmeDays(options.sessions).map((day) => {
    const byHour = new Map<number, Tile[]>();

    for (const tile of day.tiles) {
      const hour = hourFloor(tile.start);
      const tiles = byHour.get(hour) ?? [];
      tiles.push(tile);
      byHour.set(hour, tiles);
    }

    const hours: LedgerHour[] = [...byHour.keys()]
      .toSorted((left, right) => left - right)
      .map((hour) => {
        const repeated = isRepeatedHour(hour);

        const time = localFormat({
          at: hour,
          format: "H:i",
          locale: options.locale,
        });

        return {
          clock: time,
          hourLabel: localFormat({
            at: hour,
            format: "H",
            locale: options.locale,
          }),
          repeatedZone: repeated ? zoneName(hour) : "",
          slotKey: slotKeyOf(hour),
          startsAt: hour,
          tiles: (byHour.get(hour) ?? []).map((tile) => ({
            ...tileClocks({
              end: tile.end,
              locale: options.locale,
              start: tile.start,
            }),
            endIso: localFormat({
              at: tile.end,
              format: "c",
              locale: options.locale,
            }),
            endsAt: tile.end,
            sessionId: tile.booked.id,
            startIso: localFormat({
              at: tile.start,
              format: "c",
              locale: options.locale,
            }),
            startsAt: tile.start,
          })),
        };
      });

    return {
      day: dayOf({ date: day.date, locale: options.locale }),
      endsAt: Math.max(...day.tiles.map((tile) => tile.end)),
      hours,
      startsAt: Math.min(...day.tiles.map((tile) => tile.start)),
    };
  });

export const buildCardDays = (options: {
  readonly locale: Locale;
  readonly sessions: readonly Booked[];
}): readonly CardDay[] => {
  const byStart = new Map<number, Booked[]>();

  for (const booked of options.sessions) {
    const start = millis(booked.start);
    const group = byStart.get(start) ?? [];
    group.push(booked);
    byStart.set(start, group);
  }

  const starts = [...byStart.keys()].toSorted((left, right) => left - right);
  const dates = [...new Set(starts.map(programmeDate))];
  const isSingleDay = dates.length === 1;

  return dates.map((date) => ({
    day: dayOf({ date, locale: options.locale }),
    slots: starts
      .filter((start) => programmeDate(start) === date)
      .map((start) => ({
        dateLabel: isSingleDay
          ? `${localFormat({ at: start, format: "l, j F", locale: options.locale })} –`
          : "",
        hour: localFormat({ at: start, format: "H:i", locale: options.locale }),
        sessionIds: (byStart.get(start) ?? []).map((booked) => booked.id),
        startsAt: start,
      })),
  }));
};

type RoomKey = Readonly<{
  location: Location;
  value: string;
}>;

const compareKeys = (left: Location, right: Location): number => {
  if (left.programmeOrder !== right.programmeOrder) {
    return left.programmeOrder - right.programmeOrder;
  }

  const length = Math.min(left.sortPath.length, right.sortPath.length);

  for (let index = 0; index < length; index += 1) {
    const one = left.sortPath[index];
    const other = right.sortPath[index];

    if (one !== undefined && other !== undefined) {
      if (one.order !== other.order) {
        return one.order - other.order;
      }

      if (one.name !== other.name) {
        return one.name < other.name ? -1 : 1;
      }

      if (one.id !== other.id) {
        return one.id - other.id;
      }
    }
  }

  if (left.sortPath.length !== right.sortPath.length) {
    return left.sortPath.length - right.sortPath.length;
  }

  if (left.spaceId !== right.spaceId) {
    return left.spaceId - right.spaceId;
  }

  return left.parentId - right.parentId;
};

const keyOf = (location: Location) =>
  `${location.programmeOrder}|${location.spaceId}|${location.parentId}|${location.spaceName}|${location.parentName}`;

type RowWindow = Readonly<{
  dayIndex: number;
  end: number;
  hourMark: number;
  isFold: boolean;
  start: number;
}>;

const rowWindows = (options: {
  readonly dayIndex: number;
  readonly firstHour: number;
  readonly tiles: readonly Tile[];
}): readonly RowWindow[] => {
  const dayEnd = Math.max(...options.tiles.map((tile) => tile.end));
  const marks = [options.firstHour];

  while ((marks.at(-1) ?? dayEnd) < dayEnd) {
    marks.push((marks.at(-1) ?? 0) + HOUR_MILLIS);
  }

  const cuts = [
    ...new Set(options.tiles.flatMap((tile) => [tile.start, tile.end])),
  ];

  return marks.slice(0, -1).flatMap((mark, index) => {
    const next = marks[index + 1] ?? mark;

    const inside = cuts
      .filter((cut) => mark < cut && cut < next)
      .toSorted((left, right) => left - right);

    const edges = [mark, ...inside, next];

    return edges.slice(0, -1).map((start, edge) => ({
      dayIndex: options.dayIndex,
      end: edges[edge + 1] ?? next,
      hourMark: mark,
      isFold: false,
      start,
    }));
  });
};

type Booking = Readonly<{ booked: Booked; end: number; start: number }>;

const foldLulls = (
  windows: readonly RowWindow[],
  bookings: readonly Booking[]
): readonly RowWindow[] => {
  const starts = new Set(bookings.map((booking) => booking.start));
  const ends = new Set(bookings.map((booking) => booking.end));

  const busyHours = new Set(
    windows
      .filter((window) => starts.has(window.start) || ends.has(window.end))
      .map((window) => window.hourMark)
  );

  const folded: RowWindow[] = [];
  let run: RowWindow[] = [];

  const flush = () => {
    const minutes = run.reduce(
      (sum, window) => sum + (window.end - window.start) / 60_000,
      0
    );

    const first = run[0];
    const last = run.at(-1);

    if (first !== undefined && last !== undefined) {
      if (minutes < FOLD_MIN_MINUTES) {
        folded.push(...run);
      } else {
        folded.push({ ...first, end: last.end, isFold: true });
      }
    }

    run = [];
  };

  for (const window of windows) {
    if (busyHours.has(window.hourMark)) {
      flush();
      folded.push(window);
    } else {
      run.push(window);
    }
  }

  flush();

  return folded;
};

type Placed = Readonly<{
  booking: Booking;
  column: number;
  laneCount: number;
  laneIndex: number;
  rowStart: number;
  span: number;
}>;

const titleKey = (booking: Booking) => booking.booked.title.toLowerCase();

const placeConflicts = (positioned: readonly Placed[]): readonly Placed[] => {
  const byColumn = new Map<number, Placed[]>();

  for (const item of positioned) {
    byColumn.set(item.column, [...(byColumn.get(item.column) ?? []), item]);
  }

  const placed: Placed[] = [];

  for (const items of byColumn.values()) {
    const ordered = items.toSorted(
      (left, right) =>
        left.booking.start - right.booking.start ||
        left.booking.end - right.booking.end ||
        titleKey(left.booking).localeCompare(titleKey(right.booking)) ||
        left.booking.booked.id - right.booking.booked.id
    );

    const components: Placed[][] = [];
    let component: Placed[] = [];
    let componentEnd = 0;

    for (const item of ordered) {
      if (component.length > 0 && item.rowStart >= componentEnd) {
        components.push(component);
        component = [];
      }

      component.push(item);
      componentEnd = Math.max(componentEnd, item.rowStart + item.span);
    }

    if (component.length > 0) {
      components.push(component);
    }

    for (const conflict of components) {
      const laneEnds: number[] = [];

      const assigned = conflict.map((item) => {
        const free = laneEnds.findIndex((end) => end <= item.rowStart);
        const laneIndex = free === -1 ? laneEnds.length : free;
        laneEnds[laneIndex] = item.rowStart + item.span;

        return { ...item, laneIndex };
      });

      placed.push(
        ...assigned.map((item) => ({ ...item, laneCount: laneEnds.length }))
      );
    }
  }

  return placed.toSorted(
    (left, right) =>
      left.rowStart - right.rowStart ||
      left.column - right.column ||
      left.booking.start - right.booking.start ||
      left.booking.end - right.booking.end ||
      left.laneIndex - right.laneIndex ||
      titleKey(left.booking).localeCompare(titleKey(right.booking)) ||
      left.booking.booked.id - right.booking.booked.id
  );
};

const roomColumns = (keys: readonly RoomKey[]): readonly RoomColumn[] => {
  let previous: string | undefined = undefined;

  return keys.map(({ location }) => {
    const groupKey = location.parentId === 0 ? "" : String(location.parentId);

    const column = {
      group: location.parentName,
      groupKey,
      name: location.spaceName,
      startsGroup: groupKey !== previous,
    };

    previous = groupKey;

    return column;
  });
};

export const buildRoomGrid = (options: {
  readonly locale: Locale;
  readonly sessions: readonly Booked[];
}): RoomGrid => {
  const days = programmeDays(options.sessions);

  const keys = [
    ...new Map(
      options.sessions.map((booked) => [
        keyOf(booked.location),
        { location: booked.location, value: keyOf(booked.location) },
      ])
    ).values(),
  ].toSorted((left, right) => compareKeys(left.location, right.location));

  const columnOf = new Map(keys.map((key, index) => [key.value, index + 1]));

  const bookings: readonly Booking[] = options.sessions.map((booked) => ({
    booked,
    end: millis(booked.end),
    start: millis(booked.start),
  }));

  const windows: RowWindow[] = [];
  const headings = new Map<number, number>();

  for (const [dayIndex, day] of days.entries()) {
    if (dayIndex > 0) {
      headings.set(windows.length, dayIndex);
      windows.push({
        dayIndex,
        end: 0,
        hourMark: -1,
        isFold: false,
        start: -1,
      });
    }

    const firstHour = hourFloor(
      Math.min(...day.tiles.map((tile) => tile.start))
    );

    windows.push(
      ...foldLulls(
        rowWindows({ dayIndex, firstHour, tiles: day.tiles }),
        bookings
      )
    );
  }

  const positioned: Placed[] = bookings.flatMap((booking) => {
    const covered = windows.flatMap((window, index) =>
      window.start >= 0 &&
      window.start < booking.end &&
      window.end > booking.start
        ? [index]
        : []
    );

    const first = covered[0];
    const last = covered.at(-1);

    return first === undefined || last === undefined
      ? []
      : [
          {
            booking,
            column: columnOf.get(keyOf(booking.booked.location)) ?? 1,
            laneCount: 1,
            laneIndex: 0,
            rowStart: first + 1,
            span: last - first + 1,
          },
        ];
  });

  const placed = placeConflicts(positioned);
  const opened = new Set<string>();

  const rows: RoomRow[] = windows.map((window, index) => {
    const headingDay = headings.get(index);
    const dayFor = days[window.dayIndex];

    if (headingDay !== undefined && dayFor !== undefined) {
      return {
        _tag: "DayHeading",
        day: dayOf({ date: dayFor.date, locale: options.locale }),
        dayIndex: headingDay,
      };
    }

    const slotKey = slotKeyOf(window.hourMark);

    const tiles: RoomTile[] = placed
      .filter((item) => item.rowStart === index + 1)
      .map((item) => ({
        ...tileClocks({
          end: item.booking.end,
          locale: options.locale,
          start: item.booking.start,
        }),
        column: item.column,
        endIso: localFormat({
          at: item.booking.end,
          format: "c",
          locale: options.locale,
        }),
        endsAt: item.booking.end,
        laneCount: item.laneCount,
        laneIndex: item.laneIndex,
        sessionId: item.booking.booked.id,
        slotKey,
        span: item.span,
        startIso: localFormat({
          at: item.booking.start,
          format: "c",
          locale: options.locale,
        }),
        startsAt: item.booking.start,
      }));

    const opensSlot = tiles.length > 0 && !opened.has(slotKey);

    if (tiles.length > 0) {
      opened.add(slotKey);
    }

    const minutes = Math.max(
      1,
      Math.round((window.end - window.start) / 60_000)
    );

    return {
      _tag: "Time",
      clock: localFormat({
        at: window.start,
        format: "H:i",
        locale: options.locale,
      }),
      dayIndex: window.dayIndex,
      endIso: localFormat({
        at: window.end,
        format: "c",
        locale: options.locale,
      }),
      endsAt: window.end,
      foldUntil: localFormat({
        at: window.end,
        format: "H:i",
        locale: options.locale,
      }),
      isCut: window.start !== window.hourMark,
      isFold: window.isFold,
      minutes,
      opensSlot,
      repeatedZone: isRepeatedHour(window.start) ? zoneName(window.start) : "",
      slotKey,
      startIso: localFormat({
        at: window.start,
        format: "c",
        locale: options.locale,
      }),
      startsAt: window.start,
      tiles,
    };
  });

  return {
    columns: roomColumns(keys),
    days: days.map((day) => dayOf({ date: day.date, locale: options.locale })),
    rows,
  };
};
