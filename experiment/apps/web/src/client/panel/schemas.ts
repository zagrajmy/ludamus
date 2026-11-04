import { Schema } from "effect";

export const SessionStatusSchema = Schema.Literals([
  "pending",
  "accepted",
  "on_hold",
  "rejected",
]);

export type SessionStatusValue = typeof SessionStatusSchema.Type;

export const NamedId = Schema.Struct({ id: Schema.Int, name: Schema.String });

export type NamedId = typeof NamedId.Type;
