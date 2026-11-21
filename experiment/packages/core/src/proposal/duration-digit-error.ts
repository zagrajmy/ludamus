import { Schema } from "effect";

export class DurationDigitError extends Schema.TaggedError<
  DurationDigitError,
  { readonly brand: unique symbol }
>()("DurationDigitError", { raw: Schema.String }) {
  override get message(): string {
    return `"${this.raw}" is made of digits that are not decimal numbers`;
  }
}
