import { Result, Schema } from "effect";

import {
  PY_DECIMAL_CLASS,
  PY_SPACE_CLASS,
  pyDecimalInt,
  pyIsDigitString,
  pyLength,
  pyStrip,
} from "./python-text.js";

export const MINUTES_PER_HOUR = 60;

export const MAX_DURATION_HOURS = 23;

export const MAX_DURATION_MINUTES = 59;

const DIGIT = PY_DECIMAL_CLASS;

const SPACE = PY_SPACE_CLASS;

const CANONICAL_DURATION = new RegExp(
  `^PT(?:(?<hours>${DIGIT}+)H)?(?:(?<minutes>${DIGIT}+)M)?$`,
  "u"
);

const LOOSE_DURATION = new RegExp(
  `^p?t?${SPACE}*(?:(?<hours>${DIGIT}{1,4})${SPACE}*h(?:ours?|rs?)?)?` +
    `${SPACE}*(?:(?<minutes>${DIGIT}{1,4})${SPACE}*m(?:inutes?|ins?)?)?$`,
  "u"
);

export class InvalidDurationError extends Schema.TaggedError<
  InvalidDurationError,
  { readonly brand: unique symbol }
>()("InvalidDurationError", { raw: Schema.String }) {
  override get message(): string {
    return "Enter a length as whole hours (0-23) and minutes (0-59).";
  }
}

export class DurationDigitError extends Schema.TaggedError<
  DurationDigitError,
  { readonly brand: unique symbol }
>()("DurationDigitError", { raw: Schema.String }) {
  override get message(): string {
    return `"${this.raw}" is made of digits that are not decimal numbers`;
  }
}

const groupValue = (
  match: RegExpMatchArray,
  name: "hours" | "minutes"
): number => {
  const raw = match.groups?.[name];

  return raw === undefined ? 0 : (pyDecimalInt(raw) ?? 0);
};

export const parseDuration = (
  isoDuration: string | null
): readonly [number, number] => {
  const match = (isoDuration ?? "").match(CANONICAL_DURATION);

  if (match === null) {
    return [0, 0];
  }

  return [groupValue(match, "hours"), groupValue(match, "minutes")];
};

export const parseDurationPart = (part: {
  readonly raw: string | null;
  readonly maximum: number;
}): Result.Result<number, InvalidDurationError | DurationDigitError> => {
  const text = pyStrip(part.raw ?? "");

  if (text === "") {
    return Result.succeed(0);
  }

  if (!pyIsDigitString(text) || pyLength(text) > String(part.maximum).length) {
    return Result.fail(new InvalidDurationError({ raw: text }));
  }

  const value = pyDecimalInt(text);

  if (value === null) {
    return Result.fail(new DurationDigitError({ raw: text }));
  }

  if (value > part.maximum) {
    return Result.fail(new InvalidDurationError({ raw: text }));
  }

  return Result.succeed(value);
};

export const stepperParts = (iso: string | null): readonly [string, string] => {
  const [hours, minutes] = parseDuration(iso);

  return [hours ? String(hours) : "", minutes ? String(minutes) : ""];
};

export const buildDuration = (parts: {
  readonly hours: number;
  readonly minutes: number;
}): string => {
  const carried = Math.floor(parts.minutes / MINUTES_PER_HOUR);
  const minutes = parts.minutes - carried * MINUTES_PER_HOUR;
  const hours = parts.hours + carried;

  if (!hours && !minutes) {
    return "";
  }

  return `PT${hours ? `${hours}H` : ""}${minutes ? `${minutes}M` : ""}`;
};

export const durationFromParts = (parts: {
  readonly hours: string | null;
  readonly minutes: string | null;
}): Result.Result<string, InvalidDurationError | DurationDigitError> =>
  Result.flatMap(
    parseDurationPart({ maximum: MAX_DURATION_HOURS, raw: parts.hours }),
    (hours) =>
      Result.map(
        parseDurationPart({
          maximum: MAX_DURATION_MINUTES,
          raw: parts.minutes,
        }),
        (minutes) => buildDuration({ hours, minutes })
      )
  );

export const normalizeDuration = (text: string): string => {
  const match = pyStrip(text).toLowerCase().match(LOOSE_DURATION);

  if (match === null) {
    return "";
  }

  return buildDuration({
    hours: groupValue(match, "hours"),
    minutes: groupValue(match, "minutes"),
  });
};

export const formatDuration = (isoDuration: string | null): string => {
  const [hours, minutes] = parseDuration(isoDuration);

  if (hours && minutes) {
    return `${hours}h ${minutes}min`;
  }

  if (hours) {
    return `${hours}h`;
  }

  if (minutes) {
    return `${minutes}min`;
  }

  return "";
};

export const durationChoices = (
  durations: readonly string[]
): readonly (readonly [string, string])[] =>
  durations.flatMap((duration) => {
    const label = formatDuration(duration);
    const choice: readonly [string, string] = [duration, label];

    return label ? [choice] : [];
  });
