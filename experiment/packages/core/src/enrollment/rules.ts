import { DateTime } from "effect";

import { UNLIMITED_SLOTS } from "./schemas.js";
import type { PromotionState, WaitingParticipant } from "./schemas.js";

export const MEMBERSHIP_CHECK_INTERVAL_MINUTES = 15;

export const effectiveSlotOwner = (participant: WaitingParticipant): number =>
  participant.sponsorId ?? participant.userId;

export const promotionGroupKey = (participant: WaitingParticipant): string => {
  if (participant.partyId !== null) {
    return `party:${participant.partyId}`;
  }

  return `owner:${effectiveSlotOwner(participant)}`;
};

export const isEligibleForPromotion = (options: {
  readonly participant: WaitingParticipant;
  readonly presenterId: number | null;
  readonly shadowbannedUserIds: readonly number[];
}): boolean => {
  const { participant, presenterId, shadowbannedUserIds } = options;

  return (
    participant.userId !== presenterId &&
    !participant.hasConflict &&
    !shadowbannedUserIds.includes(participant.userId)
  );
};

export const groupIntoParties = (
  waiting: readonly WaitingParticipant[]
): readonly (readonly WaitingParticipant[])[] => {
  const parties = new Map<string, WaitingParticipant[]>();

  for (const participant of waiting) {
    const key = promotionGroupKey(participant);
    const party = parties.get(key) ?? [];
    party.push(participant);
    parties.set(key, party);
  }

  return [...parties.values()];
};

const initialSlotsByOwner = (
  waiting: readonly WaitingParticipant[]
): Map<number, number> => {
  const slots = new Map<number, number>();

  for (const participant of waiting) {
    if (!slots.has(participant.recipientUserId)) {
      slots.set(participant.recipientUserId, participant.ownerSlotsRemaining);
    }
  }

  return slots;
};

const countByRecipient = (
  members: readonly WaitingParticipant[]
): Map<number, number> => {
  const counts = new Map<number, number>();

  for (const member of members) {
    counts.set(
      member.recipientUserId,
      (counts.get(member.recipientUserId) ?? 0) + 1
    );
  }

  return counts;
};

type MembershipSlotAction = "fits" | "skip" | "stop";

const membershipSlotAction = (
  eligible: readonly WaitingParticipant[],
  slotsByOwner: ReadonlyMap<number, number>
): MembershipSlotAction => {
  const shortfall = [...countByRecipient(eligible)]
    .filter(([owner, needed]) => needed > (slotsByOwner.get(owner) ?? 0))
    .map(([owner]) => owner);

  if (shortfall.length === 0) {
    return "fits";
  }

  if (shortfall.every((owner) => (slotsByOwner.get(owner) ?? 0) <= 0)) {
    return "skip";
  }

  return "stop";
};

export const selectPromotableParties = (
  state: PromotionState
): readonly (readonly WaitingParticipant[])[] => {
  let seatsRemaining = state.availableSeats;
  const selected: (readonly WaitingParticipant[])[] = [];
  const slotsByOwner = initialSlotsByOwner(state.waiting);

  for (const party of groupIntoParties(state.waiting)) {
    const eligible = party.filter((participant) =>
      isEligibleForPromotion({
        participant,
        presenterId: state.presenterId,
        shadowbannedUserIds: state.shadowbannedUserIds,
      })
    );

    if (eligible.length === 0) {
      continue;
    }

    const action = membershipSlotAction(eligible, slotsByOwner);

    if (action === "skip") {
      continue;
    }

    if (action === "stop" || eligible.length > seatsRemaining) {
      break;
    }

    selected.push(eligible);
    seatsRemaining -= eligible.length;

    for (const [owner, count] of countByRecipient(eligible)) {
      slotsByOwner.set(owner, (slotsByOwner.get(owner) ?? 0) - count);
    }
  }

  return selected;
};

export const isValidWindowPeriod = (period: {
  readonly startTime: DateTime.DateTime;
  readonly endTime: DateTime.DateTime;
}): boolean => DateTime.isLessThan(period.startTime, period.endTime);

export const distinctRecipients = (
  candidates: Iterable<number>
): readonly number[] => [...new Set(candidates)];

export const allowedSlots = (config: {
  readonly userSlots: number;
  readonly domainSlots: number;
}): number => config.userSlots + config.domainSlots;

export const canEnrollUsers = (options: {
  readonly occupyingUserIds: readonly number[];
  readonly userIdsToEnroll: readonly number[];
  readonly allowedSlots: number;
}): boolean => {
  const total = new Set([
    ...options.occupyingUserIds,
    ...options.userIdsToEnroll,
  ]);

  return total.size <= options.allowedSlots;
};

export const usedSlots = (occupyingUserIds: readonly number[]): number =>
  new Set(occupyingUserIds).size;

export const availableAllowance = (options: {
  readonly occupyingUserIds: readonly number[];
  readonly allowedSlots: number;
}): number =>
  Math.max(0, options.allowedSlots - usedSlots(options.occupyingUserIds));

export const ownerSlotsRemaining = (options: {
  readonly ownerEmail: string;
  readonly userAllowed: ReadonlyMap<string, number>;
  readonly domainAllowed: ReadonlyMap<string, number>;
  readonly occupyingHouseholdUserIds: readonly number[];
}): number => {
  const { ownerEmail, userAllowed, domainAllowed } = options;

  if (ownerEmail === "") {
    return UNLIMITED_SLOTS;
  }

  const at = ownerEmail.indexOf("@");
  const domain = at === -1 ? "" : (ownerEmail.split("@")[1] ?? "");

  const hasConfig =
    userAllowed.has(ownerEmail) || (domain !== "" && domainAllowed.has(domain));

  if (!hasConfig) {
    return UNLIMITED_SLOTS;
  }

  const allowed =
    (userAllowed.get(ownerEmail) ?? 0) +
    (domain === "" ? 0 : (domainAllowed.get(domain) ?? 0));

  return Math.max(0, allowed - usedSlots(options.occupyingHouseholdUserIds));
};
