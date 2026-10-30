import { Option, Result, Schema } from "effect";

import { NotEnoughSpotsError } from "./errors.js";
import {
  OCCUPYING_PARTICIPATION_STATUSES,
  SessionParticipationStatus,
} from "./schemas.js";
import type { EnrollmentWindowLike } from "./schemas.js";
import { canEnroll, policyAvailableSlots, policyForActor } from "./windows.js";

export const EnrollRequestChoice = Schema.Literals([
  "cancel",
  "enroll",
  "waitlist",
]);

export type EnrollRequestChoice = typeof EnrollRequestChoice.Type;

export const EnrollmentRequest = Schema.Struct({
  choice: EnrollRequestChoice,
  isPartyMember: Schema.Boolean,
  name: Schema.String,
  needsAccept: Schema.Boolean,
  userId: Schema.Int,
});

export type EnrollmentRequest = typeof EnrollmentRequest.Type;

export const EnrollmentWindowPolicy = Schema.Struct({
  allowAnonymousEnrollment: Schema.Boolean,
  maxWaitlistSessions: Schema.Int,
  percentageSlots: Schema.Int,
  restrictToConfiguredUsers: Schema.Boolean,
});

export type EnrollmentWindowPolicy = typeof EnrollmentWindowPolicy.Type;

export const SeatAvailability = Schema.Struct({
  eligibleWindows: Schema.Array(EnrollmentWindowPolicy),
  enrolledCount: Schema.Int,
  participantsLimit: Schema.Int,
  viewerIsConfigured: Schema.Boolean,
});

export type SeatAvailability = typeof SeatAvailability.Type;

export const ExistingParticipation = Schema.Struct({
  status: SessionParticipationStatus,
  userId: Schema.Int,
});

export type ExistingParticipation = typeof ExistingParticipation.Type;

export const EnrollSessionState = Schema.Struct({
  ...SeatAvailability.fields,
  conflictedUserIds: Schema.Array(Schema.Int),
  guestParticipationIds: Schema.Array(Schema.Int),
  participations: Schema.Array(ExistingParticipation),
  presenterId: Schema.NullOr(Schema.Int),
  shadowbannedUserIds: Schema.Array(Schema.Int),
});

export type EnrollSessionState = typeof EnrollSessionState.Type;

export const SkipReason = Schema.Literals([
  "session_host",
  "not_available",
  "time_conflict",
  "manages_own_enrollment",
  "no_enrollment_to_cancel",
]);

export type SkipReason = typeof SkipReason.Type;

export const SKIP_REASON_MSGIDS: Readonly<Record<SkipReason, string>> = {
  manages_own_enrollment: "%(name)s (manages their own enrollment)",
  no_enrollment_to_cancel: "%(name)s (no enrollment to cancel)",
  not_available: "%(name)s (not available)",
  session_host: "%(name)s (session host)",
  time_conflict: "%(name)s (time conflict)",
};

export const EnrollmentWrite = Schema.TaggedUnion({
  AddGuests: { count: Schema.Int, partyId: Schema.NullOr(Schema.Int) },
  Delete: { userId: Schema.Int },
  HoldSeat: { partyId: Schema.NullOr(Schema.Int), userId: Schema.Int },
  RemoveGuest: { participationId: Schema.Int },
  Save: {
    created: Schema.Boolean,
    partyId: Schema.NullOr(Schema.Int),
    status: Schema.Literals(["confirmed", "waiting"]),
    userId: Schema.Int,
  },
});

export type EnrollmentWrite = typeof EnrollmentWrite.Type;

const NamedUser = Schema.Struct({ name: Schema.String, userId: Schema.Int });

export const EnrollmentBatch = Schema.Struct({
  cancelledUsers: Schema.Array(Schema.String),
  confirmedUsers: Schema.Array(Schema.String),
  enrolledMemberUserIds: Schema.Array(Schema.Int),
  freedSeat: Schema.Boolean,
  guestTotal: Schema.NullOr(Schema.Int),
  heldSeats: Schema.Array(NamedUser),
  signedUpUsers: Schema.Array(NamedUser),
  skippedUsers: Schema.Array(
    Schema.Struct({ name: Schema.String, reason: SkipReason })
  ),
  waitingUsers: Schema.Array(Schema.String),
  writes: Schema.Array(EnrollmentWrite),
});

export type EnrollmentBatch = typeof EnrollmentBatch.Type;

const isOccupying = (status: SessionParticipationStatus | null): boolean =>
  status !== null && OCCUPYING_PARTICIPATION_STATUSES.includes(status);

const seats = (options: {
  readonly windows: readonly EnrollmentWindowLike[];
  readonly isConfiguredUser: boolean;
  readonly seating: SeatAvailability;
  readonly freed: number;
}): number =>
  policyAvailableSlots({
    enrolledCount: options.seating.enrolledCount - options.freed,
    participantsLimit: options.seating.participantsLimit,
    policy: policyForActor({
      isConfiguredUser: options.isConfiguredUser,
      windows: options.windows,
    }),
  });

export const actorAvailableSlots = (options: {
  readonly seating: SeatAvailability;
  readonly freed: number;
}): number =>
  seats({
    freed: options.freed,
    isConfiguredUser: options.seating.viewerIsConfigured,
    seating: options.seating,
    windows: options.seating.eligibleWindows,
  });

export const checkCapacity = (options: {
  readonly session: EnrollSessionState;
  readonly requests: readonly EnrollmentRequest[];
  readonly guestSeatsNeeded: number;
  readonly guestSeatsFreed: number;
}): Option.Option<NotEnoughSpotsError> => {
  const { session, requests } = options;
  const memberCount = requests.filter((req) => req.choice === "enroll").length;
  const enrollCount = memberCount + options.guestSeatsNeeded;

  if (enrollCount === 0) {
    return Option.none();
  }

  const cancelling = new Set(
    requests.filter((req) => req.choice === "cancel").map((req) => req.userId)
  );

  const freedSpots =
    options.guestSeatsFreed +
    session.participations.filter(
      (row) => cancelling.has(row.userId) && isOccupying(row.status)
    ).length;

  const sessionPolicy = policyForActor({
    isConfiguredUser: true,
    windows: session.eligibleWindows,
  });

  const availableSpots = canEnroll(sessionPolicy)
    ? seats({
        freed: freedSpots,
        isConfiguredUser: true,
        seating: session,
        windows: session.eligibleWindows,
      })
    : freedSpots;

  const memberSpots = actorAvailableSlots({
    freed: freedSpots,
    seating: session,
  });

  if (memberCount > memberSpots) {
    return Option.some(
      new NotEnoughSpotsError({
        available: memberSpots,
        blameGuests: false,
        requested: memberCount,
      })
    );
  }

  if (enrollCount > availableSpots) {
    return Option.some(
      new NotEnoughSpotsError({
        available: availableSpots,
        blameGuests: true,
        requested: enrollCount,
      })
    );
  }

  return Option.none();
};

const STATUS_BY_CHOICE = {
  enroll: "confirmed",
  waitlist: "waiting",
} as const;

interface Ledger {
  readonly rows: Map<number, SessionParticipationStatus | null>;
  readonly writes: EnrollmentWrite[];
  readonly cancelledUsers: string[];
  readonly confirmedUsers: string[];
  readonly waitingUsers: string[];
  readonly skippedUsers: { name: string; reason: SkipReason }[];
  readonly signedUpUsers: { name: string; userId: number }[];
  readonly heldSeats: { name: string; userId: number }[];
  readonly enrolledMemberUserIds: number[];
  freedSeat: boolean;
}

const cancel = (options: {
  readonly ledger: Ledger;
  readonly req: EnrollmentRequest;
  readonly snapshot: readonly ExistingParticipation[];
}): void => {
  const { ledger, req } = options;
  const existing = options.snapshot.find((row) => row.userId === req.userId);

  if (existing === undefined) {
    ledger.skippedUsers.push({
      name: req.name,
      reason: "no_enrollment_to_cancel",
    });

    return;
  }

  if (isOccupying(existing.status)) {
    ledger.freedSeat = true;
  }

  ledger.rows.delete(req.userId);
  ledger.writes.push({ _tag: "Delete", userId: req.userId });
  ledger.cancelledUsers.push(req.name);
};

const join = (options: {
  readonly ledger: Ledger;
  readonly req: EnrollmentRequest & { readonly choice: "enroll" | "waitlist" };
  readonly session: EnrollSessionState;
  readonly shadowbanned: readonly number[];
  readonly partyId: number | null;
}): void => {
  const { ledger, req, session } = options;

  if (session.presenterId !== null && req.userId === session.presenterId) {
    ledger.skippedUsers.push({ name: req.name, reason: "session_host" });

    return;
  }

  if (options.shadowbanned.includes(req.userId)) {
    ledger.skippedUsers.push({ name: req.name, reason: "not_available" });

    return;
  }

  if (
    req.choice === "enroll" &&
    session.conflictedUserIds.includes(req.userId)
  ) {
    ledger.skippedUsers.push({ name: req.name, reason: "time_conflict" });

    return;
  }

  const isFreshSignup = !ledger.rows.has(req.userId);

  if (req.needsAccept) {
    if (!isFreshSignup) {
      ledger.skippedUsers.push({
        name: req.name,
        reason: "manages_own_enrollment",
      });

      return;
    }

    ledger.heldSeats.push({ name: req.name, userId: req.userId });
    ledger.signedUpUsers.push({ name: req.name, userId: req.userId });

    return;
  }

  const status = STATUS_BY_CHOICE[req.choice];
  ledger.rows.set(req.userId, status);
  ledger.writes.push({
    _tag: "Save",
    created: isFreshSignup,
    partyId: options.partyId,
    status,
    userId: req.userId,
  });

  if (req.isPartyMember && isFreshSignup) {
    ledger.enrolledMemberUserIds.push(req.userId);
  }

  (status === "confirmed" ? ledger.confirmedUsers : ledger.waitingUsers).push(
    req.name
  );

  if (isFreshSignup) {
    ledger.signedUpUsers.push({ name: req.name, userId: req.userId });
  }
};

const isJoin = (
  req: EnrollmentRequest
): req is EnrollmentRequest & { readonly choice: "enroll" | "waitlist" } =>
  req.choice !== "cancel";

export const processEnrollments = (options: {
  readonly session: EnrollSessionState;
  readonly requests: readonly EnrollmentRequest[];
  readonly partyId: number | null;
  readonly guestsTarget: number | null;
}): Result.Result<EnrollmentBatch, NotEnoughSpotsError> => {
  const { session, requests, partyId } = options;

  const guestsDelta =
    options.guestsTarget === null
      ? 0
      : options.guestsTarget - session.guestParticipationIds.length;

  const guestSeatsNeeded = Math.max(guestsDelta, 0);
  const guestSeatsFreed = Math.max(-guestsDelta, 0);

  const capacity = checkCapacity({
    guestSeatsFreed,
    guestSeatsNeeded,
    requests,
    session,
  });

  if (Option.isSome(capacity)) {
    return Result.fail(capacity.value);
  }

  const ledger: Ledger = {
    cancelledUsers: [],
    confirmedUsers: [],
    enrolledMemberUserIds: [],
    freedSeat: false,
    heldSeats: [],
    rows: new Map(
      session.participations.map((row) => [row.userId, row.status])
    ),
    signedUpUsers: [],
    skippedUsers: [],
    waitingUsers: [],
    writes: [],
  };

  const shadowbanned =
    session.presenterId === null ? [] : session.shadowbannedUserIds;

  const ordered = [
    ...requests.filter((req) => req.choice === "cancel"),
    ...requests.filter((req) => req.choice !== "cancel"),
  ];

  for (const req of ordered) {
    if (isJoin(req)) {
      join({ ledger, partyId, req, session, shadowbanned });
    } else {
      cancel({ ledger, req, snapshot: session.participations });
    }
  }

  let guestTotal: number | null = null;

  if (guestSeatsNeeded > 0 || guestSeatsFreed > 0) {
    if (guestSeatsNeeded > 0) {
      ledger.writes.push({
        _tag: "AddGuests",
        count: guestSeatsNeeded,
        partyId,
      });
    }

    const doomed =
      guestSeatsFreed > 0
        ? session.guestParticipationIds.slice(-guestSeatsFreed)
        : [];

    for (const participationId of doomed) {
      ledger.writes.push({ _tag: "RemoveGuest", participationId });
    }

    if (guestSeatsFreed > 0) {
      ledger.freedSeat = true;
    }

    guestTotal =
      session.guestParticipationIds.length + guestSeatsNeeded - doomed.length;
  }

  for (const held of ledger.heldSeats) {
    ledger.writes.push({ _tag: "HoldSeat", partyId, userId: held.userId });
  }

  return Result.succeed({
    cancelledUsers: ledger.cancelledUsers,
    confirmedUsers: ledger.confirmedUsers,
    enrolledMemberUserIds: ledger.enrolledMemberUserIds,
    freedSeat: ledger.freedSeat,
    guestTotal,
    heldSeats: ledger.heldSeats,
    signedUpUsers: ledger.signedUpUsers,
    skippedUsers: ledger.skippedUsers,
    waitingUsers: ledger.waitingUsers,
    writes: ledger.writes,
  });
};

export const HouseholdMember = Schema.Struct({
  choices: Schema.Array(EnrollRequestChoice),
  desiredIn: Schema.Boolean,
  isActive: Schema.Boolean,
  isMember: Schema.Boolean,
  name: Schema.String,
  needsAccept: Schema.Boolean,
  status: Schema.NullOr(SessionParticipationStatus),
  userId: Schema.Int,
});

export type HouseholdMember = typeof HouseholdMember.Type;

export const routeWantsIn = (options: {
  readonly wantsIn: readonly HouseholdMember[];
  readonly available: number;
}): readonly EnrollmentRequest[] => {
  let { available } = options;
  const routed: EnrollmentRequest[] = [];

  for (const member of options.wantsIn) {
    const hasRoom = available > 0;
    let choice: "enroll" | "waitlist";

    if (member.needsAccept) {
      if (!hasRoom) {
        continue;
      }

      choice = "enroll";
    } else if (hasRoom && member.choices.includes("enroll")) {
      choice = "enroll";
    } else if (member.choices.includes("waitlist")) {
      choice = "waitlist";
    } else {
      continue;
    }

    if (choice === "enroll") {
      available -= 1;
    }

    routed.push({
      choice,
      isPartyMember: member.isMember,
      name: member.name,
      needsAccept: member.needsAccept,
      userId: member.userId,
    });
  }

  return routed;
};

export const desiredStateRequests = (options: {
  readonly household: readonly HouseholdMember[];
  readonly conflictedUserIds: readonly number[];
  readonly seating: SeatAvailability;
}): readonly EnrollmentRequest[] => {
  const cancels: EnrollmentRequest[] = [];
  const wantsIn: HouseholdMember[] = [];
  let freed = 0;

  for (const member of options.household.filter((m) => m.isActive)) {
    const currentlyIn = member.status !== null;

    if (member.desiredIn) {
      if (currentlyIn || options.conflictedUserIds.includes(member.userId)) {
        continue;
      }

      if (
        member.choices.includes("enroll") ||
        member.choices.includes("waitlist")
      ) {
        wantsIn.push(member);
      }
    } else if (currentlyIn && member.choices.includes("cancel")) {
      cancels.push({
        choice: "cancel",
        isPartyMember: member.isMember,
        name: member.name,
        needsAccept: member.needsAccept,
        userId: member.userId,
      });

      if (isOccupying(member.status)) {
        freed += 1;
      }
    }
  }

  return [
    ...cancels,
    ...routeWantsIn({
      available: actorAvailableSlots({ freed, seating: options.seating }),
      wantsIn,
    }),
  ];
};

export const ExplicitChoice = Schema.Literals([
  "cancel",
  "enroll",
  "waitlist",
  "include",
]);

export type ExplicitChoice = typeof ExplicitChoice.Type;

export const explicitRequests = (
  household: readonly {
    readonly userId: number;
    readonly name: string;
    readonly isActive: boolean;
    readonly isMember: boolean;
    readonly needsAccept: boolean;
    readonly choice: ExplicitChoice | null;
  }[]
): readonly EnrollmentRequest[] =>
  household.flatMap((member) =>
    member.isActive && member.choice !== null && member.choice !== "include"
      ? [
          {
            choice: member.choice,
            isPartyMember: member.isMember,
            name: member.name,
            needsAccept: member.needsAccept,
            userId: member.userId,
          },
        ]
      : []
  );

export interface EnrollmentMessage {
  readonly level: "success" | "warning";
  readonly msgid: string;
  readonly names: readonly string[];
}

export const enrollmentMessages = (
  batch: EnrollmentBatch
): readonly EnrollmentMessage[] => {
  const groups: readonly EnrollmentMessage[] = [
    { level: "success", msgid: "Enrolled: {}", names: batch.confirmedUsers },
    {
      level: "success",
      msgid: "Added to waiting list: {}",
      names: batch.waitingUsers,
    },
    {
      level: "success",
      msgid: "Seat held (awaiting their approval): {}",
      names: batch.heldSeats.map((held) => held.name),
    },
    { level: "success", msgid: "Cancelled: {}", names: batch.cancelledUsers },
    {
      level: "warning",
      msgid: "Skipped (already enrolled or conflicts): {}",
      names: batch.skippedUsers.map((skipped) =>
        SKIP_REASON_MSGIDS[skipped.reason].replace("%(name)s", skipped.name)
      ),
    },
  ];

  const guests: readonly EnrollmentMessage[] =
    batch.guestTotal === null
      ? []
      : [
          {
            level: "success",
            msgid: "Guests you bring: {}",
            names: [String(batch.guestTotal)],
          },
        ];

  return [...groups.filter((group) => group.names.length > 0), ...guests];
};
