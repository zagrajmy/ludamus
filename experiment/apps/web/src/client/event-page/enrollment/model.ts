import { EnrollFooter } from "@zagrajmy/core/contracts";
import { Schema } from "effect";

export const FooterState = Schema.Struct({
  busy: Schema.Boolean,
  error: Schema.String,
  eventSlug: Schema.String,
  footer: EnrollFooter,
  notice: Schema.String,
  sessionId: Schema.Int,
  viewerId: Schema.Int,
});

export type FooterState = typeof FooterState.Type;

export const FooterSeats = Schema.Struct({
  enrolledCount: Schema.Int,
  isFull: Schema.Boolean,
  seatsLeft: Schema.Int,
  waitingCount: Schema.Int,
});

export type FooterSeats = typeof FooterSeats.Type;

export const enrollmentPath = (state: FooterState) =>
  `/event/${state.eventSlug}/session/${state.sessionId}/enrollment/`;
