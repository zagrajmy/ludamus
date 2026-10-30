import { Schema } from "effect";

export const NotFoundFlags = Schema.Struct({ path: Schema.String });
export type NotFoundFlags = typeof NotFoundFlags.Type;

export const NotPortedFlags = Schema.Struct({
  pageName: Schema.String,
  path: Schema.String,
});
export type NotPortedFlags = typeof NotPortedFlags.Type;
