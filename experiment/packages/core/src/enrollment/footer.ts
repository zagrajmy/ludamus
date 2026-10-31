import { Schema } from "effect";

export const SeatBadge = Schema.Struct({
  icon: Schema.Literals(["check-circle", "clock"]),
  label: Schema.String,
  tone: Schema.Literals(["success", "warning"]),
});

export type SeatBadge = typeof SeatBadge.Type;

export const FooterChoice = Schema.Literals(["enroll", "waitlist", "cancel"]);

export type FooterChoice = typeof FooterChoice.Type;

export const EnrollActions = Schema.Struct({
  badge: Schema.NullOr(SeatBadge),
  confirm: Schema.String,
  groupLabel: Schema.String,
  submitIcon: Schema.Literals(["user-plus", "clock", "x-mark"]),
  submitLabel: Schema.String,
  submitValue: FooterChoice,
});

export type EnrollActions = typeof EnrollActions.Type;

export const EnrollFooter = Schema.Struct({
  actions: Schema.NullOr(EnrollActions),
  opensAt: Schema.NullOr(Schema.DateTimeUtcFromString),
});

export type EnrollFooter = typeof EnrollFooter.Type;

export const FooterFacts = Schema.Struct({
  isEnded: Schema.Boolean,
  isEnrollmentAvailable: Schema.Boolean,
  isFull: Schema.Boolean,
  isScheduled: Schema.Boolean,
  opensAt: Schema.NullOr(Schema.DateTimeUtcFromString),
  participantsLimit: Schema.Int,
  userEnrolled: Schema.Boolean,
  userWaiting: Schema.Boolean,
});

export type FooterFacts = typeof FooterFacts.Type;

const cancelConfirm = (facts: {
  readonly isEnrollmentAvailable: boolean;
  readonly isFull: boolean;
}): string => {
  if (facts.isEnrollmentAvailable) {
    return facts.isFull
      ? "This session is full — cancelling hands your seat to the next person waiting. Cancel anyway?"
      : "";
  }

  return facts.isFull
    ? "Enrollment is closed — your seat goes to the next person waiting and you cannot take it back. Cancel anyway?"
    : "Enrollment is closed — once you give up your seat you cannot take it back. Cancel anyway?";
};

const WAY_IN_GROUP_LABEL = "Enroll with others…";

export const enrollActions = (
  facts: Omit<FooterFacts, "isScheduled" | "opensAt" | "participantsLimit">
): EnrollActions | null => {
  const holds = facts.userEnrolled || facts.userWaiting;

  if (!facts.isEnrollmentAvailable && (facts.isEnded || !holds)) {
    return null;
  }

  if (holds) {
    const groupLabel = facts.isEnrollmentAvailable
      ? WAY_IN_GROUP_LABEL
      : "Manage the seats you booked for others…";

    if (facts.userEnrolled) {
      return {
        badge: {
          icon: "check-circle",
          label: "You're enrolled",
          tone: "success",
        },
        confirm: cancelConfirm(facts),
        groupLabel,
        submitIcon: "x-mark",
        submitLabel: "Cancel",
        submitValue: "cancel",
      };
    }

    return {
      badge: { icon: "clock", label: "On the waiting list", tone: "warning" },
      confirm: facts.isEnrollmentAvailable
        ? ""
        : "Enrollment is closed — once you leave the waiting list you cannot rejoin it. Leave anyway?",
      groupLabel,
      submitIcon: "x-mark",
      submitLabel: "Leave",
      submitValue: "cancel",
    };
  }

  return facts.isFull
    ? {
        badge: null,
        confirm: "",
        groupLabel: WAY_IN_GROUP_LABEL,
        submitIcon: "clock",
        submitLabel: "Join waiting list",
        submitValue: "waitlist",
      }
    : {
        badge: null,
        confirm: "",
        groupLabel: WAY_IN_GROUP_LABEL,
        submitIcon: "user-plus",
        submitLabel: "Enroll",
        submitValue: "enroll",
      };
};

export const enrollFooter = (facts: FooterFacts): EnrollFooter => {
  const actions = enrollActions(facts);
  const takesEnrollment = facts.isScheduled && facts.participantsLimit > 0;

  return {
    actions,
    opensAt:
      actions === null && takesEnrollment && !facts.isEnded
        ? facts.opensAt
        : null,
  };
};
