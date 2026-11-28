import { Schema } from "effect";

export const AboutConvention = Schema.Struct({
  domain: Schema.String,
  name: Schema.String,
});

export const AboutFlags = Schema.Struct({
  contactEmail: Schema.String,
  conventions: Schema.Array(AboutConvention),
  eventCount: Schema.Int,
  sessionCount: Schema.Int,
});

export type AboutFlags = typeof AboutFlags.Type;
