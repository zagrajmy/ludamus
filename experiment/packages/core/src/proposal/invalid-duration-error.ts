import { Schema } from "effect";

export class InvalidDurationError extends Schema.TaggedError<
  InvalidDurationError,
  { readonly brand: unique symbol }
>()("InvalidDurationError", { raw: Schema.String }) {
  // oxlint-disable-next-line eslint/class-methods-use-this -- overrides the inherited Error.message accessor, which cannot be static
  override get message(): string {
    return "Enter a length as whole hours (0-23) and minutes (0-59).";
  }
}
