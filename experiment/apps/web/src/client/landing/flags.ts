import { Schema } from "effect";

export const LandingConvention = Schema.Struct({
  coverUrl: Schema.String,
  domain: Schema.String,
  eventSlug: Schema.String,
  name: Schema.String,
});
export type LandingConvention = typeof LandingConvention.Type;

export const LandingFlags = Schema.Struct({
  contactEmail: Schema.String,
  conventions: Schema.Array(LandingConvention),
  encountersEnabled: Schema.Boolean,
  showcaseUrl: Schema.String,
});
export type LandingFlags = typeof LandingFlags.Type;
