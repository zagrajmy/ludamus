import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";
import { defineTaggedUnion } from "foldkit/schema";

import { EnrollmentFooterMessages } from "./enrollment/message.js";
import { FooterState } from "./enrollment/model.js";

export const EnrollmentActions = defineTaggedUnion({
  Loading: { sessionId: Schema.Int },
  NotAvailable: {},
  Seat: { state: FooterState },
  SignInToEnroll: { href: Schema.String },
});

export type EnrollmentActions = typeof EnrollmentActions.Type;

export const EnrollmentSlotMessage = defineMessageUnion({
  ClickedEnrollmentAction: { sessionId: Schema.Int },
  ...EnrollmentFooterMessages,
});

export type EnrollmentSlotMessage = typeof EnrollmentSlotMessage.Type;

export const enrollmentActionsFor = (options: {
  readonly loginUrl: string;
  readonly sessionId: number;
  readonly signedIn: boolean;
  readonly slug: string;
  readonly takesEnrollment: boolean;
  readonly canEnrollNow: boolean;
}): EnrollmentActions =>
  options.signedIn
    ? EnrollmentActions.Loading({ sessionId: options.sessionId })
    : options.takesEnrollment && options.canEnrollNow
      ? EnrollmentActions.SignInToEnroll({
          href: `${options.loginUrl}?next=/event/${options.slug}/%3Fsession%3D${options.sessionId}`,
        })
      : EnrollmentActions.NotAvailable();
