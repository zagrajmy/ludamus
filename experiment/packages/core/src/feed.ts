import { Schema } from "effect";

export const SqliteFlag = Schema.Literals([0, 1]);

export const FeedEventRow = Schema.Struct({
  coverImage: Schema.String,
  description: Schema.String,
  endTime: Schema.String,
  id: Schema.Int,
  name: Schema.String,
  proposalEndTime: Schema.NullOr(Schema.String),
  proposalStartTime: Schema.NullOr(Schema.String),
  publicationTime: Schema.NullOr(Schema.String),
  sessionCount: Schema.Int,
  slug: Schema.String,
  startTime: Schema.String,
  visibility: Schema.String,
});

export type FeedEventRow = typeof FeedEventRow.Type;

export const FeedEncounterRow = Schema.Struct({
  creatorId: Schema.Int,
  creatorName: Schema.String,
  endTime: Schema.NullOr(Schema.String),
  game: Schema.String,
  headerImage: Schema.String,
  id: Schema.Int,
  isPublic: SqliteFlag,
  maxParticipants: Schema.Int,
  place: Schema.String,
  rsvpCount: Schema.Int,
  shareCode: Schema.String,
  startTime: Schema.String,
  title: Schema.String,
});

export type FeedEncounterRow = typeof FeedEncounterRow.Type;

export const AnnouncementRow = Schema.Struct({
  content: Schema.String,
  id: Schema.Int,
  title: Schema.String,
});

export type AnnouncementRow = typeof AnnouncementRow.Type;

export const EncountersPolicy = Schema.Literals([
  "everyone",
  "managers",
  "none",
]);

export type EncountersPolicy = typeof EncountersPolicy.Type;

export const SphereChromeRow = Schema.Struct({
  domain: Schema.String,
  encountersPolicy: EncountersPolicy,
  id: Schema.Int,
  logo: Schema.String,
  name: Schema.String,
  siteId: Schema.Int,
});

export type SphereChromeRow = typeof SphereChromeRow.Type;

export const ViewerChromeRow = Schema.Struct({
  avatarUrl: Schema.String,
  email: Schema.String,
  id: Schema.Int,
  isSuperuser: SqliteFlag,
  name: Schema.String,
  sphereRole: Schema.NullOr(Schema.String),
  useGravatar: SqliteFlag,
  username: Schema.String,
});

export type ViewerChromeRow = typeof ViewerChromeRow.Type;

export const LandingStatsRow = Schema.Struct({
  events: Schema.Int,
  sessions: Schema.Int,
});

export type LandingStatsRow = typeof LandingStatsRow.Type;

export const LandingConventionRow = Schema.Struct({
  coverImage: Schema.String,
  domain: Schema.String,
  eventSlug: Schema.String,
  name: Schema.String,
});

export type LandingConventionRow = typeof LandingConventionRow.Type;
