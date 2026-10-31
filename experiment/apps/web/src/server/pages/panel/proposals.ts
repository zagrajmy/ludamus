import {
  AgendaItemStore,
  FacilitatorStore,
  FieldStore,
  PanelStore,
  ProposalCategoryId,
  ProposalCategoryStore,
  SessionFieldId,
  SessionStore,
  SpaceStore,
  TrackStore,
  UserDirectory,
} from "@zagrajmy/core";
import { SessionStatus } from "@zagrajmy/core";
import type {
  Event,
  FieldValue,
  SessionListFilters,
  SessionSort,
  TrackId,
} from "@zagrajmy/core";
import type { PanelAccess } from "@zagrajmy/core/panel/access";
import { readProposalInEvent } from "@zagrajmy/core/panel/proposals";
import { formatDate } from "@zagrajmy/i18n";
import { DateTime, Effect, Option, Schema } from "effect";

import type {
  ProposalColumn,
  ProposalDetailFlags,
  ProposalFormFlags,
  ProposalsFlags,
} from "../../../client/panel/proposals/flags.js";
import { mediaUrl } from "../../request-context.js";
import type { RequestContext } from "../../request-context.js";

export class TrackOutsideEvent {
  readonly _tag = "TrackOutsideEvent";
}

const BUILTIN_KEYS = new Set([
  "title",
  "host",
  "category",
  "status",
  "created",
]);

const listPath = (event: Event) => `/panel/event/${event.slug}/proposals/`;

const local = (context: RequestContext, value: DateTime.Utc, format: string) =>
  formatDate({
    format,
    locale: context.translator.locale,
    value: DateTime.formatIso(value),
  });

export const safeNext = (context: RequestContext, fallback: string) => {
  const next = context.url.searchParams.get("next") ?? "";

  return next.startsWith("/") && !next.startsWith("//") ? next : fallback;
};

const columnsOf = (context: RequestContext): readonly ProposalColumn[] => {
  const { t } = context.translator;

  return [
    { key: "title", kind: "text", label: t("Title") },
    { key: "host", kind: "text", label: t("Presenter name") },
    { key: "category", kind: "text", label: t("Category") },
    { key: "status", kind: "status", label: t("Status") },
    { key: "created", kind: "created", label: t("Created") },
  ];
};

const parseSort = (raw: string): Option.Option<SessionSort> => {
  const descending = raw.startsWith("-");
  const key = descending ? raw.slice(1) : raw;

  if (
    key === "title" ||
    key === "host" ||
    key === "category" ||
    key === "status" ||
    key === "created"
  ) {
    return Option.some({ descending, key });
  }

  return key.startsWith("field_") && /^\d+$/u.test(key.slice(6))
    ? Option.some({
        descending,
        fieldId: SessionFieldId.make(Number(key.slice(6))),
      })
    : Option.none();
};

const listFilters = (
  options: Readonly<{
    categoryId: Option.Option<ProposalCategoryId>;
    fieldValues: readonly Readonly<{ id: number; value: string }>[];
    multi: boolean;
    search: string;
    sort: string;
    status: string;
    trackId: Option.Option<TrackId>;
  }>
) => {
  let filters: SessionListFilters = {};
  const answered = options.fieldValues.flatMap((field) =>
    field.value === ""
      ? []
      : [{ fieldId: SessionFieldId.make(field.id), value: field.value }]
  );

  if (Option.isSome(options.categoryId)) {
    filters = { ...filters, categoryId: options.categoryId.value };
  }

  if (answered.length > 0) {
    filters = { ...filters, fieldFilters: answered };
  }

  if (options.multi) {
    filters = { ...filters, multiTracks: true };
  }

  if (options.status === "scheduled") {
    filters = { ...filters, scheduled: true };
  }

  const status = Schema.decodeUnknownOption(SessionStatus)(options.status);

  if (Option.isSome(status)) {
    filters = { ...filters, scheduled: false, status: status.value };
  }

  if (options.search !== "") {
    filters = { ...filters, search: options.search };
  }

  const sort = parseSort(options.sort);

  if (Option.isSome(sort)) {
    filters = { ...filters, sort: sort.value };
  }

  if (Option.isSome(options.trackId)) {
    filters = { ...filters, trackId: options.trackId.value };
  }

  return filters;
};

export const loadProposals = Effect.fn("PanelPages.loadProposals")(
  function* loadProposals(
    context: RequestContext,
    options: Readonly<{ access: PanelAccess; event: Event }>
  ) {
    const { event } = options;
    const query = context.url.searchParams;
    const tracks = yield* TrackStore;
    const allTracks = yield* tracks.listByEvent(event.id);

    const managed = yield* tracks.listByManager({
      eventId: event.id,
      userId: options.access.viewer.id,
    });

    const managedIds = new Set<number>(managed.map((track) => track.id));
    const trackParam = (query.get("track") ?? "").trim();

    let trackId = Option.none<TrackId>();

    if (
      !query.has("track") &&
      managed.length === 1 &&
      managed[0] !== undefined
    ) {
      trackId = Option.some(managed[0].id);
    } else if (/^\d+$/u.test(trackParam)) {
      const found = allTracks.find((track) => String(track.id) === trackParam);

      if (found === undefined) {
        return yield* Effect.fail(new TrackOutsideEvent());
      }

      trackId = Option.some(found.id);
    }

    const multi = trackParam === "multi";

    const fields = (yield* (yield* FieldStore).listSessionFields(
      event.id
    )).filter((field) => field.fieldType === "select");

    const categories = yield* (yield* ProposalCategoryStore).listByEvent(
      event.id
    );

    const rawCategory = (query.get("category") ?? "").trim();

    const category = categories.find(
      (known) => String(known.id) === rawCategory
    );

    const rawStatus = query.get("status") ?? "pending";

    const status =
      rawStatus === "scheduled" ||
      Option.isSome(Schema.decodeUnknownOption(SessionStatus)(rawStatus))
        ? rawStatus
        : "";

    const rawSort = (query.get("sort") ?? "").trim();
    const sortKey = rawSort.replace(/^-/u, "");

    const sort =
      BUILTIN_KEYS.has(sortKey) ||
      fields.some((field) => `field_${field.id}` === sortKey)
        ? rawSort
        : "";

    const search = (query.get("search") ?? "").trim();

    const fieldValues = fields.map((field) => ({
      id: field.id,
      value: (query.get(`field_${field.id}`) ?? "").trim(),
    }));

    const filters = listFilters({
      categoryId: Option.map(Option.fromNullishOr(category), (known) =>
        ProposalCategoryId.make(known.id)
      ),
      fieldValues,
      multi,
      search,
      sort,
      status,
      trackId,
    });

    const sessions = yield* SessionStore;
    const rows = yield* sessions.listByEvent({ eventId: event.id, filters });
    const deleted = yield* sessions.listDeletedByEvent(event.id);
    const stats = yield* (yield* PanelStore).eventStats(event.id);

    const toRow = (row: (typeof rows)[number]) => ({
      categoryName: row.categoryName,
      createdLabel: local(context, row.creationTime, "d M Y H:i"),
      facilitatorName: row.facilitatorName,
      id: row.id,
      isScheduled: row.isScheduled,
      status: row.status,
      title: row.title,
    });

    const flags: ProposalsFlags = {
      categories: categories.map((known) => ({
        id: known.id,
        name: known.name,
      })),
      cells: rows.map((row) => ({
        id: row.id,
        values: {
          category: row.categoryName,
          host: row.facilitatorName,
          title: row.title,
        },
      })),
      columns: columnsOf(context),
      deleted: deleted.map(toRow),
      eventSlug: event.slug,
      fields: fields.map((field) => ({
        id: field.id,
        name: field.name,
        options: field.options.map((choice) => ({
          label: choice.label,
          value: choice.value,
        })),
        value: fieldValues.find((known) => known.id === field.id)?.value ?? "",
      })),
      filterStatus: status,
      filters: {
        category: category === undefined ? "" : String(category.id),
        search,
        sort,
        status: status === "" ? "all" : status,
        track: multi
          ? "multi"
          : Option.match(trackId, { onNone: () => "", onSome: String }),
      },
      fullPath: `${context.url.pathname}${context.url.search}`,
      hasProposals: stats.totalProposals > 0,
      listPath: listPath(event),
      rows: rows.map(toRow),
      tracks: allTracks
        .map((track) => ({
          id: track.id,
          isManaged: managedIds.has(track.id),
          name: track.name,
        }))
        .toSorted((left, right) =>
          left.isManaged === right.isManaged
            ? left.name.localeCompare(right.name)
            : left.isManaged
              ? -1
              : 1
        ),
    };

    return flags;
  }
);

export const durationParts = (iso: string) => {
  const match = /^P(?:T)?(?:(\d+)H)?(?:(\d+)M)?$/u.exec(iso);

  return {
    hours: Number(match?.[1] ?? 0),
    minutes: Number(match?.[2] ?? 0),
  };
};

export const durationLabel = (iso: string) => {
  const { hours, minutes } = durationParts(iso);

  if (hours > 0 && minutes > 0) {
    return `${hours}h ${minutes}min`;
  }

  if (hours > 0) {
    return `${hours}h`;
  }

  return minutes > 0 ? `${minutes}min` : "";
};

const fieldText = (value: FieldValue, context: RequestContext) => {
  if (typeof value === "boolean") {
    return value ? context.translator.t("Yes") : context.translator.t("No");
  }

  return typeof value === "string" ? value : value.join(", ");
};

const readScoped = (event: Event, proposalId: number) =>
  readProposalInEvent({ eventId: event.id, proposalId }).pipe(
    Effect.map(Option.some),
    Effect.catchTag("NotFound", () => Effect.succeed(Option.none()))
  );

export const loadProposalDetail = Effect.fn("PanelPages.loadProposalDetail")(
  function* loadProposalDetail(
    context: RequestContext,
    event: Event,
    proposalId: number
  ) {
    const found = yield* readScoped(event, proposalId);

    if (Option.isNone(found)) {
      return Option.none<ProposalDetailFlags>();
    }

    const session = found.value;
    const sessions = yield* SessionStore;
    const fieldValues = yield* sessions.readFieldValues(session.id);

    const facilitators =
      (yield* sessions.facilitatorsBySession([session.id])).get(session.id) ??
      [];

    const slots = yield* sessions.readPreferredTimeSlots(session.id);
    const trackIds = new Set<number>(yield* sessions.readTrackIds(session.id));

    const tracks = (yield* (yield* TrackStore).listByEvent(event.id)).filter(
      (track) => trackIds.has(track.id)
    );

    const categories = yield* (yield* ProposalCategoryStore).listByEvent(
      event.id
    );

    const agenda = yield* (yield* AgendaItemStore).readBySession(session.id);

    const presenter =
      session.presenterId === null
        ? Option.none()
        : yield* (yield* UserDirectory).readById(session.presenterId).pipe(
            Effect.map(Option.some),
            Effect.catchTag("NotFound", () => Effect.succeed(Option.none()))
          );

    const scheduled = Option.isNone(agenda)
      ? ""
      : yield* (yield* SpaceStore)
          .readInEvent({ eventId: event.id, id: agenda.value.spaceId })
          .pipe(
            Effect.map((space) =>
              context.translator.t(
                "Scheduled in %(space)s, %(start)s – %(end)s",
                {
                  end: local(context, agenda.value.endTime, "TIME_FORMAT"),
                  space: space.name,
                  start: local(
                    context,
                    agenda.value.startTime,
                    "DATETIME_FORMAT"
                  ),
                }
              )
            ),
            Effect.catchTag("NotFound", () => Effect.succeed(""))
          );

    const flags: ProposalDetailFlags = {
      backUrl: safeNext(context, listPath(event)),
      categoryName:
        categories.find((category) => category.id === session.categoryId)
          ?.name ?? "",
      contactEmail: session.contactEmail,
      coverUrl: session.coverImage === "" ? "" : mediaUrl(session.coverImage),
      createdLabel: local(context, session.creationTime, "DATETIME_FORMAT"),
      description: session.description,
      durationLabel: durationLabel(session.duration),
      eventSlug: event.slug,
      facilitatorName: session.facilitatorName,
      facilitators: facilitators.map((facilitator) => ({
        name: facilitator.displayName,
        slug: facilitator.slug,
      })),
      fieldValues: fieldValues
        .toSorted((left, right) => left.fieldOrder - right.fieldOrder)
        .map((answer) => ({
          term: answer.fieldName,
          value: fieldText(answer.value, context),
        })),
      id: session.id,
      minAge: session.minAge,
      modifiedLabel: local(
        context,
        session.modificationTime,
        "DATETIME_FORMAT"
      ),
      participantsLimit: session.participantsLimit,
      preferredSlots: slots.map(
        (slot) =>
          `${local(context, slot.startTime, "DATETIME_FORMAT")} – ${local(context, slot.endTime, "DATETIME_FORMAT")}`
      ),
      presenter: Option.match(presenter, {
        onNone: () => "",
        onSome: (user) => `${user.name} · ${user.email}`,
      }),
      scheduled,
      slug: session.slug,
      status: session.status,
      title: session.title,
      tracks: tracks.map((track) => ({ name: track.name, slug: track.slug })),
    };

    return Option.some(flags);
  }
);

export const loadProposalForm = Effect.fn("PanelPages.loadProposalForm")(
  function* loadProposalForm(
    context: RequestContext,
    event: Event,
    proposalId: Option.Option<number>
  ) {
    const categories = yield* (yield* ProposalCategoryStore).listByEvent(
      event.id
    );

    const facilitators = yield* (yield* FacilitatorStore).listByEvent({
      eventId: event.id,
      filters: { sort: "name" },
    });

    const tracks = yield* (yield* TrackStore).listByEvent(event.id);

    const base = {
      categories: categories.map((category) => ({
        id: category.id,
        name: category.name,
      })),
      eventSlug: event.slug,
      facilitators: facilitators.map((facilitator) => ({
        id: facilitator.id,
        name: facilitator.displayName,
      })),
      tracks: tracks.map((track) => ({ id: track.id, name: track.name })),
    };

    if (Option.isNone(proposalId)) {
      const created: ProposalFormFlags = {
        ...base,
        cancelUrl: safeNext(context, listPath(event)),
        coverName: "",
        coverUrl: "",
        next: "",
        proposalId: Option.none(),
        savedTitle: "",
        values: {
          categoryId: "",
          contactEmail: "",
          description: "",
          durationHours: "",
          durationMinutes: "",
          facilitatorIds: [],
          facilitatorName: "",
          minAge: "",
          participantsLimit: "",
          timeSlotIds: [],
          title: "",
          trackIds: [],
        },
      };

      return Option.some(created);
    }

    const found = yield* readScoped(event, proposalId.value);

    if (Option.isNone(found)) {
      return Option.none<ProposalFormFlags>();
    }

    const session = found.value;
    const sessions = yield* SessionStore;

    const assigned =
      (yield* sessions.facilitatorsBySession([session.id])).get(session.id) ??
      [];

    const trackIds = yield* sessions.readTrackIds(session.id);
    const slots = yield* sessions.readPreferredTimeSlots(session.id);
    const { hours, minutes } = durationParts(session.duration);
    const next = safeNext(context, "");
    const detail = `${listPath(event)}${session.id}/`;

    const edited: ProposalFormFlags = {
      ...base,
      cancelUrl:
        next === ""
          ? detail
          : `${detail}?${new URLSearchParams({ next }).toString()}`,
      coverName: session.coverImageOriginalName,
      coverUrl: session.coverImage === "" ? "" : mediaUrl(session.coverImage),
      next,
      proposalId: Option.some(session.id),
      savedTitle: session.title,
      values: {
        categoryId:
          session.categoryId === null ? "" : String(session.categoryId),
        contactEmail: session.contactEmail,
        description: session.description,
        durationHours: hours === 0 ? "" : String(hours),
        durationMinutes: minutes === 0 ? "" : String(minutes),
        facilitatorIds: assigned.map((facilitator) => facilitator.id),
        facilitatorName: session.facilitatorName,
        minAge: session.minAge === 0 ? "" : String(session.minAge),
        participantsLimit:
          session.participantsLimit === 0
            ? ""
            : String(session.participantsLimit),
        timeSlotIds: slots.map((slot) => slot.id),
        title: session.title,
        trackIds: [...trackIds],
      },
    };

    return Option.some(edited);
  }
);
