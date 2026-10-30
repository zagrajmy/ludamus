import { Context, Schema } from "effect";

import { DEFAULT_LOCALE, Locale } from "./locale-schema.js";
import { translator } from "./translator.js";

export class CurrentLocale extends Context.Service<CurrentLocale, Locale>()(
  "@zagrajmy/i18n/CurrentLocale"
) {}

export const CurrentTranslator = CurrentLocale.useSync(translator);

const HEADER_MAX_LENGTH = 500;

const LANGUAGE_CODE = /^[a-z]{1,8}(?:-[a-z0-9]{1,8})*(?:@[a-z0-9]{1,20})?$/i;

const isLocale = Schema.is(Locale);

interface LanguageRange {
  readonly tag: string;
  readonly quality: number;
}

const parseRanges = (header: string): readonly LanguageRange[] => {
  const pattern =
    /([A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*|\*)(?:\s*;\s*q=(0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?))?(?:\s*,\s*|$)/y;

  const lowered = header.toLowerCase();
  const ranges: LanguageRange[] = [];

  while (pattern.lastIndex < lowered.length) {
    const start = pattern.lastIndex;
    const match = pattern.exec(lowered);

    if (match === null || pattern.lastIndex === start) {
      return [];
    }

    ranges.push({
      quality: match[2] === undefined ? 1 : Number(match[2]),
      tag: match[1] ?? "",
    });
  }

  return ranges.toSorted((left, right) => right.quality - left.quality);
};

const boundedRanges = (header: string) => {
  if (header.length <= HEADER_MAX_LENGTH) {
    return parseRanges(header);
  }

  const lastComma = header.lastIndexOf(",", HEADER_MAX_LENGTH - 1);

  return lastComma > 0 ? parseRanges(header.slice(0, lastComma)) : [];
};

const supportedVariant = (tag: string) => {
  const generic = tag.split("-")[0] ?? "";

  return isLocale(generic) ? generic : undefined;
};

export const negotiateLocale = (header: string | null): Locale => {
  for (const { tag } of boundedRanges(header ?? "")) {
    if (tag === "*") {
      break;
    }

    if (!LANGUAGE_CODE.test(tag)) {
      continue;
    }

    const variant = supportedVariant(tag);

    if (variant !== undefined) {
      return variant;
    }
  }

  return DEFAULT_LOCALE;
};
