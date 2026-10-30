import { DateTime, Option, Schema } from "effect";

import type { Locale } from "./locale-schema.js";
import { translator } from "./translator.js";

interface LocalDateTime {
  readonly year: number;
  readonly month: number;
  readonly day: number;
  readonly weekDay: number;
  readonly hour: number;
  readonly minute: number;
  readonly second: number;
  readonly microsecond: number;
  readonly offsetMinutes: number;
  readonly epochMillis: number;
}

interface LocaleNames {
  readonly months: ReadonlyArray<string>;
  readonly monthsGenitive: ReadonlyArray<string>;
  readonly monthsAbbreviated: ReadonlyArray<string>;
  readonly monthsAssociatedPress: ReadonlyArray<string>;
  readonly weekdays: ReadonlyArray<string>;
  readonly weekdaysAbbreviated: ReadonlyArray<string>;
  readonly beforeNoon: string;
  readonly afterNoon: string;
  readonly beforeNoonUpper: string;
  readonly afterNoonUpper: string;
  readonly midnight: string;
  readonly noon: string;
}

const ENGLISH_MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

const NAMES: Readonly<Record<Locale, LocaleNames>> = {
  en: {
    afterNoon: "p.m.",
    afterNoonUpper: "PM",
    beforeNoon: "a.m.",
    beforeNoonUpper: "AM",
    midnight: "midnight",
    months: ENGLISH_MONTHS,
    monthsAbbreviated: [
      "Jan",
      "Feb",
      "Mar",
      "Apr",
      "May",
      "Jun",
      "Jul",
      "Aug",
      "Sep",
      "Oct",
      "Nov",
      "Dec",
    ],
    monthsAssociatedPress: [
      "Jan.",
      "Feb.",
      "March",
      "April",
      "May",
      "June",
      "July",
      "Aug.",
      "Sept.",
      "Oct.",
      "Nov.",
      "Dec.",
    ],
    monthsGenitive: ENGLISH_MONTHS,
    noon: "noon",
    weekdays: [
      "Sunday",
      "Monday",
      "Tuesday",
      "Wednesday",
      "Thursday",
      "Friday",
      "Saturday",
    ],
    weekdaysAbbreviated: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
  },
  pl: {
    afterNoon: "po południu",
    afterNoonUpper: "po południu",
    beforeNoon: "rano",
    beforeNoonUpper: "rano",
    midnight: "północ",
    months: [
      "Styczeń",
      "Luty",
      "Marzec",
      "Kwiecień",
      "Maj",
      "Czerwiec",
      "Lipiec",
      "Sierpień",
      "Wrzesień",
      "Październik",
      "Listopad",
      "Grudzień",
    ],
    monthsAbbreviated: [
      "Sty",
      "Lut",
      "Mar",
      "Kwi",
      "Maj",
      "Cze",
      "Lip",
      "Sie",
      "Wrz",
      "Paź",
      "Lis",
      "Gru",
    ],
    monthsAssociatedPress: [
      "Sty.",
      "Lut.",
      "Mar.",
      "Kwi.",
      "Maj",
      "Cze.",
      "Lip.",
      "Sie.",
      "Wrz.",
      "Paź.",
      "Lis.",
      "Gru",
    ],
    monthsGenitive: [
      "stycznia",
      "lutego",
      "marca",
      "kwietnia",
      "maja",
      "czerwca",
      "lipca",
      "sierpnia",
      "września",
      "października",
      "listopada",
      "grudnia",
    ],
    noon: "południe",
    weekdays: [
      "Niedziela",
      "Poniedziałek",
      "Wtorek",
      "Środa",
      "Czwartek",
      "Piątek",
      "Sobota",
    ],
    weekdaysAbbreviated: ["Nd", "Pon", "Wt", "Śr", "Czw", "Pt", "So"],
  },
};

const NAMED_FORMATS: Readonly<
  Record<Locale, Readonly<Record<string, string>>>
> = {
  en: {
    DATETIME_FORMAT: "N j, Y, P",
    DATE_FORMAT: "N j, Y",
    MONTH_DAY_FORMAT: "F j",
    SHORT_DATETIME_FORMAT: "m/d/Y P",
    SHORT_DATE_FORMAT: "m/d/Y",
    TIME_FORMAT: "P",
    YEAR_MONTH_FORMAT: "F Y",
  },
  pl: {
    DATETIME_FORMAT: "j E Y H:i",
    DATE_FORMAT: "j E Y",
    MONTH_DAY_FORMAT: "j E",
    SHORT_DATETIME_FORMAT: "d-m-Y  H:i",
    SHORT_DATE_FORMAT: "d-m-Y",
    TIME_FORMAT: "H:i",
    YEAR_MONTH_FORMAT: "F Y",
  },
};

const WARSAW = DateTime.zoneMakeNamedUnsafe("Europe/Warsaw");

const WARSAW_STANDARD_OFFSET_MINUTES = 60;

const DAY_ROLLOVER_HOURS = 6;

const DATE_TIME =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?\s*(Z|[+-]\d{2}(?::?\d{2})?)?$/i;

const pad = (value: number, width = 2) => String(value).padStart(width, "0");

const offsetMinutesOf = (designator: string | undefined) => {
  if (designator === undefined || designator.toUpperCase() === "Z") {
    return 0;
  }

  const digits = designator.slice(1).replace(":", "");

  const minutes =
    Number(digits.slice(0, 2)) * 60 + Number(digits.slice(2) || "0");

  return designator.startsWith("-") ? -minutes : minutes;
};

const toLocal = (
  instant: DateTime.DateTime,
  microsecond: number
): LocalDateTime => {
  const zoned = DateTime.setZone(instant, WARSAW);
  const parts = DateTime.toParts(zoned);

  return {
    day: parts.day,
    epochMillis: DateTime.toEpochMillis(zoned),
    hour: parts.hour,
    microsecond,
    minute: parts.minute,
    month: parts.month,
    offsetMinutes: Math.round(DateTime.zonedOffset(zoned) / 60_000),
    second: parts.second,
    weekDay: parts.weekDay,
    year: parts.year,
  };
};

const parseDateTime = (value: string): Option.Option<LocalDateTime> => {
  const match = DATE_TIME.exec(value.trim());

  if (match === null) {
    return Option.none();
  }

  const [, year, month, day, hour, minute, second, fraction, designator] =
    match;

  const microsecond = Number((fraction ?? "").padEnd(6, "0").slice(0, 6));

  const written = {
    day: Number(day),
    hour: Number(hour),
    millisecond: Math.floor(microsecond / 1000),
    minute: Number(minute),
    month: Number(month),
    second: Number(second ?? "0"),
    year: Number(year),
  };

  return DateTime.make(written).pipe(
    Option.filter((instant) => {
      const parts = DateTime.toPartsUtc(instant);

      return (
        parts.year === written.year &&
        parts.month === written.month &&
        parts.day === written.day &&
        parts.hour === written.hour &&
        parts.minute === written.minute &&
        parts.second === written.second
      );
    }),
    Option.map((instant) =>
      toLocal(
        DateTime.subtract(instant, { minutes: offsetMinutesOf(designator) }),
        microsecond
      )
    )
  );
};

const shiftHours = (local: LocalDateTime, hours: number) =>
  toLocal(
    DateTime.makeUnsafe(local.epochMillis + hours * 3_600_000),
    local.microsecond
  );

const twelveHour = (local: LocalDateTime) => local.hour % 12 || 12;

const isLeapYear = (year: number) =>
  (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;

const daysInMonth = (local: LocalDateTime) =>
  [
    31,
    isLeapYear(local.year) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ][local.month - 1] ?? 0;

const dayOfYear = (local: LocalDateTime) =>
  Array.from({ length: local.month - 1 }, (_, index) =>
    daysInMonth({ ...local, month: index + 1 })
  ).reduce((total, days) => total + days, local.day);

const englishOrdinal = (day: number) => {
  if (day >= 11 && day <= 13) {
    return "th";
  }

  return ["th", "st", "nd", "rd"][day % 10] ?? "th";
};

const isoOffset = (local: LocalDateTime, separator: string) => {
  const sign = local.offsetMinutes < 0 ? "-" : "+";
  const minutes = Math.abs(local.offsetMinutes);

  return `${sign}${pad(Math.floor(minutes / 60))}${separator}${pad(minutes % 60)}`;
};

const isoFormat = (local: LocalDateTime) =>
  `${pad(local.year, 4)}-${pad(local.month)}-${pad(local.day)}T${pad(local.hour)}:${pad(local.minute)}:${pad(local.second)}${local.microsecond === 0 ? "" : `.${pad(local.microsecond, 6)}`}${isoOffset(local, ":")}`;

const zoneAbbreviation = (local: LocalDateTime) =>
  local.offsetMinutes === WARSAW_STANDARD_OFFSET_MINUTES ? "CET" : "CEST";

const isAmbiguousWallClock = (local: LocalDateTime) => {
  const otherOffset =
    local.offsetMinutes === WARSAW_STANDARD_OFFSET_MINUTES
      ? WARSAW_STANDARD_OFFSET_MINUTES + 60
      : WARSAW_STANDARD_OFFSET_MINUTES;

  const twin = toLocal(
    DateTime.makeUnsafe(
      local.epochMillis + (local.offsetMinutes - otherOffset) * 60_000
    ),
    local.microsecond
  );

  return (
    twin.offsetMinutes === otherOffset &&
    twin.hour === local.hour &&
    twin.minute === local.minute
  );
};

const ZONE_SPECIFIERS = "eIOTZ";

const formatSpecifier = (
  local: LocalDateTime,
  names: LocaleNames,
  specifier: string
): string | undefined => {
  const month = local.month - 1;
  const meridiem = local.hour > 11 ? names.afterNoon : names.beforeNoon;

  const hourAndMinute =
    local.minute === 0
      ? String(twelveHour(local))
      : `${twelveHour(local)}:${pad(local.minute)}`;

  if (ZONE_SPECIFIERS.includes(specifier) && isAmbiguousWallClock(local)) {
    return "";
  }

  switch (specifier) {
    case "a": {
      return meridiem;
    }

    case "A": {
      return local.hour > 11 ? names.afterNoonUpper : names.beforeNoonUpper;
    }

    case "b": {
      return names.monthsAbbreviated[month]?.toLowerCase();
    }

    case "c": {
      return isoFormat(local);
    }

    case "d": {
      return pad(local.day);
    }

    case "D": {
      return names.weekdaysAbbreviated[local.weekDay];
    }

    case "e":
    case "T": {
      return zoneAbbreviation(local);
    }

    case "E": {
      return names.monthsGenitive[month];
    }

    case "f": {
      return hourAndMinute;
    }

    case "F": {
      return names.months[month];
    }

    case "g": {
      return String(twelveHour(local));
    }

    case "G": {
      return String(local.hour);
    }

    case "h": {
      return pad(twelveHour(local));
    }

    case "H": {
      return pad(local.hour);
    }

    case "i": {
      return pad(local.minute);
    }

    case "I": {
      return local.offsetMinutes === WARSAW_STANDARD_OFFSET_MINUTES ? "0" : "1";
    }

    case "j": {
      return String(local.day);
    }

    case "l": {
      return names.weekdays[local.weekDay];
    }

    case "L": {
      return isLeapYear(local.year) ? "True" : "False";
    }

    case "m": {
      return pad(local.month);
    }

    case "M": {
      return names.monthsAbbreviated[month];
    }

    case "n": {
      return String(local.month);
    }

    case "N": {
      return names.monthsAssociatedPress[month];
    }

    case "O": {
      return isoOffset(local, "");
    }

    case "P": {
      if (local.minute === 0 && local.hour === 0) {
        return names.midnight;
      }

      if (local.minute === 0 && local.hour === 12) {
        return names.noon;
      }

      return `${hourAndMinute} ${meridiem}`;
    }

    case "s": {
      return pad(local.second);
    }

    case "S": {
      return englishOrdinal(local.day);
    }

    case "t": {
      return pad(daysInMonth(local));
    }

    case "u": {
      return pad(local.microsecond, 6);
    }

    case "U": {
      return String(Math.floor(local.epochMillis / 1000));
    }

    case "w": {
      return String(local.weekDay);
    }

    case "y": {
      return pad(local.year % 100);
    }

    case "Y": {
      return pad(local.year, 4);
    }

    case "z": {
      return String(dayOfYear(local));
    }

    case "Z": {
      return String(local.offsetMinutes * 60);
    }

    default: {
      return undefined;
    }
  }
};

const render = (locale: Locale, local: LocalDateTime, format: string) => {
  const formats = NAMED_FORMATS[locale];

  const pattern = Object.hasOwn(formats, format)
    ? (formats[format] ?? format)
    : format;

  const names = NAMES[locale];
  let text = "";
  let escaped = false;

  for (const character of pattern) {
    if (escaped) {
      text += character;
      escaped = false;
    } else if (character === "\\") {
      escaped = true;
    } else {
      text += formatSpecifier(local, names, character) ?? character;
    }
  }

  return text;
};

const abbreviatedMonthFormat = (locale: Locale, withYear: boolean) =>
  (
    NAMED_FORMATS[locale][withYear ? "DATE_FORMAT" : "MONTH_DAY_FORMAT"] ?? ""
  ).replaceAll(/[FNE]/g, (token) => (token === "E" ? "b" : "M"));

const isSameDay = (left: LocalDateTime, right: LocalDateTime) =>
  left.year === right.year &&
  left.month === right.month &&
  left.day === right.day;

const rangeLabel = (
  locale: Locale,
  {
    end,
    now,
    start,
  }: { start: LocalDateTime; end: LocalDateTime; now: LocalDateTime }
) => {
  const date = abbreviatedMonthFormat(
    locale,
    start.year !== end.year || start.year !== now.year
  );

  const time = (local: LocalDateTime) => render(locale, local, "TIME_FORMAT");
  const opening = `${render(locale, start, date)}, ${time(start)}`;

  return isSameDay(start, end)
    ? `${opening} – ${time(end)}`
    : `${opening} – ${render(locale, end, date)}, ${time(end)}`;
};

export const formatDate = ({
  format,
  locale,
  value,
}: {
  readonly locale: Locale;
  readonly value: string;
  readonly format: string;
}): string =>
  Option.match(parseDateTime(value), {
    onNone: () => value,
    onSome: (local) => render(locale, local, format),
  });

export const shortDate = (locale: Locale, value: string): string =>
  formatDate({
    format: `D ${abbreviatedMonthFormat(locale, false)}`,
    locale,
    value,
  });

export const formatDateRange = ({
  end,
  locale,
  now,
  start,
}: {
  readonly locale: Locale;
  readonly start: string;
  readonly end: string;
  readonly now: string;
}): string =>
  Option.match(
    Option.all({
      end: parseDateTime(end),
      now: parseDateTime(now),
      start: parseDateTime(start),
    }),
    {
      onNone: () => `${start} – ${end}`,
      onSome: (range) => rangeLabel(locale, range),
    }
  );

export const DateLeaf = Schema.Struct({
  band: Schema.String,
  bandIsLong: Schema.Boolean,
  datetime: Schema.String,
  day: Schema.String,
  hour: Schema.String,
  isOngoing: Schema.Boolean,
  isRange: Schema.Boolean,
  isSunday: Schema.Boolean,
  isToday: Schema.Boolean,
  label: Schema.String,
  weekday: Schema.String,
});

export type DateLeaf = typeof DateLeaf.Type;

const SHORTEST_BAND_LENGTH = [..."paź"].length;

const SUNDAY = 0;

const leafOf = (
  locale: Locale,
  {
    end,
    now,
    start,
  }: {
    start: LocalDateTime;
    end: Option.Option<LocalDateTime>;
    now: LocalDateTime;
  }
): DateLeaf => {
  const { t } = translator(locale);
  const finish = Option.getOrElse(end, () => start);
  const rolledBack = shiftHours(finish, -DAY_ROLLOVER_HOURS);
  const last = rolledBack.epochMillis > start.epochMillis ? rolledBack : start;
  const isRange = !isSameDay(start, last);
  const sameMonth = start.year === last.year && start.month === last.month;
  const monthBand = render(locale, start, "b");

  const band = sameMonth
    ? start.year === now.year
      ? monthBand
      : `${monthBand} ${start.year}`
    : `${monthBand}–${render(locale, last, "b")}`;

  const isOngoing =
    isRange &&
    start.epochMillis <= now.epochMillis &&
    now.epochMillis <= finish.epochMillis;

  const isToday = !isRange && isSameDay(start, now);

  const label = Option.isSome(end)
    ? rangeLabel(locale, { end: finish, now, start })
    : `${render(locale, start, abbreviatedMonthFormat(locale, true))}, ${render(locale, start, "TIME_FORMAT")}`;

  return {
    band,
    bandIsLong: [...band].length > SHORTEST_BAND_LENGTH,
    datetime: isoFormat(start),
    day: isRange ? `${start.day}–${last.day}` : String(start.day),
    hour: isOngoing ? t("ongoing") : render(locale, start, "H:i"),
    isOngoing,
    isRange,
    isSunday: !isRange && start.weekDay === SUNDAY,
    isToday,
    label,
    weekday: isToday
      ? t("today")
      : isRange
        ? `${render(locale, start, "D")}–${render(locale, last, "D")}`
        : render(locale, start, "D"),
  };
};

export const dateLeaf = ({
  end,
  locale,
  now,
  start,
}: {
  readonly locale: Locale;
  readonly start: string;
  readonly end?: string;
  readonly now: string;
}): Option.Option<DateLeaf> => {
  const parsedEnd =
    end === undefined
      ? Option.some(Option.none<LocalDateTime>())
      : Option.map(parseDateTime(end), Option.some);

  return Option.map(
    Option.all({
      end: parsedEnd,
      now: parseDateTime(now),
      start: parseDateTime(start),
    }),
    (moments) => leafOf(locale, moments)
  );
};
