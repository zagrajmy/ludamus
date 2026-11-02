import { Schema } from "effect";

export class MembershipApiError extends Schema.TaggedError<
  MembershipApiError,
  { readonly brand: unique symbol }
>()("MembershipApiError", {
  reason: Schema.String,
}) {
  override get message(): string {
    return `Membership lookup failed: ${this.reason}`;
  }
}
