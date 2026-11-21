import { EnrollmentForm } from "@zagrajmy/core/contracts";
import { Schema } from "effect";

import { AvatarPerson } from "../../ui/avatar.js";
import { Locale } from "../../ui/i18n.js";

export const EnrollPageRow = Schema.Struct({
  avatar: AvatarPerson,
  userId: Schema.Int,
});

export type EnrollPageRow = typeof EnrollPageRow.Type;

export const EnrollPageFlags = Schema.Struct({
  avatars: Schema.Array(EnrollPageRow),
  coverUrl: Schema.OptionFromOptional(Schema.String),
  descriptionHtml: Schema.String,
  eventUrl: Schema.String,
  form: EnrollmentForm,
  locale: Locale,
  partiesUrl: Schema.String,
  partyParam: Schema.NullOr(Schema.String),
  presenterAvatar: Schema.OptionFromOptional(AvatarPerson),
  shadowbanDates: Schema.Array(Schema.String),
  whenLabel: Schema.String,
});

export type EnrollPageFlags = typeof EnrollPageFlags.Type;
