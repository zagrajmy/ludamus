import { implement } from "@zagrajmy/capability/implement";
import { Effect, Option } from "effect";

import {
  changeProposalStatusContract,
  deleteProposalContract,
  restoreProposalContract,
  saveProposalContract,
} from "../contracts.js";
import {
  FacilitatorId,
  ProposalCategoryId,
  SessionId,
  TimeSlotId,
  TrackId,
} from "../ids.js";
import type { EventId } from "../ids.js";
import { AgendaItemStore } from "../ports/agenda-item-store.js";
import { ChangeLogStore } from "../ports/change-log-store.js";
import { FacilitatorStore } from "../ports/facilitator-store.js";
import { ProposalCategoryStore } from "../ports/proposal-category-store.js";
import { SessionStore } from "../ports/session-store.js";
import { NotFound } from "../ports/store-error.js";
import { TrackStore } from "../ports/track-store.js";
import { StoreTransaction } from "../ports/transaction.js";
import type { SessionStatus } from "../session.js";
import { requirePanelEvent } from "./access.js";
import { FormInvalid, ProposalScheduled, formError } from "./schemas.js";
import type { FormError, ProposalForm } from "./schemas.js";
import { transliteratedSlugify, uniqueSlug } from "./slugs.js";

const SESSION_SLUG_MAX_LENGTH = 50;

const TEXT_MAX_LENGTH = 255;

const MAX_DURATION_HOURS = 24;

const MAX_DURATION_MINUTES = 59;

const STORAGE_LIMIT = 2_147_483_647;

export const readProposalInEvent = Effect.fn("Panel.readProposalInEvent")(
  function* readProposalInEvent(options: {
    readonly eventId: EventId;
    readonly proposalId: number;
  }) {
    const session = yield* (yield* SessionStore).read(
      SessionId.make(options.proposalId)
    );

    if (session.eventId !== options.eventId || session.deletedAt !== null) {
      return yield* new NotFound({
        entity: "Session",
        key: String(options.proposalId),
      });
    }

    return session;
  }
);

export const changeProposalStatusHandler = Effect.fn(
  "Panel.changeProposalStatus"
)(function* changeProposalStatusHandler(change: {
  readonly eventSlug: string;
  readonly proposalId: number;
  readonly status: SessionStatus;
}) {
  const { event } = yield* requirePanelEvent({
    mode: "write",
    slug: change.eventSlug,
  });

  const transaction = yield* StoreTransaction;

  yield* transaction.atomic(
    Effect.gen(function* changeScopedStatus() {
      const session = yield* readProposalInEvent({
        eventId: event.id,
        proposalId: change.proposalId,
      });

      const placed = yield* (yield* AgendaItemStore).readBySession(session.id);

      if (change.status !== "accepted" && Option.isSome(placed)) {
        return yield* new ProposalScheduled();
      }

      yield* (yield* SessionStore).update({
        changes: { status: change.status },
        eventId: event.id,
        id: session.id,
      });
    })
  );

  return {};
});

export const deleteProposalHandler = Effect.fn("Panel.deleteProposal")(
  function* deleteProposalHandler(ref: {
    readonly eventSlug: string;
    readonly proposalId: number;
  }) {
    const { access, event } = yield* requirePanelEvent({
      mode: "write",
      slug: ref.eventSlug,
    });

    const sessions = yield* SessionStore;
    const agenda = yield* AgendaItemStore;
    const transaction = yield* StoreTransaction;

    yield* transaction.atomic(
      Effect.gen(function* deleteScopedProposal() {
        const session = yield* readProposalInEvent({
          eventId: event.id,
          proposalId: ref.proposalId,
        });

        const placed = yield* agenda.readBySession(session.id);

        if (Option.isSome(placed)) {
          const item = placed.value;

          yield* agenda.delete({ eventId: event.id, id: item.id });
          yield* sessions.update({
            changes: { scheduleConfirmed: false, status: "pending" },
            eventId: event.id,
            id: session.id,
          });
          yield* (yield* ChangeLogStore).logScheduleChange({
            action: "unassign",
            eventId: event.id,
            movedFromId: null,
            newEndTime: null,
            newSpaceId: null,
            newStartTime: null,
            oldEndTime: item.endTime,
            oldSpaceId: item.spaceId,
            oldStartTime: item.startTime,
            sessionId: session.id,
            userId: access.viewer.id,
          });
        }

        yield* sessions.softDelete({ eventId: event.id, id: session.id });
      })
    );

    return {};
  }
);

export const restoreProposalHandler = Effect.fn("Panel.restoreProposal")(
  function* restoreProposalHandler(ref: {
    readonly eventSlug: string;
    readonly proposalId: number;
  }) {
    const { event } = yield* requirePanelEvent({
      mode: "write",
      slug: ref.eventSlug,
    });

    yield* (yield* SessionStore).restore({
      eventId: event.id,
      id: SessionId.make(ref.proposalId),
    });

    return {};
  }
);

const optionalCount = (options: {
  readonly errors: FormError[];
  readonly field: string;
  readonly max?: number;
  readonly raw: string;
}) => {
  const raw = options.raw.trim();

  if (raw === "") {
    return 0;
  }

  if (!/^\d+$/u.test(raw)) {
    options.errors.push(formError(options.field, "Enter a whole number."));

    return 0;
  }

  const value = Number(raw);
  const max = options.max ?? STORAGE_LIMIT;

  if (value > max) {
    options.errors.push(
      formError(
        options.field,
        "Ensure this value is less than or equal to %(limit_value)s.",
        {
          limit_value: max,
        }
      )
    );
  }

  return value;
};

const requiredText = (options: {
  readonly errors: FormError[];
  readonly field: string;
  readonly message: string;
  readonly raw: string;
}) => {
  const value = options.raw.trim();

  if (value === "") {
    options.errors.push(formError(options.field, options.message));
  } else if (value.length > TEXT_MAX_LENGTH) {
    options.errors.push(
      formError(
        options.field,
        "Ensure this value has at most %(limit_value)d characters (it has %(show_value)d).",
        { limit_value: TEXT_MAX_LENGTH, show_value: value.length }
      )
    );
  }

  return value;
};

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/u;

export const isoDuration = (hours: number, minutes: number) => {
  if (hours === 0 && minutes === 0) {
    return "";
  }

  return `PT${hours > 0 ? `${hours}H` : ""}${minutes > 0 ? `${minutes}M` : ""}`;
};

const cleanProposal = Effect.fn("Panel.cleanProposal")(
  function* cleanProposal(options: {
    readonly eventId: EventId;
    readonly form: ProposalForm;
  }) {
    const { form } = options;
    const errors: FormError[] = [];

    const categories = yield* (yield* ProposalCategoryStore).listByEvent(
      options.eventId
    );

    const title = requiredText({
      errors,
      field: "title",
      message: "Title is required.",
      raw: form.title,
    });

    const facilitatorName = requiredText({
      errors,
      field: "facilitator_name",
      message: "Presenter name is required.",
      raw: form.facilitatorName,
    });

    const category = categories.find(
      (known) => String(known.id) === form.categoryId.trim()
    );

    if (form.categoryId.trim() === "") {
      errors.push(formError("category_id", "Please select a category."));
    } else if (category === undefined) {
      errors.push(formError("category_id", "Invalid category selection."));
    }

    const contactEmail = form.contactEmail.trim();

    if (contactEmail !== "" && !EMAIL.test(contactEmail)) {
      errors.push(formError("contact_email", "Enter a valid email address."));
    }

    const participantsLimit = optionalCount({
      errors,
      field: "participants_limit",
      raw: form.participantsLimit,
    });

    const minAge = optionalCount({
      errors,
      field: "min_age",
      raw: form.minAge,
    });

    const hours = optionalCount({
      errors,
      field: "duration_hours",
      max: MAX_DURATION_HOURS,
      raw: form.durationHours,
    });

    const minutes = optionalCount({
      errors,
      field: "duration_minutes",
      max: MAX_DURATION_MINUTES,
      raw: form.durationMinutes,
    });

    if (form.proposalId === null && form.facilitatorIds.length === 0) {
      errors.push(formError("", "Please select at least one facilitator."));
    }

    if (errors.length > 0 || category === undefined) {
      return yield* new FormInvalid({ errors });
    }

    return {
      categoryId: ProposalCategoryId.make(category.id),
      contactEmail,
      description: form.description.trim(),
      duration: isoDuration(hours, minutes),
      facilitatorName,
      minAge,
      participantsLimit,
      title,
    };
  }
);

const scopedIds = Effect.fn("Panel.scopedProposalIds")(
  function* scopedIds(options: {
    readonly eventId: EventId;
    readonly form: ProposalForm;
  }) {
    const facilitators = yield* (yield* FacilitatorStore).listByEvent({
      eventId: options.eventId,
      filters: {
        ids: options.form.facilitatorIds.map((id) => FacilitatorId.make(id)),
      },
    });

    const tracks = yield* (yield* TrackStore).listByEvent(options.eventId);

    const knownFacilitators = new Set<number>(
      facilitators.map((facilitator) => facilitator.id)
    );

    const knownTracks = new Set<number>(tracks.map((track) => track.id));

    return {
      facilitatorIds: options.form.facilitatorIds
        .filter((id) => knownFacilitators.has(id))
        .map((id) => FacilitatorId.make(id)),
      trackIds: options.form.trackIds
        .filter((id) => knownTracks.has(id))
        .map((id) => TrackId.make(id)),
    };
  }
);

export const saveProposalHandler = Effect.fn("Panel.saveProposal")(
  function* saveProposalHandler(form: ProposalForm) {
    const { event } = yield* requirePanelEvent({
      mode: "write",
      slug: form.eventSlug,
    });

    const sessions = yield* SessionStore;
    const transaction = yield* StoreTransaction;

    return yield* transaction.atomic(
      Effect.gen(function* saveScopedProposal() {
        const existing =
          form.proposalId === null
            ? Option.none()
            : Option.some(
                yield* readProposalInEvent({
                  eventId: event.id,
                  proposalId: form.proposalId,
                })
              );

        const cleaned = yield* cleanProposal({ eventId: event.id, form });
        const ids = yield* scopedIds({ eventId: event.id, form });

        if (Option.isSome(existing)) {
          const session = existing.value;

          yield* sessions.update({
            changes: cleaned,
            eventId: event.id,
            id: session.id,
          });
          yield* sessions.setFacilitators({
            eventId: event.id,
            facilitatorIds: ids.facilitatorIds,
            sessionId: session.id,
          });
          yield* sessions.setTracks({
            eventId: event.id,
            sessionId: session.id,
            trackIds: ids.trackIds,
          });

          return { id: session.id };
        }

        const slug = yield* uniqueSlug({
          attempts: 8,
          base: transliteratedSlugify(cleaned.title, SESSION_SLUG_MAX_LENGTH),
          exists: (candidate) =>
            sessions.slugExists({ eventId: event.id, slug: candidate }),
          trim: (base, suffix) =>
            transliteratedSlugify(
              base,
              SESSION_SLUG_MAX_LENGTH - suffix.length - 1
            ),
        });

        const id = yield* sessions.create({
          ...cleaned,
          eventId: event.id,
          facilitatorIds: ids.facilitatorIds,
          ident: "",
          presenterId: null,
          scheduleConfirmed: false,
          slug,
          status: "pending",
          timeSlotIds: form.timeSlotIds.map((slot) => TimeSlotId.make(slot)),
          trackIds: ids.trackIds,
        });

        return { id };
      })
    );
  }
);

export const changeProposalStatus = implement(
  changeProposalStatusContract,
  changeProposalStatusHandler
);

export const deleteProposal = implement(
  deleteProposalContract,
  deleteProposalHandler
);

export const restoreProposal = implement(
  restoreProposalContract,
  restoreProposalHandler
);

export const saveProposal = implement(
  saveProposalContract,
  saveProposalHandler
);
