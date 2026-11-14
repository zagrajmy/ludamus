import { Option } from "effect";

import type { EventsFeedFlags } from "../src/client/events-feed/flags.js";
import { init } from "../src/client/init.js";
import { PageFlags } from "../src/client/model.js";
import type { Flags, Model } from "../src/client/model.js";
import type { ShellFlags, ShellViewer } from "../src/client/shell/flags.js";
import type { DateLeaf } from "../src/ui/date-leaf.js";
import { EncounterAttendance, FeedItem } from "../src/ui/feed-card.js";
import type { FeedEncounterCard, FeedEventCard } from "../src/ui/feed-card.js";

export const leaf: DateLeaf = {
  band: "nov 2031",
  bandIsLong: true,
  datetime: "2031-11-09T13:00:00+01:00",
  day: "9",
  hour: "13:00",
  isOngoing: false,
  isRange: false,
  isSunday: true,
  isToday: false,
  label: "Nov 9, 2031, 1 p.m. – 6 p.m.",
  weekday: "Sun",
};

export const shellFlags = (
  overrides: Partial<ShellFlags> = {}
): ShellFlags => ({
  analyticsEnabled: false,
  flashes: [],
  isRootSphere: false,
  links: {
    about: "http://localhost:8000/about/",
    board: Option.none(),
    brand: "/brand/",
    dashboard: "http://localhost:8000/dashboard/",
    home: "http://localhost:8000/",
    login: "/crowd/auth0/do/login?next=http%3A%2F%2Fcrew.localhost%3A8000%2F",
    logout: "/crowd/auth0/do/logout",
    panel: Option.none(),
    profile: "/crowd/profile/",
    sphere: "http://crew.localhost:8000/",
  },
  locale: "en",
  notifications: Option.none(),
  requestUrl: "http://crew.localhost:8000/",
  sphere: {
    domain: "crew.localhost:8000",
    logoUrl: Option.none(),
    name: "Crew Sphere",
  },
  supportEmail: "support@example.com",
  viewer: Option.none(),
  year: 2026,
  ...overrides,
});

export const player: ShellViewer = {
  avatarUrl: Option.none(),
  email: "player@example.com",
  hasPanelAccess: false,
  name: "Ola Player",
};

export const manager: ShellViewer = {
  ...player,
  hasPanelAccess: true,
  name: "Mira Manager",
};

export const eventCard = (
  overrides: Partial<FeedEventCard> = {}
): FeedEventCard => ({
  coverUrl: "/static/placeholder-images/01.webp",
  descriptionText: "Three days of board games.",
  isLinkOnly: false,
  isProposalActive: false,
  isUnpublished: false,
  leaf,
  name: "Harvest Convention",
  sessionCount: 2,
  slug: "harvest-convention",
  ...overrides,
});

export const encounterCard = (
  overrides: Partial<FeedEncounterCard> = {}
): FeedEncounterCard => ({
  attendance: EncounterAttendance.SpotsLeft({ left: 4 }),
  coverUrl: "/static/placeholder-images/02.webp",
  game: Option.some("Memoir '44"),
  isMine: false,
  isPublic: true,
  leaf,
  organizerName: Option.some("Tester"),
  place: Option.some("Tester's place"),
  shareCode: "FEED01",
  title: "Late Night Tactics",
  ...overrides,
});

export const feedFlags = (
  overrides: Partial<EventsFeedFlags> = {}
): EventsFeedFlags => ({
  announcements: [],
  canCreateEncounter: false,
  past: [],
  showHidden: false,
  upcoming: [],
  ...overrides,
});

export const feedItem = {
  encounter: (card: FeedEncounterCard) => FeedItem.Encounter({ card }),
  event: (card: FeedEventCard) => FeedItem.Event({ card }),
};

export const modelFor = (flags: Flags): Model =>
  init(flags, {
    hash: Option.none(),
    host: "crew.localhost",
    pathname: "/",
    port: Option.some("8000"),
    protocol: "http:",
    search: Option.none(),
  }).model;

export const feedModel = (
  options: {
    readonly feed?: Partial<EventsFeedFlags>;
    readonly shell?: Partial<ShellFlags>;
  } = {}
) =>
  modelFor({
    page: PageFlags.EventsFeed({ flags: feedFlags(options.feed) }),
    shell: shellFlags(options.shell),
  });
