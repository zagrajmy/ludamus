import { Schema } from "effect";

export class EnrollmentStoreError extends Schema.TaggedError<
  EnrollmentStoreError,
  { readonly brand: unique symbol }
>()("EnrollmentStoreError", {
  operation: Schema.String,
  reason: Schema.String,
}) {
  override get message(): string {
    return `${this.operation} failed: ${this.reason}`;
  }
}
