import { Schema } from "effect";

export class InvalidEnrollmentWindowError extends Schema.TaggedError<
  InvalidEnrollmentWindowError,
  { readonly brand: unique symbol }
>()("InvalidEnrollmentWindowError", {
  endTime: Schema.DateTimeUtcFromString,
  startTime: Schema.DateTimeUtcFromString,
}) {
  // oxlint-disable-next-line eslint/class-methods-use-this -- overrides the inherited Error.message accessor, which cannot be static
  override get message(): string {
    return "An enrollment window must end after it starts";
  }
}
