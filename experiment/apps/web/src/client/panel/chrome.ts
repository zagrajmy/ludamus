import { Schema } from "effect";

import { Locale } from "../../ui/i18n.js";

export const PanelNav = Schema.Literals([
  "index",
  "cfp",
  "proposals",
  "facilitators",
  "venues",
  "tracks",
  "timetable",
  "settings",
  "event-create",
]);

export type PanelNav = typeof PanelNav.Type;

export const PanelEventRef = Schema.Struct({
  name: Schema.String,
  slug: Schema.String,
});

export type PanelEventRef = typeof PanelEventRef.Type;

export const PanelCurrentEvent = Schema.Struct({
  dateLabel: Schema.String,
  isProposalActive: Schema.Boolean,
  name: Schema.String,
  slug: Schema.String,
});

export type PanelCurrentEvent = typeof PanelCurrentEvent.Type;

export const PanelChromeFlags = Schema.Struct({
  activeNav: PanelNav,
  currentEvent: Schema.OptionFromOptional(PanelCurrentEvent),
  events: Schema.Array(PanelEventRef),
  locale: Locale,
});

export type PanelChromeFlags = typeof PanelChromeFlags.Type;

export const panelCategories = [
  "program",
  "schedule",
  "live",
  "settings",
  "sphere",
] as const;

export const PanelCategory = Schema.Literals(panelCategories);

export type PanelCategory = typeof PanelCategory.Type;

export const PanelChromeModel = Schema.Struct({
  ...PanelChromeFlags.fields,
  collapsed: Schema.Array(PanelCategory),
  dismissedFlashIds: Schema.Array(Schema.String),
  isSidebarOpen: Schema.Boolean,
});

export type PanelChromeModel = typeof PanelChromeModel.Type;

export const initPanelChrome = (flags: PanelChromeFlags): PanelChromeModel => ({
  ...flags,
  collapsed: [],
  dismissedFlashIds: [],
  isSidebarOpen: false,
});

export const eventIndexPath = (slug: string) => `/panel/event/${slug}/`;

export const eventPath = (slug: string, rest: string) =>
  `/panel/event/${slug}/${rest}`;
