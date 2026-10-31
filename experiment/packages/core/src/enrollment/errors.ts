import { Schema } from "effect";

export class InvalidEnrollmentWindowError extends Schema.TaggedError<
  InvalidEnrollmentWindowError,
  { readonly brand: unique symbol }
>()("InvalidEnrollmentWindowError", {
  endTime: Schema.DateTimeUtcFromString,
  startTime: Schema.DateTimeUtcFromString,
}) {
  override get message(): string {
    return "An enrollment window must end after it starts";
  }
}

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
