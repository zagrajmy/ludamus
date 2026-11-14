import {
  AccreditationType,
  FacilitatorSort,
  FacilitatorStore,
  UserDirectory,
} from "@zagrajmy/core";
import type { Event, FacilitatorListFilters } from "@zagrajmy/core";
import type { PanelAccess } from "@zagrajmy/core/panel/access";
import { loadFacilitatorDetail } from "@zagrajmy/core/panel/facilitators";
import { formatDate } from "@zagrajmy/i18n";
import { DateTime, Effect, Option, Schema } from "effect";

import type {
  FacilitatorBinFlags,
  FacilitatorDetailFlags,
  FacilitatorFormFlags,
  FacilitatorsFlags,
} from "../../../client/panel/facilitators/flags.js";
import type { RequestContext } from "../../request-context.js";

const ORGANIZER_FILTERS = new Set(["mine", "unassigned"]);

const listPath = (event: Event) => `/panel/event/${event.slug}/facilitators/`;

export const loadFacilitators = Effect.fn("PanelPages.loadFacilitators")(
  function* loadFacilitators(
    context: RequestContext,
    options: Readonly<{ access: PanelAccess; event: Event }>
  ) {
    const query = context.url.searchParams;
    const search = (query.get("search") ?? "").trim();
    const rawAccreditation = (query.get("accreditation") ?? "").trim();

    const accreditation =
      Schema.decodeUnknownOption(AccreditationType)(rawAccreditation);

    const rawOrganizer = (query.get("organizer") ?? "").trim();
    const organizer = ORGANIZER_FILTERS.has(rawOrganizer) ? rawOrganizer : "";
    const rawSort = (query.get("sort") ?? "").trim();

    const sort = Schema.decodeUnknownOption(FacilitatorSort)(
      rawSort === "" ? "name" : rawSort
    );

    let filters: FacilitatorListFilters = {};

    if (search !== "") {
      filters = { ...filters, search };
    }

    if (Option.isSome(accreditation)) {
      filters = { ...filters, accreditation: accreditation.value };
    }

    if (organizer === "mine") {
      filters = { ...filters, organizerId: options.access.viewer.id };
    }

    if (organizer === "unassigned") {
      filters = { ...filters, organizerUnassigned: true };
    }

    if (Option.isSome(sort)) {
      filters = { ...filters, sort: sort.value };
    }

    const rows = yield* (yield* FacilitatorStore).listByEvent({
      eventId: options.event.id,
      filters,
    });

    const flags: FacilitatorsFlags = {
      columns: [
        "name",
        "linked",
        "guild",
        "sessions",
        "accreditation",
        "organizer",
      ],
      eventSlug: options.event.slug,
      filters: {
        accreditation: Option.getOrElse(accreditation, () => ""),
        organizer,
        search,
        sort: Option.match(sort, {
          onNone: () => "name",
          onSome: (value) => value,
        }),
      },
      listPath: listPath(options.event),
      rows: rows.map((row) => ({
        accreditationType: row.accreditationType,
        displayName: row.displayName,
        isLinked: row.userId !== null,
        organizerName: row.organizerName ?? "",
        sessionCount: row.sessionCount,
        slug: row.slug,
      })),
    };

    return flags;
  }
);

const shortDateTime = (context: RequestContext, value: DateTime.Utc) =>
  formatDate({
    format: "SHORT_DATETIME_FORMAT",
    locale: context.translator.locale,
    value: DateTime.formatIso(value),
  });

export const loadFacilitatorBin = Effect.fn("PanelPages.loadFacilitatorBin")(
  function* loadFacilitatorBin(context: RequestContext, event: Event) {
    const rows = yield* (yield* FacilitatorStore).listDeletedByEvent(event.id);

    const flags: FacilitatorBinFlags = {
      eventSlug: event.slug,
      listPath: `${listPath(event)}bin/`,
      rows: rows.map((row) => ({
        deletedLabel:
          row.deletedAt === null ? "" : shortDateTime(context, row.deletedAt),
        displayName: row.displayName,
        slug: row.slug,
      })),
    };

    return flags;
  }
);

export const loadFacilitatorPage = Effect.fn("PanelPages.loadFacilitatorPage")(
  function* loadFacilitatorPage(event: Event, slug: string) {
    const detail = yield* loadFacilitatorDetail({
      eventId: event.id,
      includeDeleted: true,
      slug,
    });

    if (Option.isNone(detail)) {
      return Option.none<FacilitatorDetailFlags>();
    }

    const { facilitator, sessions } = detail.value;

    const linked =
      facilitator.userId === null
        ? Option.none()
        : yield* (yield* UserDirectory).readById(facilitator.userId).pipe(
            Effect.map(Option.some),
            Effect.catchTag("NotFound", () => Effect.succeed(Option.none()))
          );

    const flags: FacilitatorDetailFlags = {
      accreditationType: facilitator.accreditationType,
      displayName: facilitator.displayName,
      eventSlug: event.slug,
      internalComment: facilitator.internalComment,
      isCollective: facilitator.isCollective,
      isDeleted: facilitator.deletedAt !== null,
      linkedUser: Option.match(linked, {
        onNone: () => "",
        onSome: (user) =>
          user.email === "" ? user.name : `${user.name} · ${user.email}`,
      }),
      organizerName: facilitator.organizerName ?? "",
      sessions: sessions.map((session) => ({
        id: session.id,
        isDeleted: session.isDeleted,
        isScheduled: session.isScheduled,
        status: session.status,
        title: session.title,
      })),
      slug: facilitator.slug,
    };

    return Option.some(flags);
  }
);

export const loadFacilitatorForm = Effect.fn("PanelPages.loadFacilitatorForm")(
  function* loadFacilitatorForm(event: Event, slug: Option.Option<string>) {
    if (Option.isNone(slug)) {
      const created: FacilitatorFormFlags = {
        eventSlug: event.slug,
        facilitatorSlug: Option.none(),
        organizerName: "",
        savedName: "",
        values: {
          accreditationType: "none",
          assignMe: true,
          displayName: "",
          internalComment: "",
          isCollective: false,
        },
      };

      return Option.some(created);
    }

    const detail = yield* loadFacilitatorDetail({
      eventId: event.id,
      includeDeleted: false,
      slug: slug.value,
    });

    return detail.pipe(
      Option.map(({ facilitator }): FacilitatorFormFlags => ({
        eventSlug: event.slug,
        facilitatorSlug: Option.some(facilitator.slug),
        organizerName: facilitator.organizerName ?? "",
        savedName: facilitator.displayName,
        values: {
          accreditationType: facilitator.accreditationType,
          assignMe: false,
          displayName: facilitator.displayName,
          internalComment: facilitator.internalComment,
          isCollective: facilitator.isCollective,
        },
      }))
    );
  }
);
