import { Schema } from "effect";

export class NotEnoughSpotsError extends Schema.TaggedError<
  NotEnoughSpotsError,
  { readonly brand: unique symbol }
>()("NotEnoughSpotsError", {
  available: Schema.Int,
  blameGuests: Schema.Boolean,
  requested: Schema.Int,
}) {
  override get message(): string {
    return this.blameGuests
      ? `Not enough spots available. ${this.requested} spots requested, ${this.available} available. Bring fewer guests or use the waiting list for account holders.`
      : `Not enough spots available. ${this.requested} spots requested, ${this.available} available. Please use waiting list for some users.`;
  }
}
