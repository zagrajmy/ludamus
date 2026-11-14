import { Schema } from "effect";

export const ContentSlug = Schema.Literals([
  "privacy-policy",
  "terms-of-service",
]);

export const contentSlugs = ContentSlug.literals;

export type ContentSlug = typeof ContentSlug.Type;

export const ContentPageFlags = Schema.Struct({
  documentHtml: Schema.String,
  slug: ContentSlug,
});

export type ContentPageFlags = typeof ContentPageFlags.Type;
