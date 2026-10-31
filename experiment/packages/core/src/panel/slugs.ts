import { Effect, Random } from "effect";

const URLSAFE =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

const TRANSLITERATIONS: Readonly<Record<string, string>> = {
  Æ: "AE",
  Ð: "D",
  Ø: "O",
  Þ: "Th",
  ß: "ss",
  æ: "ae",
  ð: "d",
  ø: "o",
  þ: "th",
  Ł: "L",
  ł: "l",
};

const words = (ascii: string) =>
  ascii
    .toLowerCase()
    .replaceAll(/[^\w\s-]/gu, "")
    .replaceAll(/[-\s]+/gu, "-");

export const djangoSlugify = (value: string) =>
  words(
    value.normalize("NFKD").replaceAll(/[^\u0000-\u007F]/gu, "")
  ).replaceAll(/^[-_]+|[-_]+$/gu, "");

export const transliteratedSlugify = (value: string, maxLength = 50) =>
  words(
    [...value]
      .map((char) => TRANSLITERATIONS[char] ?? char)
      .join("")
      .normalize("NFKD")
      .replaceAll(/[^\u0000-\u007F]/gu, "")
  )
    .replaceAll(/^-+|-+$/gu, "")
    .slice(0, maxLength)
    .replaceAll(/^-+|-+$/gu, "");

export const urlsafeToken = Effect.fn("Panel.urlsafeToken")(
  function* urlsafeToken() {
    const picks = yield* Effect.forEach([0, 1, 2, 3], () =>
      Random.nextIntBetween(0, URLSAFE.length)
    );

    return picks.map((index) => URLSAFE.charAt(index)).join("");
  }
);

export const uniqueSlug = Effect.fn("Panel.uniqueSlug")(function* uniqueSlug<
  E,
>(options: {
  readonly attempts: number;
  readonly base: string;
  readonly exists: (slug: string) => Effect.Effect<boolean, E>;
  readonly trim: (base: string, suffix: string) => string;
}) {
  let slug = options.base;

  for (let attempt = 0; attempt < options.attempts; attempt += 1) {
    if (!(yield* options.exists(slug))) {
      return slug;
    }

    const suffix = yield* urlsafeToken();
    slug = `${options.trim(options.base, suffix)}-${suffix}`;
  }

  return slug;
});
