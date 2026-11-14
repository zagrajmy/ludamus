import { Context } from "effect";
import type { Effect, Option } from "effect";

import type { PartyId, PartyMembershipId, UserId } from "../ids.js";
import type {
  MembershipRequest,
  Party,
  PartyByToken,
  PartyConsentMode,
  PartyInvite,
  PartyJoin,
  PartyMembershipStatus,
} from "../party.js";
import type { StoreFailure } from "./store-error.js";

export interface LeaderScope {
  readonly leaderId: UserId;
  readonly partyId: PartyId;
}

export class PartyStore extends Context.Service<
  PartyStore,
  {
    readonly listForViewer: (
      viewerId: UserId
    ) => Effect.Effect<readonly Party[], StoreFailure>;
    readonly readForViewer: (options: {
      readonly partyId: PartyId;
      readonly viewerId: UserId;
    }) => Effect.Effect<Option.Option<Party>, StoreFailure>;
    readonly listInvites: (
      viewerId: UserId
    ) => Effect.Effect<readonly PartyInvite[], StoreFailure>;
    readonly create: (options: {
      readonly leaderId: UserId;
      readonly name: string;
      readonly inviteToken: string;
    }) => Effect.Effect<PartyId, StoreFailure>;
    readonly rename: (
      scope: LeaderScope & { readonly name: string }
    ) => Effect.Effect<boolean, StoreFailure>;
    readonly delete: (
      scope: LeaderScope
    ) => Effect.Effect<boolean, StoreFailure>;
    readonly setInviteToken: (
      scope: LeaderScope & { readonly token: string }
    ) => Effect.Effect<boolean, StoreFailure>;
    readonly readByInviteToken: (options: {
      readonly token: string;
      readonly viewerId: UserId;
    }) => Effect.Effect<Option.Option<PartyByToken>, StoreFailure>;
    readonly joinViaToken: (options: {
      readonly token: string;
      readonly userId: UserId;
    }) => Effect.Effect<Option.Option<PartyJoin>, StoreFailure>;
    readonly createMembershipIfAbsent: (
      request: MembershipRequest
    ) => Effect.Effect<boolean, StoreFailure>;
    readonly acceptInvite: (options: {
      readonly membershipId: PartyMembershipId;
      readonly userId: UserId;
    }) => Effect.Effect<boolean, StoreFailure>;
    readonly declineInvite: (options: {
      readonly membershipId: PartyMembershipId;
      readonly userId: UserId;
    }) => Effect.Effect<boolean, StoreFailure>;
    readonly removeMember: (
      scope: LeaderScope & { readonly membershipId: PartyMembershipId }
    ) => Effect.Effect<Option.Option<PartyMembershipStatus>, StoreFailure>;
    readonly setConsent: (options: {
      readonly userId: UserId;
      readonly partyId: PartyId;
      readonly mode: PartyConsentMode;
    }) => Effect.Effect<boolean, StoreFailure>;
    readonly leave: (options: {
      readonly userId: UserId;
      readonly partyId: PartyId;
    }) => Effect.Effect<boolean, StoreFailure>;
  }
>()("@zagrajmy/core/PartyStore") {}
