import { DateTime, Duration, Schema } from "effect";
import * as Arbitrary from "effect/Arbitrary";

import { UNLIMITED_SLOTS } from "../../src/enrollment/index.js";
import type {
  EnrollmentWindowRules,
  PromotionState,
  WaitingParticipant,
} from "../../src/enrollment/index.js";

export const BASE = DateTime.makeUnsafe("2026-06-04T12:00:00Z");

export const at = (minutes: number): DateTime.Utc =>
  DateTime.add(BASE, { minutes });

export const between = (minimum: number, maximum: number): Schema.Int =>
  Schema.Int.check(Schema.isBetween({ maximum, minimum }));

const UserId = between(1, 6);

const MemberDraft = Schema.Struct({
  hasConflict: Schema.Boolean,
  partyId: Schema.NullOr(between(1, 2)),
  sponsorId: Schema.NullOr(UserId),
  userId: UserId,
});

const SlotValue = Schema.Literals([0, 1, 2, 3, UNLIMITED_SLOTS]);

const StateDraft = Schema.Struct({
  availableSeats: between(0, 6),
  claimWindowHours: Schema.Literals([0, 1, 24, 48]),
  members: Schema.Array(MemberDraft).check(Schema.isMaxLength(6)),
  presenterId: Schema.NullOr(UserId),
  promotionMode: Schema.Literals(["auto", "offer_claim"]),
  shadowbannedUserIds: Schema.Array(UserId).check(Schema.isMaxLength(2)),
  slots: Schema.Array(SlotValue).check(
    Schema.isMinLength(6),
    Schema.isMaxLength(6)
  ),
  startHours: between(0, 72),
});

type StateDraft = typeof StateDraft.Type;

const toState = (draft: StateDraft): PromotionState => {
  const seen = new Set<number>();
  const waiting: WaitingParticipant[] = [];

  for (const member of draft.members) {
    if (seen.has(member.userId)) {
      continue;
    }

    seen.add(member.userId);

    const sponsorId =
      member.sponsorId === member.userId ? null : member.sponsorId;

    const recipientUserId = sponsorId ?? member.userId;
    waiting.push({
      creationTime: at(waiting.length),
      email: `u${member.userId}@example.com`,
      fullName: `user-${member.userId}`,
      hasConflict: member.hasConflict,
      ownerSlotsRemaining: draft.slots[recipientUserId - 1] ?? UNLIMITED_SLOTS,
      participationId: waiting.length + 1,
      partyId: member.partyId,
      recipientUserId,
      sponsorId,
      userId: member.userId,
    });
  }

  return {
    availableSeats: draft.availableSeats,
    eventSlug: "ev",
    offerClaimWindow: Duration.hours(draft.claimWindowHours),
    presenterId: draft.presenterId,
    promotionMode: draft.promotionMode,
    sessionId: 1,
    sessionTitle: "S",
    shadowbannedUserIds: [...new Set(draft.shadowbannedUserIds)],
    startTime: DateTime.add(BASE, { hours: draft.startHours }),
    waiting,
  };
};

export const promotionStates = Arbitrary.map(
  Arbitrary.schema(StateDraft),
  toState
);

const WindowDraft = Schema.Struct({
  allowAnonymousEnrollment: Schema.Boolean,
  length: between(1, 48),
  limitToEndTime: Schema.Boolean,
  maxWaitlistSessions: between(0, 10),
  percentageSlots: between(1, 100),
  restrictToConfiguredUsers: Schema.Boolean,
  start: between(0, 48),
});

export const EPOCH = DateTime.makeUnsafe("2026-06-01T00:00:00Z");

export const windowLists = Arbitrary.map(
  Arbitrary.schema(Schema.Array(WindowDraft).check(Schema.isMaxLength(4))),
  (drafts): readonly EnrollmentWindowRules[] =>
    drafts.map((draft, index) => ({
      allowAnonymousEnrollment: draft.allowAnonymousEnrollment,
      endTime: DateTime.add(EPOCH, { hours: draft.start + draft.length }),
      limitToEndTime: draft.limitToEndTime,
      maxWaitlistSessions: draft.maxWaitlistSessions,
      percentageSlots: draft.percentageSlots,
      pk: index + 1,
      restrictToConfiguredUsers: draft.restrictToConfiguredUsers,
      startTime: DateTime.add(EPOCH, { hours: draft.start }),
    }))
);
