import { Schema } from "effect";

import { PartyId, PartyMembershipId, UserId } from "./ids.js";
import { UserSummary } from "./user.js";

export const PartyConsentMode = Schema.Literals([
  "accept_by_default",
  "accept_invites",
]);

export type PartyConsentMode = typeof PartyConsentMode.Type;

export const PartyMembershipStatus = Schema.Literals(["active", "invited"]);

export type PartyMembershipStatus = typeof PartyMembershipStatus.Type;

export const PartyMember = Schema.Struct({
  claimToken: Schema.String,
  consentMode: PartyConsentMode,
  membershipId: PartyMembershipId,
  status: PartyMembershipStatus,
  user: UserSummary,
});

export type PartyMember = typeof PartyMember.Type;

export const Party = Schema.Struct({
  createdAt: Schema.DateTimeUtc,
  id: PartyId,
  leader: UserSummary,
  members: Schema.Array(PartyMember),
  name: Schema.String,
});

export type Party = typeof Party.Type;

export const PartyInvite = Schema.Struct({
  leader: UserSummary,
  membershipId: PartyMembershipId,
  partyId: PartyId,
  partyName: Schema.String,
});

export type PartyInvite = typeof PartyInvite.Type;

export const PartyByToken = Schema.Struct({
  alreadyMember: Schema.Boolean,
  id: PartyId,
  leader: UserSummary,
  name: Schema.String,
});

export type PartyByToken = typeof PartyByToken.Type;

export const PartyJoin = Schema.Struct({
  joined: Schema.Boolean,
  partyId: PartyId,
});

export type PartyJoin = typeof PartyJoin.Type;

export const MembershipRequest = Schema.Struct({
  consentMode: PartyConsentMode,
  partyId: PartyId,
  status: PartyMembershipStatus,
  userId: UserId,
});

export type MembershipRequest = typeof MembershipRequest.Type;
