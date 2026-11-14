import { EnrollFooter } from "@zagrajmy/core/contracts";
import { Schema } from "effect";

import { FooterSeats } from "./model.js";

export const EnrollmentFooterMessages = {
  ClickedBookmark: { sessionId: Schema.Int },
  ClickedFooterChoice: { sessionId: Schema.Int },
  FailedReadEnrollFooter: { sessionId: Schema.Int },
  FailedSubmitEnrollments: {
    error: Schema.String,
    footer: Schema.NullOr(EnrollFooter),
    sessionId: Schema.Int,
  },
  FailedToggleBookmark: {
    bookmarked: Schema.Boolean,
    count: Schema.Int,
    sessionId: Schema.Int,
  },
  GotEnrollFooter: {
    eventSlug: Schema.String,
    footer: EnrollFooter,
    seats: FooterSeats,
    sessionId: Schema.Int,
    viewerId: Schema.Int,
  },
  KeptSeat: { sessionId: Schema.Int },
  SucceededSubmitEnrollments: {
    footer: EnrollFooter,
    notice: Schema.String,
    seats: FooterSeats,
    sessionId: Schema.Int,
  },
  SucceededToggleBookmark: {
    bookmarked: Schema.Boolean,
    count: Schema.Int,
    sessionId: Schema.Int,
  },
} as const;
