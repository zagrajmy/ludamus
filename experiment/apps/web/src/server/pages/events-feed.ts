import type { FeedEncounterRow, FeedEventRow } from "@zagrajmy/core/feed";
import { FeedStore } from "@zagrajmy/core/ports/feed-store";
import { dateLeaf } from "@zagrajmy/i18n";
import type { DateLeaf } from "@zagrajmy/i18n";
import { Effect, Option } from "effect";

import type { EventsFeedFlags } from "../../client/events-feed/flags.js";
import { EncounterAttendance, FeedItem } from "../../ui/feed-card.js";
import {
  parseStoredInstant,
  isBefore,
  storedTimestamp,
} from "../format/instant.js";
import type { Instant } from "../format/instant.js";
import { markdownToPlainText } from "../markdown.js";
import { mediaUrl, placeholderCoverUrl } from "../request-context.js";
import type { RequestContext } from "../request-context.js";

export const pastFeedLimit = 24;

const epochZero: Instant = { epochMillis: 0, microsecond: 0 };

const instantOf = (stored: string) =>
  Option.getOrElse(parseStoredInstant(stored), () => epochZero);

const optionalInstant = (stored: string | null) =>
  stored === null
    ? undefined
    : Option.getOrUndefined(parseStoredInstant(stored));

const before = isBefore;

const leafFor = (options: {
  readonly context: RequestContext;
  readonly end: string | null;
  readonly start: string;
}): DateLeaf =>
  Option.getOrElse(
    dateLeaf({
      ...(options.end === null ? {} : { end: options.end }),
      locale: options.context.translator.locale,
      now: storedTimestamp(options.context.now),
      start: options.start,
    }),
    () => ({
      band: "",
      bandIsLong: false,
      datetime: options.start,
      day: "",
      hour: "",
      isOngoing: false,
      isRange: false,
      isSunday: false,
      isToday: false,
      label: options.start,
      weekday: "",
    })
  );

export const isListedEvent = (event: FeedEventRow, now: Instant) => {
  const published = optionalInstant(event.publicationTime);

  return (
    published !== undefined &&
    !before(now, published) &&
    event.visibility === "public"
  );
};

const isProposalActive = (event: FeedEventRow, now: Instant) => {
  const opens = optionalInstant(event.proposalStartTime);
  const closes = optionalInstant(event.proposalEndTime);

  return (
    opens !== undefined &&
    closes !== undefined &&
    before(opens, now) &&
    before(now, closes)
  );
};

type Dated = Readonly<{ item: FeedItem; start: Instant }>;

const eventItems = (options: {
  readonly context: RequestContext;
  readonly events: readonly FeedEventRow[];
}): readonly Dated[] =>
  options.events.map((event, position) => {
    const start = instantOf(event.startTime);
    const published = optionalInstant(event.publicationTime);

    return {
      item: FeedItem.Event({
        card: {
          coverUrl:
            event.coverImage === ""
              ? placeholderCoverUrl(position)
              : mediaUrl(event.coverImage),
          descriptionText: markdownToPlainText(event.description),
          isLinkOnly: event.visibility === "unlisted",
          isProposalActive: isProposalActive(event, options.context.now),
          isUnpublished:
            published === undefined || before(options.context.now, published),
          leaf: leafFor({
            context: options.context,
            end: event.endTime,
            start: event.startTime,
          }),
          name: event.name,
          sessionCount: event.sessionCount,
          slug: event.slug,
        },
      }),
      start,
    };
  });

const attendanceOf = (
  encounter: FeedEncounterRow,
  options: { readonly isMine: boolean; readonly now: Instant }
) => {
  const hasStarted = !before(options.now, instantOf(encounter.startTime));

  if (encounter.maxParticipants === 0 || hasStarted) {
    return EncounterAttendance.Attending({ count: encounter.rsvpCount });
  }

  if (options.isMine) {
    return EncounterAttendance.SignedUp({
      count: encounter.rsvpCount,
      max: encounter.maxParticipants,
    });
  }

  const left = Math.max(encounter.maxParticipants - encounter.rsvpCount, 0);

  return left === 0
    ? EncounterAttendance.Full()
    : EncounterAttendance.SpotsLeft({ left });
};

const present = (value: string) =>
  value === "" ? Option.none<string>() : Option.some(value);

const encounterItems = (options: {
  readonly context: RequestContext;
  readonly encounters: readonly FeedEncounterRow[];
  readonly viewerId: number | null;
}): readonly Dated[] =>
  options.encounters.map((encounter) => {
    const start = instantOf(encounter.startTime);
    const isMine = encounter.creatorId === options.viewerId;

    return {
      item: FeedItem.Encounter({
        card: {
          attendance: attendanceOf(encounter, {
            isMine,
            now: options.context.now,
          }),
          coverUrl:
            encounter.headerImage === ""
              ? placeholderCoverUrl(encounter.id)
              : mediaUrl(encounter.headerImage),
          game: present(encounter.game),
          isMine,
          isPublic: encounter.isPublic === 1,
          leaf: leafFor({
            context: options.context,
            end: encounter.endTime,
            start: encounter.startTime,
          }),
          organizerName: isMine
            ? Option.none()
            : present(encounter.creatorName),
          place: present(encounter.place),
          shareCode: encounter.shareCode,
          title: encounter.title,
        },
      }),
      start,
    };
  });

export const mergeFeed = (options: {
  readonly items: readonly Dated[];
  readonly newestFirst: boolean;
}) =>
  options.items
    .toSorted((left, right) =>
      options.newestFirst
        ? right.start.epochMillis - left.start.epochMillis
        : left.start.epochMillis - right.start.epochMillis
    )
    .map((dated) => dated.item);

export const loadEventsFeed = Effect.fn("EventsFeedPage.load")(
  function* loadEventsFeed(context: RequestContext) {
    const store = yield* FeedStore;
    const { now } = context;

    const viewerId = Option.match(context.viewer, {
      onNone: () => null,
      onSome: (viewer) => viewer.id,
    });

    const events = (yield* store.listEvents(context.sphere.id)).filter(
      (event) => context.hasPanelAccess || isListedEvent(event, now)
    );

    const isEnded = (event: FeedEventRow) =>
      before(instantOf(event.endTime), now);

    const upcomingEvents = events.filter((event) => !isEnded(event));
    const pastEvents = events.filter(isEnded).toReversed();
    const encountersOn = context.sphere.encountersPolicy !== "none";

    const window = {
      now: storedTimestamp(now),
      sphereId: context.sphere.id,
      viewerId,
    };

    const upcomingEncounters = encountersOn
      ? yield* store.listUpcomingEncounters(window)
      : [];

    const pastEncounters = encountersOn
      ? yield* store.listPastEncounters(window)
      : [];

    const announcements = yield* store.listAnnouncements(context.sphere.id);

    const canCreateEncounter =
      viewerId !== null &&
      (context.sphere.encountersPolicy === "everyone" ||
        (context.sphere.encountersPolicy === "managers" &&
          Option.exists(
            context.viewer,
            (viewer) => viewer.sphereRole === "manager"
          )));

    const flags: EventsFeedFlags = {
      announcements,
      canCreateEncounter,
      past: mergeFeed({
        items: [
          ...eventItems({ context, events: pastEvents }),
          ...encounterItems({ context, encounters: pastEncounters, viewerId }),
        ],
        newestFirst: true,
      }).slice(0, pastFeedLimit),
      showHidden: context.hasPanelAccess,
      upcoming: mergeFeed({
        items: [
          ...eventItems({ context, events: upcomingEvents }),
          ...encounterItems({
            context,
            encounters: upcomingEncounters,
            viewerId,
          }),
        ],
        newestFirst: false,
      }),
    };

    return flags;
  }
);
