import { pySlice } from "./python-text.js";

export const SLUG_BASE_MAX_LENGTH = 45;

export const SLUG_ATTEMPTS = 4;

export const uniqueSlug = (options: {
  readonly base: string;
  readonly fallback: string;
  readonly exists: (slug: string) => boolean;
  readonly nextSuffix: () => string;
}): string => {
  const capped = pySlice(
    options.base === "" ? options.fallback : options.base,
    SLUG_BASE_MAX_LENGTH
  );

  let slug = capped;

  for (let attempt = 0; attempt < SLUG_ATTEMPTS; attempt += 1) {
    if (!options.exists(slug)) {
      break;
    }

    slug = `${capped}-${options.nextSuffix()}`;
  }

  return slug;
};
