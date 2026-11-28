import { Schema } from "effect";

export class InvalidDurationError extends Schema.TaggedError<
  InvalidDurationError,
  { readonly brand: unique symbol }
>()("InvalidDurationError", { raw: Schema.String }) {
  override get message(): string {
    return `"${this.raw}" is not a length in whole hours (0-23) and minutes (0-59)`;
  }
}
