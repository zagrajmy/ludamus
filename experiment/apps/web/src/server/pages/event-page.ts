import {
  BookmarkStore,
  CurrentSphere,
  EnrollmentConfigStore,
  ParticipationStore,
  SphereId,
  UserDirectory,
  UserId,
  readEventPage,
} from "@zagrajmy/core";
import type {
  EnrollmentConfig,
  EventPage,
  SessionCard,
  SessionField,
} from "@zagrajmy/core/contracts";
import {
  accessSeats,
  canEnrollNow,
  viewerAccess,
} from "@zagrajmy/core/enrollment/windows";
import { formatDuration } from "@zagrajmy/core/proposal/durations";
import type { Locale } from "@zagrajmy/i18n";
import { formatDate, shortDate } from "@zagrajmy/i18n";
import { DateTime, Effect, Option } from "effect";

import type {
  Availability,
  EventPageFlags,
  FieldPill,
  IconGlyph,
  SessionView,
  StatusPill,
} from "../../client/event-page/flags.js";
import type { Translator } from "../../ui/i18n.js";
import type { IconData } from "../../ui/icon.js";
import * as icons from "../../ui/icons.js";
import { markdownSummary, renderSafeMarkdown } from "../markdown.js";
import { mediaUrl } from "../request-context.js";
import type { RequestContext } from "../request-context.js";
import { buildCardDays, buildLedger, buildRoomGrid } from "./event-schedule.js";
import type { Booked } from "./event-schedule.js";

const MAX_VISIBLE_PILLS = 4;

const SCARCE_THRESHOLD = 0.2;

const ROSTER_PREVIEW = 3;

const iconIndex: Readonly<Record<string, IconData>> = icons;

const camel = (name: string) =>
  name.replaceAll(/-([a-z0-9])/gu, (_match, letter: string) =>
    letter.toUpperCase()
  );

const iconNamed = (name: string): Option.Option<IconGlyph> =>
  name === ""
    ? Option.none()
    : Option.fromNullishOr(iconIndex[`${camel(name)}Mini`]);

const millis = (instant: DateTime.Utc) => DateTime.toEpochMillis(instant);

const format = (options: {
  readonly at: DateTime.Utc;
  readonly locale: Locale;
  readonly pattern: string;
}) =>
  formatDate({
    format: options.pattern,
    locale: options.locale,
    value: DateTime.formatIso(options.at),
  });

const whenLabel = (options: {
  readonly end: DateTime.Utc;
  readonly locale: Locale;
  readonly start: DateTime.Utc;
}) =>
  `${format({ at: options.start, locale: options.locale, pattern: "l, j E" })} · ${format({ at: options.start, locale: options.locale, pattern: "G:i" })}–${format({ at: options.end, locale: options.locale, pattern: "G:i" })}`;

const answerValues = (value: SessionCard["fieldValues"][number]["value"]) => {
  if (typeof value === "string") {
    return value === "" ? [] : [value];
  }

  if (typeof value === "boolean") {
    return [];
  }

  return value.filter((item) => item !== "");
};

const publicSelectAnswers = (card: SessionCard) =>
  card.fieldValues.flatMap((answer) =>
    answer.fieldType === "select" &&
    answer.isPublic &&
    Array.isArray(answer.value)
      ? answer.value.map((value) => ({
          slug: answer.fieldSlug,
          value: String(value),
        }))
      : []
  );

const crumbsOf = (card: SessionCard) =>
  card.location.sortPath.map((step) => ({
    name: step.name,
    spaceFilter:
      step.id === card.location.spaceId
        ? String(step.id)
        : step.id === card.location.parentId
          ? `venue:${step.id}`
          : "",
  }));

type Viewer = Readonly<{
  bookmarked: ReadonlySet<number>;
  configuredWindowIds: readonly number[];
  enrolled: ReadonlySet<number>;
  waiting: ReadonlySet<number>;
}>;

const NO_VIEWER: Viewer = {
  bookmarked: new Set(),
  configuredWindowIds: [],
  enrolled: new Set(),
  waiting: new Set(),
};

const personOf = (user: {
  readonly avatarUrl: string;
  readonly name: string;
  readonly username: string;
}) => ({
  avatarUrl:
    user.avatarUrl === "" ? Option.none<string>() : Option.some(user.avatarUrl),
  name: user.name === "" ? user.username : user.name,
});

const availabilityOf = (state: {
  readonly inactiveWhenOngoing: boolean;
  readonly isAvailable: boolean;
  readonly isEnded: boolean;
  readonly isFull: boolean;
  readonly isOngoing: boolean;
  readonly isScheduled: boolean;
  readonly takesEnrollment: boolean;
}): Availability => {
  if (!state.isScheduled) {
    return "proposal";
  }

  if (state.isEnded) {
    return "ended";
  }

  if (state.inactiveWhenOngoing && state.isOngoing) {
    return "in-progress";
  }

  if (!state.takesEnrollment) {
    return "no-enrollment";
  }

  if (!state.isAvailable) {
    return "unavailable";
  }

  return state.isFull ? "full" : "available";
};

const sessionView = (options: {
  readonly bookmarks: ReadonlyMap<number, number>;
  readonly card: SessionCard;
  readonly enrollable: (windowIds: readonly number[]) => boolean;
  readonly inactiveWhenOngoing: boolean;
  readonly locale: Locale;
  readonly now: DateTime.Utc;
  readonly translator: Translator;
  readonly viewer: Viewer;
}): SessionView => {
  const { card, locale, now, translator, viewer } = options;
  const { session, seats } = card;
  const agenda = card.agendaItem;
  const isScheduled = agenda !== null;

  const isEnded =
    agenda !== null && DateTime.isLessThanOrEqualTo(agenda.endTime, now);

  const isOngoing =
    agenda !== null && DateTime.isLessThanOrEqualTo(agenda.startTime, now);

  const takesEnrollment = isScheduled && session.participantsLimit > 0;

  const isAvailable =
    isScheduled && options.enrollable(seats.eligibleWindowIds);

  const spotsLeft = Math.max(
    0,
    seats.effectiveParticipantsLimit - seats.enrolledCount
  );

  const availability = availabilityOf({
    inactiveWhenOngoing: options.inactiveWhenOngoing,
    isAvailable,
    isEnded,
    isFull: seats.isFull,
    isOngoing,
    isScheduled,
    takesEnrollment,
  });

  const seatsLabel = isScheduled
    ? seats.enrolledCount > 0
      ? translator.n("%(counter)s free", "%(counter)s free", spotsLeft, {
          counter: spotsLeft,
        })
      : translator.n(
          "%(counter)s seat",
          "%(counter)s seats",
          seats.effectiveParticipantsLimit,
          {
            counter: seats.effectiveParticipantsLimit,
          }
        )
    : translator.n(
        "%(counter)s seat",
        "%(counter)s seats",
        session.participantsLimit,
        {
          counter: session.participantsLimit,
        }
      );

  const shownFields = card.fieldValues.filter((answer) => answer.showOnCards);

  const pillRows = shownFields.map((answer) => {
    const values = answerValues(answer.value);
    const glyph = iconNamed(answer.fieldIcon);

    return {
      overflow: values
        .slice(MAX_VISIBLE_PILLS)
        .map((value): FieldPill => ({ icon: glyph, value })),
      visible: values
        .slice(0, MAX_VISIBLE_PILLS)
        .map((value): FieldPill => ({ icon: glyph, value })),
    };
  });

  const selectAnswers = publicSelectAnswers(card);

  const tagCategories = [
    ...selectAnswers.map((answer) => `${answer.slug}:${answer.value}`),
    ...card.trackNames.map((name) => `__track:${name}`),
    ...(card.categoryName === "" ? [] : [`__category:${card.categoryName}`]),
  ].join(";");

  const presenterName =
    card.presenter === null
      ? session.facilitatorName
      : card.presenter.name === ""
        ? card.presenter.username
        : card.presenter.name;

  const confirmed = card.participations.filter(
    (seat) => seat.status === "confirmed"
  );

  const spaceOrder = JSON.stringify(
    card.location.sortPath.map((step) => [step.order, step.name, step.id])
  );

  return {
    availability,
    bookmarkCount: options.bookmarks.get(session.id) ?? 0,
    categoryName: card.categoryName,
    coverUrl: session.coverImage === "" ? "" : mediaUrl(session.coverImage),
    crumbs: crumbsOf(card),
    description: session.description,
    descriptionHtml: renderSafeMarkdown(session.description),
    durationLabel: formatDuration(session.duration),
    effectiveLimit: seats.effectiveParticipantsLimit,
    enrolledCount: seats.enrolledCount,
    fieldAnswers: card.fieldValues.flatMap((answer) => {
      const values = answerValues(answer.value);

      return values.length === 0
        ? []
        : [
            {
              icon: iconNamed(answer.fieldIcon),
              name: answer.fieldName,
              values,
            },
          ];
    }),
    host: session.facilitatorName,
    id: session.id,
    isFull: seats.isFull,
    locationLabel: card.location.path,
    minAge: session.minAge,
    overflowPills: pillRows.flatMap((row) => row.overflow),
    participants: confirmed
      .toSorted((left, right) => left.status.localeCompare(right.status))
      .slice(0, ROSTER_PREVIEW)
      .map((seat) => personOf(seat.user)),
    pills: pillRows.flatMap((row) => row.visible),
    presenter: {
      avatarUrl:
        card.presenter === null || card.presenter.avatarUrl === ""
          ? Option.none()
          : Option.some(card.presenter.avatarUrl),
      name: presenterName,
    },
    roster:
      card.participations.length === 0 &&
      seats.enrolledCount + seats.waitingCount > 0
        ? Option.none()
        : Option.some(
            card.participations
              .toSorted(
                (left, right) =>
                  millis(left.creationTime) - millis(right.creationTime)
              )
              .map((seat) => ({
                createdLabel: format({
                  at: seat.creationTime,
                  locale,
                  pattern: "M j, G:i",
                }),
                person: personOf(seat.user),
                status: seat.status,
              }))
          ),
    seatsLabel,
    spaceId: card.location.spaceId === 0 ? "" : String(card.location.spaceId),
    spaceName: card.location.spaceName,
    spaceOrder,
    spotsLeft,
    spotsScarce:
      seats.effectiveParticipantsLimit !== 0 &&
      spotsLeft / seats.effectiveParticipantsLimit < SCARCE_THRESHOLD,
    tagCategories,
    tags: selectAnswers.map((answer) => answer.value).join(","),
    takesEnrollment,
    timing:
      agenda === null
        ? Option.none()
        : Option.some({
            day: format({ at: agenda.startTime, locale, pattern: "Y-m-d" }),
            dayLabel: format({
              at: agenda.startTime,
              locale,
              pattern: "l, j F",
            }),
            endClock: format({ at: agenda.endTime, locale, pattern: "H:i" }),
            endIso: format({ at: agenda.endTime, locale, pattern: "c" }),
            endsAt: millis(agenda.endTime),
            hour: format({ at: agenda.startTime, locale, pattern: "H:i" }),
            sessionEndIso: format({ at: agenda.endTime, locale, pattern: "c" }),
            startClock: format({
              at: agenda.startTime,
              locale,
              pattern: "H:i",
            }),
            startIso: format({ at: agenda.startTime, locale, pattern: "c" }),
            startsAt: millis(agenda.startTime),
            when: whenLabel({
              end: agenda.endTime,
              locale,
              start: agenda.startTime,
            }),
          }),
    title: session.title,
    tracks: card.trackNames,
    userBookmarked: viewer.bookmarked.has(session.id),
    userEnrolled: viewer.enrolled.has(session.id),
    userWaiting: viewer.waiting.has(session.id),
    venueId: card.location.parentId === 0 ? "" : String(card.location.parentId),
    venueName: card.location.parentName,
    waitingCount: seats.waitingCount,
  };
};

const statusPills = (options: {
  readonly canEnroll: boolean;
  readonly isEnded: boolean;
  readonly isLive: boolean;
  readonly isProposalActive: boolean;
  readonly locale: Locale;
  readonly opensAt: DateTime.Utc | null;
  readonly translator: Translator;
}): readonly StatusPill[] => {
  const { translator } = options;
  const pills: StatusPill[] = [];

  if (options.isLive) {
    pills.push({
      classes:
        "bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400",
      icon: "live",
      label: translator.t("Happening now!"),
    });
  } else if (options.isEnded) {
    pills.push({
      classes:
        "bg-neutral-200 dark:bg-neutral-700/30 text-foreground-secondary",
      icon: "check-circle",
      label: translator.t("Completed"),
    });
  }

  if (options.canEnroll) {
    pills.push({
      classes:
        "bg-coral-100 dark:bg-coral-900/30 text-coral-700 dark:text-coral-400",
      icon: "user-plus",
      label: translator.t("Enrollment Open"),
    });
  } else if (options.opensAt !== null) {
    const opensIso = DateTime.formatIso(options.opensAt);

    pills.push({
      classes:
        "bg-warm-200 dark:bg-warm-800/30 text-warm-700 dark:text-warm-400",
      icon: "clock",
      label: translator.t("Your enrollment opens %(day)s at %(time)s", {
        day: shortDate(options.locale, opensIso),
        time: formatDate({
          format: "G:i",
          locale: options.locale,
          value: opensIso,
        }),
      }),
    });
  }

  if (options.isProposalActive) {
    pills.push({
      classes:
        "bg-amber-100 dark:bg-amber-900/10 text-amber-700 dark:text-amber-400",
      icon: "light-bulb",
      label: translator.t("Proposals Open"),
    });
  }

  if (!options.isLive && !options.isEnded && options.opensAt === null) {
    pills.push({
      classes:
        "bg-warm-200 dark:bg-warm-800/30 text-warm-700 dark:text-warm-400",
      icon: "clock",
      label: translator.t("Upcoming"),
    });
  }

  return pills.slice(0, 2);
};

const icsStamp = (instant: DateTime.Utc) =>
  DateTime.formatIso(instant).replaceAll(/[-:]/gu, "").replace(/\.\d+/u, "");

const googleCalendarUrl = (options: {
  readonly address: string;
  readonly end: DateTime.Utc;
  readonly name: string;
  readonly start: DateTime.Utc;
  readonly url: string;
}) => {
  const params = new URLSearchParams({
    action: "TEMPLATE",
    dates: `${icsStamp(options.start)}/${icsStamp(options.end)}`,
    details: options.url,
    text: options.name,
  });

  if (options.address !== "") {
    params.set("location", options.address);
  }

  return `https://calendar.google.com/calendar/render?${params.toString().replaceAll("+", "%20")}`;
};

const fieldChoices = (
  fields: readonly SessionField[],
  sessions: readonly SessionCard[]
) => {
  const answered = new Map<string, Set<string>>();

  for (const card of sessions) {
    for (const answer of publicSelectAnswers(card)) {
      const values = answered.get(answer.slug) ?? new Set<string>();
      values.add(answer.value);
      answered.set(answer.slug, values);
    }
  }

  return fields.flatMap((field) => {
    const used = answered.get(field.slug) ?? new Set<string>();

    const options = field.options
      .toSorted((left, right) => left.order - right.order || left.id - right.id)
      .map((option) => option.value)
      .filter((value) => used.has(value));

    return options.length > 1
      ? [{ name: field.name, options, slug: field.slug }]
      : [];
  });
};

const distinctSorted = (values: readonly string[]) =>
  [...new Set(values.filter((value) => value !== ""))].toSorted();

const atLeastTwo = (values: readonly string[]) =>
  values.length > 1 ? values : [];

const spaceChoices = (options: {
  readonly allRooms: string;
  readonly sessions: readonly SessionCard[];
}) => {
  const rooms = new Map<number, SessionCard["location"]>();

  for (const card of options.sessions) {
    if (card.location.spaceId !== 0 && !rooms.has(card.location.spaceId)) {
      rooms.set(card.location.spaceId, card.location);
    }
  }

  const compare = (
    left: SessionCard["location"],
    right: SessionCard["location"]
  ) => {
    const length = Math.min(left.sortPath.length, right.sortPath.length);

    for (let index = 0; index < length; index += 1) {
      const one = left.sortPath[index];
      const other = right.sortPath[index];

      if (one !== undefined && other !== undefined) {
        if (one.order !== other.order) {
          return one.order - other.order;
        }

        if (one.name !== other.name) {
          return one.name < other.name ? -1 : 1;
        }

        if (one.id !== other.id) {
          return one.id - other.id;
        }
      }
    }

    return (
      left.sortPath.length - right.sortPath.length ||
      left.spaceId - right.spaceId
    );
  };

  let group;
  const choices: { label: string; value: string }[] = [];

  for (const location of [...rooms.values()].toSorted(compare)) {
    if (location.parentId === 0) {
      group = undefined;
    } else if (group !== location.parentId) {
      group = location.parentId;
      choices.push({
        label: `${location.parentName} — ${options.allRooms}`,
        value: `venue:${location.parentId}`,
      });
    }

    choices.push({
      label:
        location.parentName === ""
          ? location.spaceName
          : `${location.parentName} — ${location.spaceName}`,
      value: String(location.spaceId),
    });
  }

  return { choices, roomCount: rooms.size };
};

const readViewer = Effect.fn("EventPage.readViewer")(
  function* readViewer(options: {
    readonly context: RequestContext;
    readonly page: EventPage;
  }) {
    const { context, page } = options;

    if (Option.isNone(context.viewer)) {
      return NO_VIEWER;
    }

    const viewer = context.viewer.value;
    const userId = UserId.make(viewer.id);
    const users = yield* UserDirectory;
    const participations = yield* ParticipationStore;
    const bookmarks = yield* BookmarkStore;
    const windows = yield* EnrollmentConfigStore;

    const companions = yield* users.companionsOf(userId);

    const seats = yield* participations.listForUsersInEvent({
      eventId: page.event.id,
      userIds: [userId, ...companions.map((companion) => companion.id)],
    });

    const bookmarked = page.isCompact
      ? yield* bookmarks.bookmarkedSessionIds({
          eventId: page.event.id,
          userId,
        })
      : [];

    const domain = viewer.email.split("@")[1] ?? "";
    const windowIds = page.enrollmentWindows.map((window) => window.id);

    const configured = [
      ...(yield* windows.userAllowances({
        emails: viewer.email === "" ? [] : [viewer.email],
        enrollmentConfigIds: windowIds,
      })),
      ...(yield* windows.domainAllowances({
        domains: domain === "" ? [] : [domain],
        enrollmentConfigIds: windowIds,
      })),
    ];

    const viewerState: Viewer = {
      bookmarked: new Set(bookmarked),
      configuredWindowIds: configured.length === 0 ? [] : windowIds,
      enrolled: new Set(
        seats
          .filter((seat) => seat.status === "confirmed")
          .map((seat) => seat.sessionId)
      ),
      waiting: new Set(
        seats
          .filter((seat) => seat.status === "waiting")
          .map((seat) => seat.sessionId)
      ),
    };

    return viewerState;
  }
);

const windowRules = (window: EnrollmentConfig) => ({
  ...window,
  pk: window.id,
});

const linkPreviewOf = (options: {
  readonly eventName: string;
  readonly eventDescription: string;
  readonly search: string;
  readonly sessions: readonly SessionView[];
}) => {
  const raw = new URLSearchParams(options.search).get("session") ?? "";

  const session = /^\d+$/u.test(raw)
    ? options.sessions.find((candidate) => candidate.id === Number(raw))
    : undefined;

  if (session === undefined) {
    return {
      description: markdownSummary(options.eventDescription),
      title: "",
    };
  }

  const parts = [
    ...Option.toArray(Option.map(session.timing, (timing) => timing.when)),
    ...(session.locationLabel === "" ? [] : [`— ${session.locationLabel}`]),
    ...(session.host === "" || session.presenter.name === ""
      ? []
      : [`· ${session.presenter.name}`]),
    ...(session.description === ""
      ? []
      : [`| ${markdownSummary(session.description)}`]),
  ];

  return {
    description: parts.join(" "),
    title: `${session.title} • ${options.eventName}`,
  };
};

const buildFlags = Effect.fn("EventPage.buildFlags")(
  function* buildFlags(options: {
    readonly context: RequestContext;
    readonly page: EventPage;
  }) {
    const { context, page } = options;
    const { translator } = context;
    const { locale } = translator;
    const { event } = page;
    const now = DateTime.makeUnsafe(context.now.epochMillis);
    const viewer = yield* readViewer({ context, page });

    const access = viewerAccess({
      configuredWindowIds: viewer.configuredWindowIds,
      now,
      windows: page.enrollmentWindows.map(windowRules),
    });

    const activeWindows = page.enrollmentWindows.filter(
      (window) =>
        DateTime.isLessThan(window.startTime, now) &&
        DateTime.isLessThan(now, window.endTime)
    );

    const bookmarkCounts = new Map(
      page.bookmarkCounts.map((row) => [row.sessionId, row.count])
    );

    const sessions = page.sessions.map((card) =>
      sessionView({
        bookmarks: bookmarkCounts,
        card,
        enrollable: (windowIds) => accessSeats({ access, windowIds }),
        inactiveWhenOngoing: activeWindows.some(
          (window) => window.limitToEndTime
        ),
        locale,
        now,
        translator,
        viewer,
      })
    );

    const booked: readonly Booked[] = page.sessions.flatMap((card) =>
      card.agendaItem === null
        ? []
        : [
            {
              end: card.agendaItem.endTime,
              id: card.session.id,
              isEnded: DateTime.isLessThanOrEqualTo(
                card.agendaItem.endTime,
                now
              ),
              location: card.location,
              start: card.agendaItem.startTime,
              title: card.session.title,
            },
          ]
    );

    const cardDays = page.isCompact
      ? []
      : buildCardDays({ locale, sessions: booked });

    const layout = page.isCompact
      ? {
          _tag: "Compact" as const,
          days: buildLedger({ locale, sessions: booked }),
          rooms: buildRoomGrid({ locale, sessions: booked }),
        }
      : {
          _tag: "Cards" as const,
          days: cardDays,
          slotCount: cardDays.reduce((sum, day) => sum + day.slots.length, 0),
        };

    const isLive =
      DateTime.isLessThan(event.startTime, now) &&
      DateTime.isLessThan(now, event.endTime);

    const isEnded = DateTime.isLessThan(event.endTime, now);

    const isProposalActive =
      event.proposalStartTime !== null &&
      event.proposalEndTime !== null &&
      DateTime.isLessThanOrEqualTo(event.proposalStartTime, now) &&
      DateTime.isLessThanOrEqualTo(now, event.proposalEndTime);

    const startIso = DateTime.formatIso(event.startTime);
    const endIso = DateTime.formatIso(event.endTime);

    const dated = (value: string, pattern: string) =>
      formatDate({ format: pattern, locale, value });

    const addressLines = event.address
      .split(/\r?\n/u)
      .map((line) => line.trim())
      .filter((line) => line !== "");

    const addressInline = addressLines.join(", ");
    const eventPath = `/event/${event.slug}/`;

    const spaces = spaceChoices({
      allRooms: translator.t("all rooms"),
      sessions: page.sessions,
    });

    const minAges = [
      ...new Set(page.sessions.map((card) => card.session.minAge)),
    ];

    const scheduledSessions = sessions.flatMap((session) =>
      Option.isSome(session.timing) ? [session] : []
    );

    const flags: EventPageFlags = {
      choices: {
        categories: atLeastTwo(
          distinctSorted(page.sessions.map((card) => card.categoryName))
        ),
        days: distinctSorted(
          scheduledSessions.flatMap((session) =>
            Option.toArray(Option.map(session.timing, (timing) => timing.day))
          )
        ).map((day) => ({
          label:
            scheduledSessions
              .find((session) =>
                Option.exists(session.timing, (timing) => timing.day === day)
              )
              ?.timing.pipe(
                Option.map((timing) => timing.dayLabel),
                Option.getOrElse(() => day)
              ) ?? day,
          value: day,
        })),
        hosts: distinctSorted(
          page.sessions.map((card) => card.session.facilitatorName)
        ).toSorted((left, right) => left.localeCompare(right)),
        hours: distinctSorted(
          scheduledSessions.flatMap((session) =>
            Option.toArray(Option.map(session.timing, (timing) => timing.hour))
          )
        ),
        minAges: minAges
          .filter((age) => age > 0)
          .toSorted((left, right) => left - right),
        minAgesDistinct: minAges.length,
        spaces: spaces.roomCount > 1 ? spaces.choices : [],
        tagFields: fieldChoices(page.filterFields, page.sessions),
        tracks: atLeastTwo(
          distinctSorted(page.sessions.flatMap((card) => card.trackNames))
        ),
      },
      enrolledSessions: scheduledSessions.flatMap((session) =>
        session.userEnrolled
          ? [
              {
                id: session.id,
                title: session.title,
                when: Option.match(session.timing, {
                  onNone: () => "",
                  onSome: (timing) => timing.when,
                }),
              },
            ]
          : []
      ),
      enrollmentNotices: activeWindows.flatMap((window) =>
        window.bannerText === "" ? [] : [window.bannerText]
      ),
      hasEnrollableSessions: sessions.some(
        (session) => session.takesEnrollment
      ),
      hero: {
        addressLines,
        addressQuery: encodeURIComponent(addressInline),
        coverUrl: event.coverImage === "" ? "" : mediaUrl(event.coverImage),
        dates: {
          endIso: dated(endIso, "c"),
          endShort: shortDate(locale, endIso),
          endTime: dated(endIso, "G:i"),
          isSameDay: dated(startIso, "Y-m-d") === dated(endIso, "Y-m-d"),
          startDay: dated(startIso, "l, j E"),
          startIso: dated(startIso, "c"),
          startShort: shortDate(locale, startIso),
          startTime: dated(startIso, "G:i"),
        },
        descriptionHtml: renderSafeMarkdown(event.description),
        googleCalendarUrl: googleCalendarUrl({
          address: addressInline,
          end: event.endTime,
          name: event.name,
          start: event.startTime,
          url: `${context.scheme}//${context.host}${eventPath}`,
        }),
        icsUrl: `${eventPath}calendar.ics`,
        isEnded,
        isLive,
        isProposalActive,
        isUnlisted: event.visibility === "unlisted",
        mapsUrl: "",
        name: event.name,
        printUrl: `${eventPath}print/`,
        proposeUrl: `${eventPath}propose/`,
        scheduledCount: sessions.length,
        slug: event.slug,
        statusPills: statusPills({
          canEnroll: canEnrollNow(access),
          isEnded,
          isLive,
          isProposalActive,
          locale,
          opensAt: access.opensAt,
          translator,
        }),
      },
      layout,
      linkPreview: linkPreviewOf({
        eventDescription: event.description,
        eventName: event.name,
        search: context.url.search,
        sessions,
      }),
      locale,
      loginUrl: "/crowd/auth0/do/login",
      now: context.now.epochMillis,
      ownProposals: [],
      query: context.url.search,
      sessions,
      signedIn: Option.isSome(context.viewer),
      view:
        page.isCompact && context.url.searchParams.get("view") === "rooms"
          ? "rooms"
          : "list",
    };

    return flags;
  }
);

export const loadEventPage = Effect.fn("EventPage.load")(
  function* loadEventPage(context: RequestContext, slug: string) {
    const page = yield* readEventPage.handler({ slug }).pipe(
      Effect.provideService(CurrentSphere, {
        domain: context.sphere.domain,
        id: SphereId.make(context.sphere.id),
        name: context.sphere.name,
      }),
      Effect.map(Option.some),
      Effect.catchTag("NotFound", () =>
        Effect.succeed(Option.none<EventPage>())
      )
    );

    if (Option.isNone(page)) {
      return Option.none<EventPageFlags>();
    }

    return Option.some(yield* buildFlags({ context, page: page.value }));
  }
);
