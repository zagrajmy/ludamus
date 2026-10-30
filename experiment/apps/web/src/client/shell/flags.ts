import { Schema } from "effect";

import { Flash } from "../../ui/flash.js";
import { Locale } from "../../ui/i18n.js";

export const ShellSphere = Schema.Struct({
  domain: Schema.String,
  logoUrl: Schema.OptionFromOptional(Schema.String),
  name: Schema.String,
});
export type ShellSphere = typeof ShellSphere.Type;

export const ShellViewer = Schema.Struct({
  avatarUrl: Schema.OptionFromOptional(Schema.String),
  email: Schema.String,
  hasPanelAccess: Schema.Boolean,
  name: Schema.String,
});
export type ShellViewer = typeof ShellViewer.Type;

export const ShellLinks = Schema.Struct({
  about: Schema.String,
  board: Schema.OptionFromOptional(Schema.String),
  brand: Schema.String,
  dashboard: Schema.String,
  home: Schema.String,
  login: Schema.String,
  logout: Schema.String,
  panel: Schema.OptionFromOptional(Schema.String),
  profile: Schema.String,
  sphere: Schema.String,
});
export type ShellLinks = typeof ShellLinks.Type;

export const ShellFlags = Schema.Struct({
  analyticsEnabled: Schema.Boolean,
  flashes: Schema.Array(Flash),
  isRootSphere: Schema.Boolean,
  links: ShellLinks,
  locale: Locale,
  requestUrl: Schema.String,
  sphere: ShellSphere,
  supportEmail: Schema.String,
  viewer: Schema.OptionFromOptional(ShellViewer),
  year: Schema.Int,
});
export type ShellFlags = typeof ShellFlags.Type;
