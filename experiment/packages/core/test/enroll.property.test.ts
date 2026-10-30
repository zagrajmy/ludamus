import { describe, expect, it } from "@effect/vitest";
import { Result, Schema } from "effect";
import * as Arbitrary from "effect/Arbitrary";

import {
  EnrollRequestChoice,
  OCCUPYING_PARTICIPATION_STATUSES,
  SessionParticipationStatus,
  actorAvailableSlots,
  canEnroll,
  desiredStateRequests,
  policyEffectiveParticipantsLimit,
  policyForActor,
  processEnrollments,
} from "../src/enrollment/index.js";
import type {
  EnrollSessionState,
  EnrollmentBatch,
  EnrollmentRequest,
  HouseholdMember,
} from "../src/enrollment/index.js";
import { between } from "./support/arbitraries.js";

const Household: readonly number[] = [1, 2, 3, 4];

const UserId = between(1, 4);

const WindowDraft = Schema.Struct({
  allowAnonymousEnrollment: Schema.Boolean,
  maxWaitlistSessions: between(0, 10),
  percentageSlots: between(1, 100),
  restrictToConfiguredUsers: Schema.Boolean,
});

const BatchDraft = Schema.Struct({
  choices: Schema.Array(Schema.NullOr(EnrollRequestChoice)).check(
    Schema.isMinLength(4),
    Schema.isMaxLength(4)
  ),
  conflicted: Schema.Array(UserId).check(Schema.isMaxLength(2)),
  guests: between(0, 2),
  guestsTarget: Schema.NullOr(between(0, 3)),
  members: Schema.Array(Schema.Boolean).check(
    Schema.isMinLength(4),
    Schema.isMaxLength(4)
  ),
  needsAccept: Schema.Array(Schema.Boolean).check(
    Schema.isMinLength(4),
    Schema.isMaxLength(4)
  ),
  others: between(0, 2),
  participantsLimit: between(1, 8),
  partyId: Schema.NullOr(Schema.Literal(7)),
  presenterId: Schema.NullOr(between(1, 5)),
  shadowbanned: Schema.Array(UserId).check(Schema.isMaxLength(2)),
  statuses: Schema.Array(Schema.NullOr(SessionParticipationStatus)).check(
    Schema.isMinLength(4),
    Schema.isMaxLength(4)
  ),
  viewerIsConfigured: Schema.Boolean,
  windows: Schema.Array(WindowDraft).check(Schema.isMaxLength(2)),
});

type BatchDraft = typeof BatchDraft.Type;

interface Batch {
  readonly session: EnrollSessionState;
  readonly requests: readonly EnrollmentRequest[];
  readonly partyId: number | null;
  readonly guestsTarget: number | null;
}

const toBatch = (draft: BatchDraft): Batch => {
  const participations = Household.flatMap((userId, index) => {
    const status = draft.statuses[index] ?? null;

    return status === null ? [] : [{ status, userId }];
  });

  const occupying = participations.filter((row) =>
    OCCUPYING_PARTICIPATION_STATUSES.includes(row.status)
  ).length;

  const requests = Household.flatMap(
    (userId, index): readonly EnrollmentRequest[] => {
      const choice = draft.choices[index] ?? null;
      const isPartyMember = userId !== 1 && (draft.members[index] ?? false);
      const needsAccept = isPartyMember && (draft.needsAccept[index] ?? false);

      return choice === null
        ? []
        : [
            {
              choice: needsAccept && choice === "waitlist" ? "enroll" : choice,
              isPartyMember,
              name: `user-${userId}`,
              needsAccept,
              userId,
            },
          ];
    }
  );

  return {
    guestsTarget: draft.guestsTarget,
    partyId: draft.partyId,
    requests,
    session: {
      conflictedUserIds: [...new Set(draft.conflicted)],
      eligibleWindows: draft.windows,
      enrolledCount: draft.others + occupying + draft.guests,
      guestParticipationIds: Array.from(
        { length: draft.guests },
        (_, index) => 101 + index
      ),
      participantsLimit: draft.participantsLimit,
      participations,
      presenterId: draft.presenterId,
      shadowbannedUserIds: [...new Set(draft.shadowbanned)],
      viewerIsConfigured: draft.viewerIsConfigured,
    },
  };
};

const batches = { batch: Arbitrary.map(Arbitrary.schema(BatchDraft), toBatch) };

const occupiedAfter = (
  session: EnrollSessionState,
  batch: EnrollmentBatch
): number => {
  const rows = new Map<number, string>(
    session.participations.map((row) => [row.userId, row.status])
  );

  const occupies = (status: string | undefined): boolean =>
    status === "confirmed" || status === "offered";

  let occupied = session.enrolledCount;

  for (const write of batch.writes) {
    switch (write._tag) {
      case "Delete": {
        occupied -= occupies(rows.get(write.userId)) ? 1 : 0;
        rows.delete(write.userId);
        break;
      }

      case "Save": {
        occupied +=
          (occupies(write.status) ? 1 : 0) -
          (occupies(rows.get(write.userId)) ? 1 : 0);
        rows.set(write.userId, write.status);
        break;
      }

      case "AddGuests": {
        occupied += write.count;
        break;
      }

      case "RemoveGuest": {
        occupied -= 1;
        break;
      }

      case "HoldSeat": {
        occupied += 1;
        break;
      }
    }
  }

  return occupied;
};

const seatedUserIds = (batch: EnrollmentBatch): readonly number[] =>
  batch.writes.flatMap((write) =>
    (write._tag === "Save" && write.status === "confirmed") ||
    write._tag === "HoldSeat"
      ? [write.userId]
      : []
  );

describe("processEnrollments", () => {
  it.prop(
    "a batch never seats past the room the session's windows offer",
    batches,
    ({ batch }) => {
      const outcome = processEnrollments(batch);

      if (Result.isFailure(outcome)) {
        return;
      }

      const sessionPolicy = policyForActor({
        isConfiguredUser: true,
        windows: batch.session.eligibleWindows,
      });

      const room = canEnroll(sessionPolicy)
        ? policyEffectiveParticipantsLimit({
            participantsLimit: batch.session.participantsLimit,
            policy: sessionPolicy,
          })
        : 0;

      expect(occupiedAfter(batch.session, outcome.success)).toBeLessThanOrEqual(
        Math.max(batch.session.enrolledCount, room)
      );
    }
  );

  it.prop(
    "never seats the presenter or a player they shadowbanned",
    batches,
    ({ batch }) => {
      const outcome = processEnrollments(batch);

      if (Result.isFailure(outcome) || batch.session.presenterId === null) {
        return;
      }

      const barred = new Set([
        batch.session.presenterId,
        ...batch.session.shadowbannedUserIds,
      ]);

      expect(seatedUserIds(outcome.success).some((id) => barred.has(id))).toBe(
        false
      );
    },
    { arbitrary: { runs: 1500 } }
  );

  it.prop(
    "never confirms a seat for someone with a time conflict",
    batches,
    ({ batch }) => {
      const outcome = processEnrollments(batch);

      if (Result.isFailure(outcome)) {
        return;
      }

      const fresh = outcome.success.writes.flatMap((write) =>
        write._tag === "Save" && write.status === "confirmed"
          ? [write.userId]
          : []
      );

      expect(
        fresh.some((id) => batch.session.conflictedUserIds.includes(id))
      ).toBe(false);
    }
  );

  it.prop(
    "writes rows only for the people the request names",
    batches,
    ({ batch }) => {
      const outcome = processEnrollments(batch);

      if (Result.isFailure(outcome)) {
        return;
      }

      const named = new Set(batch.requests.map((req) => req.userId));

      const touched = outcome.success.writes.flatMap((write) =>
        write._tag === "Delete" ||
        write._tag === "Save" ||
        write._tag === "HoldSeat"
          ? [write.userId]
          : []
      );

      expect(touched.every((id) => named.has(id))).toBe(true);
    }
  );

  it.prop("answers every request exactly once", batches, ({ batch }) => {
    const outcome = processEnrollments(batch);

    if (Result.isFailure(outcome)) {
      return;
    }

    const answered =
      outcome.success.cancelledUsers.length +
      outcome.success.skippedUsers.length +
      outcome.success.confirmedUsers.length +
      outcome.success.waitingUsers.length +
      outcome.success.heldSeats.length;

    expect(answered).toBe(batch.requests.length);
  });

  it.prop(
    "a refusal always names more seats asked for than are free",
    batches,
    ({ batch }) => {
      const outcome = processEnrollments(batch);

      if (Result.isFailure(outcome)) {
        expect(outcome.failure.requested).toBeGreaterThan(
          outcome.failure.available
        );
      }
    }
  );
});

const MemberDraft = Schema.Struct({
  choices: Schema.Array(EnrollRequestChoice).check(Schema.isMaxLength(3)),
  desiredIn: Schema.Boolean,
  isActive: Schema.Boolean,
  needsAccept: Schema.Boolean,
  status: Schema.NullOr(SessionParticipationStatus),
});

const DesiredDraft = Schema.Struct({
  companions: between(0, 2),
  conflicted: Schema.Array(between(1, 5)).check(Schema.isMaxLength(2)),
  enrolledExtra: between(0, 3),
  members: Schema.Array(MemberDraft).check(
    Schema.isMinLength(1),
    Schema.isMaxLength(5)
  ),
  participantsLimit: between(1, 6),
  viewerIsConfigured: Schema.Boolean,
  windows: Schema.Array(WindowDraft).check(Schema.isMaxLength(2)),
});

const households = {
  draft: Arbitrary.map(Arbitrary.schema(DesiredDraft), (draft) => {
    const household: readonly HouseholdMember[] = draft.members.map(
      (member, index) => {
        const isMember = index > draft.companions;

        return {
          choices: [...new Set(member.choices)],
          desiredIn: member.desiredIn,
          isActive: member.isActive,
          isMember,
          name: `user-${index + 1}`,
          needsAccept: isMember && member.needsAccept,
          status: member.status,
          userId: index + 1,
        };
      }
    );

    const occupying = household.filter(
      (member) => member.status === "confirmed" || member.status === "offered"
    ).length;

    return {
      conflictedUserIds: draft.conflicted,
      household,
      seating: {
        eligibleWindows: draft.windows,
        enrolledCount: draft.enrolledExtra + occupying,
        participantsLimit: draft.participantsLimit,
        viewerIsConfigured: draft.viewerIsConfigured,
      },
    };
  }),
};

describe("desiredStateRequests", () => {
  it.prop(
    "never asks for more seats than the viewer may fill",
    households,
    ({ draft }) => {
      const requests = desiredStateRequests(draft);

      const freed = requests.filter((req) => {
        const status =
          draft.household.find((m) => m.userId === req.userId)?.status ?? null;

        return (
          req.choice === "cancel" &&
          (status === "confirmed" || status === "offered")
        );
      }).length;

      const seats = requests.filter((req) => req.choice === "enroll").length;
      expect(seats).toBeLessThanOrEqual(
        actorAvailableSlots({ freed, seating: draft.seating })
      );
    }
  );

  it.prop(
    "moves each person at most once, and only active ones",
    households,
    ({ draft }) => {
      const requests = desiredStateRequests(draft);
      const ids = requests.map((req) => req.userId);
      expect(new Set(ids).size).toBe(ids.length);

      const active = new Set(
        draft.household.filter((m) => m.isActive).map((m) => m.userId)
      );

      expect(ids.every((id) => active.has(id))).toBe(true);
    }
  );

  it.prop(
    "cancels only people who are in, and brings in only people who are out",
    households,
    ({ draft }) => {
      for (const req of desiredStateRequests(draft)) {
        const status =
          draft.household.find((m) => m.userId === req.userId)?.status ?? null;

        expect(req.choice === "cancel").toBe(status !== null);
      }
    }
  );
});
