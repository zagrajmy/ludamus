import { Option, Schema } from "effect";
import { describe, expect, it } from "vitest";

import {
  DateLeaf,
  dateLeaf,
  formatDate,
  formatDateRange,
  shortDate,
} from "../src/dates.js";
import { Locale } from "../src/locale-schema.js";
import { negotiateLocale } from "../src/locale.js";
import cases from "./fixtures/django-cases.json" with { type: "json" };

const DjangoCase = Schema.Union([
  Schema.Struct({
    expected: Schema.String,
    format: Schema.String,
    kind: Schema.Literal("format"),
    locale: Locale,
    value: Schema.String,
  }),
  Schema.Struct({
    expected: Schema.String,
    kind: Schema.Literal("shortDate"),
    locale: Locale,
    value: Schema.String,
  }),
  Schema.Struct({
    end: Schema.String,
    expected: Schema.String,
    kind: Schema.Literal("range"),
    locale: Locale,
    now: Schema.String,
    start: Schema.String,
  }),
  Schema.Struct({
    end: Schema.optionalKey(Schema.String),
    expected: DateLeaf,
    kind: Schema.Literal("leaf"),
    locale: Locale,
    now: Schema.String,
    start: Schema.String,
  }),
  Schema.Struct({
    expected: Locale,
    header: Schema.String,
    kind: Schema.Literal("negotiate"),
  }),
]);

const replayed = Schema.decodeUnknownSync(Schema.Array(DjangoCase))(cases);

const ofKind = <Kind extends (typeof replayed)[number]["kind"]>(kind: Kind) =>
  replayed.filter(
    (entry): entry is Extract<(typeof replayed)[number], { kind: Kind }> =>
      entry.kind === kind
  );

describe("replaying what Django rendered", () => {
  it("covers every helper", () => {
    expect(new Set(replayed.map((entry) => entry.kind))).toEqual(
      new Set(["format", "shortDate", "range", "leaf", "negotiate"])
    );
  });

  it.each(ofKind("format"))(
    "|date:$format for $value in $locale",
    ({ expected, ...input }) => {
      expect(formatDate(input)).toBe(expected);
    }
  );

  it.each(ofKind("shortDate"))(
    "short_date for $value in $locale",
    ({ expected, locale, value }) => {
      expect(shortDate(locale, value)).toBe(expected);
    }
  );

  it.each(ofKind("range"))(
    "format_datetime_range $start – $end in $locale",
    ({ expected, ...input }) => {
      expect(formatDateRange(input)).toBe(expected);
    }
  );

  it.each(ofKind("leaf"))(
    "date_leaf $start – $end in $locale",
    ({ expected, ...input }) => {
      expect(dateLeaf(input)).toEqual(Option.some(expected));
    }
  );

  it.each(ofKind("negotiate"))(
    "LocaleMiddleware picks $expected for '$header'",
    ({ expected, header }) => {
      expect(negotiateLocale(header)).toBe(expected);
    }
  );
});
