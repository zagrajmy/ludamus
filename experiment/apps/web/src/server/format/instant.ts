import { Option } from "effect";

export type Instant = Readonly<{ epochMillis: number; microsecond: number }>;

const storedPattern =
  /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)?$/u;

export const parseStoredInstant = (stored: string): Option.Option<Instant> => {
  const match = storedPattern.exec(stored);

  if (match === null) {
    return Option.none();
  }

  const [, year, month, day, hour, minute, second, fraction = ""] = match;
  const microsecond = Number(fraction.padEnd(6, "0"));

  return Option.some({
    epochMillis:
      Date.UTC(
        Number(year),
        Number(month) - 1,
        Number(day),
        Number(hour),
        Number(minute),
        Number(second)
      ) + Math.floor(microsecond / 1000),
    microsecond,
  });
};

export const instantFromMillis = (epochMillis: number): Instant => ({
  epochMillis,
  microsecond: (epochMillis % 1000) * 1000,
});

export const storedTimestamp = (instant: Instant) =>
  new Date(instant.epochMillis)
    .toISOString()
    .replace("T", " ")
    .replace("Z", "")
    .padEnd(26, "0");

export const isBefore = (left: Instant, right: Instant) =>
  left.epochMillis < right.epochMillis;
