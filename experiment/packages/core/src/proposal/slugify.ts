import { Schema } from "effect";

import { asciiFold } from "./unidecode.js";

export const PROPOSAL_SLUG_MAX_LENGTH = 50;

export const PROPOSAL_SLUG_ATTEMPTS = 8;

const PY_ASCII_SPACE = String.raw` \t\n\r\f\v\u001C-\u001F`;

const NON_WORD = new RegExp(String.raw`[^\w${PY_ASCII_SPACE}-]`, "gu");

const DASHES_AND_SPACES = new RegExp(`[-${PY_ASCII_SPACE}]+`, "gu");

const stripDashes = (text: string): string => text.replaceAll(/^-+|-+$/gu, "");

export const proposalSlugify = (
  value: string,
  maxLength: number = PROPOSAL_SLUG_MAX_LENGTH
): string => {
  const slug = asciiFold(value).toLowerCase().replaceAll(NON_WORD, "");

  return stripDashes(
    stripDashes(slug.replaceAll(DASHES_AND_SPACES, "-")).slice(0, maxLength)
  );
};

export class SlugCollisionError extends Schema.TaggedError<
  SlugCollisionError,
  { readonly brand: unique symbol }
>()("SlugCollisionError", { baseSlug: Schema.String }) {
  override get message(): string {
    return `Could not generate a unique slug for '${this.baseSlug}'.`;
  }
}

export const slugCandidates = (options: {
  readonly title: string;
  readonly fallback: string;
  readonly suffixes: readonly string[];
}): readonly string[] => {
  const base = proposalSlugify(options.title) || options.fallback;

  return [
    base,
    ...options.suffixes.map((suffix) => {
      const trimmed = proposalSlugify(
        base,
        PROPOSAL_SLUG_MAX_LENGTH - suffix.length - 1
      );

      return `${trimmed}-${suffix}`;
    }),
  ].slice(0, PROPOSAL_SLUG_ATTEMPTS);
};
