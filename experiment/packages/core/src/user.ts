import { Schema } from "effect";

import { UserId } from "./ids.js";

export const AgeBand = Schema.Literals(["unknown", "13_15", "16_plus"]);

export type AgeBand = typeof AgeBand.Type;

export const UserType = Schema.Literals(["active", "connected", "anonymous"]);

export type UserType = typeof UserType.Type;

export const DEFAULT_USER_NAME = "Andrzej";

export const UserSummary = Schema.Struct({
  avatarUrl: Schema.String,
  email: Schema.String,
  id: UserId,
  managerId: Schema.NullOr(UserId),
  name: Schema.String,
  slug: Schema.String,
  useGravatar: Schema.Boolean,
  userType: UserType,
  username: Schema.String,
});

export type UserSummary = typeof UserSummary.Type;

export const User = Schema.Struct({
  ...UserSummary.fields,
  ageBand: AgeBand,
  dateJoined: Schema.DateTimeUtc,
  discordUsername: Schema.String,
  emailVerified: Schema.Boolean,
  isActive: Schema.Boolean,
  isStaff: Schema.Boolean,
  isSuperuser: Schema.Boolean,
  pendingEmail: Schema.String,
});

export type User = typeof User.Type;

export const Sponsorship = Schema.Struct({
  memberId: UserId,
  sponsor: UserSummary,
});

export type Sponsorship = typeof Sponsorship.Type;

export const fullName = (user: { readonly name: string }) =>
  user.name === "" ? DEFAULT_USER_NAME : user.name;
