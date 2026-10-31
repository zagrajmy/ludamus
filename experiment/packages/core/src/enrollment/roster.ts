import type { ParticipationStatus } from "../participation.js";
import type { EnrollmentRow, RosterPerson } from "./api.js";

export type RosterChoice = "enroll" | "waitlist" | "cancel";

export const INCLUDE_VALUE = "include";

export interface RosterFacts {
  readonly person: RosterPerson;
  readonly isViewer: boolean;
  readonly isMember: boolean;
  readonly needsAccept: boolean;
  readonly memberCanEnroll: boolean;
  readonly status: ParticipationStatus | null;
  readonly hasConflict: boolean;
  readonly hasTimeConflict: boolean;
  readonly waitingSessions: number;
}

export interface FormPolicy {
  readonly userCanEnroll: boolean;
  readonly restrictedOut: boolean;
  readonly maxWaitlistSessions: number;
}

const canJoinWaitlist = (facts: RosterFacts, policy: FormPolicy): boolean =>
  policy.maxWaitlistSessions !== 0 &&
  facts.waitingSessions < policy.maxWaitlistSessions;

const defaultChoices = (options: {
  readonly userCanEnroll: boolean;
  readonly canJoinWl: boolean;
  readonly hasConflict: boolean;
}): readonly RosterChoice[] => {
  if (options.hasConflict) {
    return options.canJoinWl ? ["waitlist"] : [];
  }

  return [
    ...(options.userCanEnroll ? (["enroll"] as const) : []),
    ...(options.canJoinWl ? (["waitlist"] as const) : []),
  ];
};

const heldSeatChoices = (
  facts: RosterFacts,
  policy: FormPolicy
): readonly RosterChoice[] => {
  if (facts.status !== null) {
    return facts.status === "offered" ? ["cancel"] : [];
  }

  if (facts.hasConflict || !policy.userCanEnroll || !facts.memberCanEnroll) {
    return [];
  }

  return ["enroll"];
};

const ownChoices = (
  facts: RosterFacts,
  policy: FormPolicy
): readonly RosterChoice[] => {
  const canJoinWl = canJoinWaitlist(facts, policy);

  if (facts.status === "confirmed") {
    return canJoinWl ? ["cancel", "waitlist"] : ["cancel"];
  }

  if (facts.status === "waiting") {
    return policy.userCanEnroll ? ["cancel", "enroll"] : ["cancel"];
  }

  if (facts.status === "offered") {
    return ["cancel"];
  }

  return defaultChoices({
    canJoinWl,
    hasConflict: facts.hasConflict,
    userCanEnroll: policy.userCanEnroll,
  });
};

export const rosterChoices = (
  facts: RosterFacts,
  policy: FormPolicy
): readonly RosterChoice[] => {
  if (facts.needsAccept) {
    return heldSeatChoices(facts, policy);
  }

  if (facts.isMember) {
    if (facts.status !== null || !facts.memberCanEnroll) {
      return [];
    }

    return defaultChoices({
      canJoinWl: canJoinWaitlist(facts, policy),
      hasConflict: facts.hasConflict,
      userCanEnroll: policy.userCanEnroll,
    });
  }

  return ownChoices(facts, policy);
};

const badge = (facts: RosterFacts): EnrollmentRow["badge"] => {
  const offered = facts.status === "offered";

  if (facts.status === "confirmed") {
    return { label: "Already enrolled", variant: "success" };
  }

  if (offered && facts.needsAccept) {
    return { label: "Seat held — awaiting their approval", variant: "warning" };
  }

  if (offered) {
    return { label: "Spot offered", variant: "warning" };
  }

  if (facts.status === "waiting") {
    return { label: "On the waiting list", variant: "warning" };
  }

  if (facts.hasTimeConflict) {
    return { label: "Time conflict", variant: "danger" };
  }

  if (facts.isMember && !facts.memberCanEnroll) {
    return { label: "Access required", variant: "muted" };
  }

  return { label: "Available", variant: "muted" };
};

const notAvailableReason = (
  facts: RosterFacts,
  includable: boolean
): string => {
  if (facts.hasTimeConflict) {
    return "Time conflict";
  }

  if (!facts.memberCanEnroll || (facts.isMember && !includable)) {
    return "Access required";
  }

  return includable ? "" : "Enrollment not available";
};

export const rosterRow = (
  facts: RosterFacts,
  choices: readonly RosterChoice[]
): EnrollmentRow => {
  const shown = badge(facts);

  const person = {
    avatarUrl: facts.person.avatarUrl,
    email: facts.person.email,
    name: facts.person.name,
    useGravatar: facts.person.useGravatar,
  };

  const common = {
    badge: shown,
    isViewer: facts.isViewer,
    person,
    userId: facts.person.id,
  };

  if (facts.status !== null) {
    const disabled = !choices.includes("cancel");

    return {
      ...common,
      boxChecked: true,
      checked: true,
      disabled,
      needsApproval: false,
      occupiesSeat: facts.status !== "waiting",
      reason: disabled ? "They manage their own enrollment" : "",
    };
  }

  const includable = choices.includes("enroll") || choices.includes("waitlist");
  const reason = notAvailableReason(facts, includable);
  const disabled = reason !== "";

  return {
    ...common,
    boxChecked: facts.isViewer && !disabled,
    checked: false,
    disabled,
    needsApproval: facts.needsAccept && !disabled,
    occupiesSeat: false,
    reason,
  };
};

export interface ChoiceRejection {
  readonly msgid: string;
  readonly vars: Readonly<Record<string, string>>;
}

export const rejectChoice = (options: {
  readonly value: string;
  readonly choices: readonly RosterChoice[];
  readonly policy: FormPolicy;
  readonly personName: string;
  readonly viewerEmail: string;
}): ChoiceRejection | null => {
  const { value, policy } = options;
  const user = options.personName === "" ? "User" : options.personName;

  if (
    value === "" ||
    value === INCLUDE_VALUE ||
    value === "on" ||
    options.choices.some((choice) => choice === value)
  ) {
    return null;
  }

  if (value === "enroll") {
    if (policy.restrictedOut) {
      return {
        msgid:
          options.viewerEmail === ""
            ? "%(user)s cannot enroll: email address required"
            : "%(user)s cannot enroll: enrollment access permission required",
        vars: { user },
      };
    }

    if (!policy.userCanEnroll) {
      return {
        msgid: "%(user)s cannot enroll: enrollment not available",
        vars: { user },
      };
    }
  }

  if (value === "enroll" || value === "waitlist") {
    return {
      msgid:
        "Select a valid choice. %(value)s is not one of the available choices.",
      vars: { value },
    };
  }

  return {
    msgid: "Invalid choice for %(user)s: %(value)s",
    vars: { user, value },
  };
};

export const normalizedChoice = (value: string): string =>
  value === "on" ? INCLUDE_VALUE : value;
