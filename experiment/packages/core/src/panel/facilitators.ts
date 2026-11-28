import { implement } from "@zagrajmy/capability/implement";
import { Effect, Option, Schema } from "effect";

import type { ContentFieldChange } from "../change-log.js";
import {
  createFacilitatorContract,
  deleteFacilitatorContract,
  restoreFacilitatorContract,
  updateFacilitatorContract,
} from "../contracts.js";
import { AccreditationType } from "../facilitator.js";
import type { EventId } from "../ids.js";
import { ChangeLogStore } from "../ports/change-log-store.js";
import { FacilitatorStore } from "../ports/facilitator-store.js";
import { SessionStore } from "../ports/session-store.js";
import { StoreTransaction } from "../ports/transaction.js";
import { requirePanelEvent } from "./access.js";
import { FacilitatorHasSessions, FormInvalid, formError } from "./schemas.js";
import type { FacilitatorEditForm, FacilitatorForm } from "./schemas.js";
import { djangoSlugify, uniqueSlug } from "./slugs.js";

const DISPLAY_NAME_MAX_LENGTH = 255;

const SLUG_BASE_MAX_LENGTH = 45;

const DELETED_LOG_VALUE = "yes";

export const parseAccreditation = (raw: string) =>
  raw === ""
    ? Effect.succeed<AccreditationType>("none")
    : Schema.decodeUnknownEffect(AccreditationType)(raw).pipe(
        Effect.mapError(
          () =>
            new FormInvalid({
              errors: [
                formError(
                  "accreditation_type",
                  "Select a valid choice. %(value)s is not one of the available choices.",
                  { value: raw }
                ),
              ],
            })
        )
      );

export const cleanDisplayName = (raw: string) => {
  const name = raw.trim();

  if (name === "") {
    return Effect.fail(
      new FormInvalid({
        errors: [formError("display_name", "Display name is required.")],
      })
    );
  }

  return name.length > DISPLAY_NAME_MAX_LENGTH
    ? Effect.fail(
        new FormInvalid({
          errors: [
            formError(
              "display_name",
              "Display name is too long (max 255 characters)."
            ),
          ],
        })
      )
    : Effect.succeed(name);
};

const facilitatorSlug = Effect.fn("Panel.facilitatorSlug")(
  function* facilitatorSlug(options: {
    readonly eventId: EventId;
    readonly name: string;
  }) {
    const facilitators = yield* FacilitatorStore;
    const base = djangoSlugify(options.name);

    return yield* uniqueSlug({
      attempts: 4,
      base: (base === "" ? "facilitator" : base).slice(0, SLUG_BASE_MAX_LENGTH),
      exists: (slug) =>
        facilitators.slugExists({ eventId: options.eventId, slug }),
      trim: (capped) => capped,
    });
  }
);

export const createFacilitatorHandler = Effect.fn("Panel.createFacilitator")(
  function* createFacilitatorHandler(form: FacilitatorForm) {
    const { access, event } = yield* requirePanelEvent({
      mode: "write",
      slug: form.eventSlug,
    });

    const displayName = yield* cleanDisplayName(form.displayName);
    const accreditationType = yield* parseAccreditation(form.accreditationType);
    const transaction = yield* StoreTransaction;

    return yield* transaction.atomic(
      Effect.gen(function* createScopedFacilitator() {
        const slug = yield* facilitatorSlug({
          eventId: event.id,
          name: displayName,
        });

        const created = yield* (yield* FacilitatorStore).create({
          accreditationType,
          displayName,
          eventId: event.id,
          ident: "",
          isCollective: form.isCollective,
          organizerId: form.assignMe ? access.viewer.id : null,
          slug,
          userId: null,
        });

        return { slug: created.slug };
      })
    );
  }
);

export const updateFacilitatorHandler = Effect.fn("Panel.updateFacilitator")(
  function* updateFacilitatorHandler(form: FacilitatorEditForm) {
    const { access, event } = yield* requirePanelEvent({
      mode: "write",
      slug: form.eventSlug,
    });

    const accreditationType = yield* parseAccreditation(form.accreditationType);
    const internalComment = form.internalComment.trim();
    const facilitators = yield* FacilitatorStore;
    const transaction = yield* StoreTransaction;

    return yield* transaction.atomic(
      Effect.gen(function* updateScopedFacilitator() {
        const facilitator = yield* facilitators.readBySlug({
          eventId: event.id,
          slug: form.facilitatorSlug,
        });

        const changes: ContentFieldChange[] = [
          {
            field: "accreditation_type",
            fieldId: null,
            new: accreditationType,
            old: facilitator.accreditationType,
          },
          {
            field: "internal_comment",
            fieldId: null,
            new: internalComment,
            old: facilitator.internalComment,
          },
          {
            field: "is_collective",
            fieldId: null,
            new: form.isCollective,
            old: facilitator.isCollective,
          },
        ].filter((change) => change.old !== change.new);

        yield* facilitators.update({
          changes: {
            accreditationType,
            internalComment,
            isCollective: form.isCollective,
          },
          eventId: event.id,
          id: facilitator.id,
        });

        if (changes.length > 0) {
          yield* (yield* ChangeLogStore).logFacilitatorChange({
            changes,
            eventId: event.id,
            facilitatorId: facilitator.id,
            userId: access.viewer.id,
          });
        }

        return { slug: facilitator.slug };
      })
    );
  }
);

const deletionLog = (deleted: boolean): ContentFieldChange => ({
  field: "deleted",
  fieldId: null,
  new: deleted ? DELETED_LOG_VALUE : "",
  old: deleted ? "" : DELETED_LOG_VALUE,
});

export const deleteFacilitatorHandler = Effect.fn("Panel.deleteFacilitator")(
  function* deleteFacilitatorHandler(ref: {
    readonly eventSlug: string;
    readonly facilitatorSlug: string;
  }) {
    const { access, event } = yield* requirePanelEvent({
      mode: "write",
      slug: ref.eventSlug,
    });

    const facilitators = yield* FacilitatorStore;
    const transaction = yield* StoreTransaction;

    yield* transaction.atomic(
      Effect.gen(function* deleteScopedFacilitator() {
        const facilitator = yield* facilitators.readBySlug({
          eventId: event.id,
          slug: ref.facilitatorSlug,
        });

        const scope = { eventId: event.id, id: facilitator.id };
        const counts = yield* facilitators.countSessions(scope);

        yield* counts.live > 0 || counts.deleted > 0
          ? Effect.fail(new FacilitatorHasSessions(counts))
          : Effect.void;

        yield* facilitators.softDelete(scope);
        yield* (yield* ChangeLogStore).logFacilitatorChange({
          changes: [deletionLog(true)],
          eventId: event.id,
          facilitatorId: facilitator.id,
          userId: access.viewer.id,
        });
      })
    );

    return {};
  }
);

export const restoreFacilitatorHandler = Effect.fn("Panel.restoreFacilitator")(
  function* restoreFacilitatorHandler(ref: {
    readonly eventSlug: string;
    readonly facilitatorSlug: string;
  }) {
    const { access, event } = yield* requirePanelEvent({
      mode: "write",
      slug: ref.eventSlug,
    });

    const facilitators = yield* FacilitatorStore;
    const transaction = yield* StoreTransaction;

    yield* transaction.atomic(
      Effect.gen(function* restoreScopedFacilitator() {
        const facilitator = yield* facilitators.readBySlugIncludingDeleted({
          eventId: event.id,
          slug: ref.facilitatorSlug,
        });

        yield* facilitators.restore({ eventId: event.id, id: facilitator.id });
        yield* (yield* ChangeLogStore).logFacilitatorChange({
          changes: [deletionLog(false)],
          eventId: event.id,
          facilitatorId: facilitator.id,
          userId: access.viewer.id,
        });
      })
    );

    return {};
  }
);

export const createFacilitator = implement(
  createFacilitatorContract,
  createFacilitatorHandler
);

export const updateFacilitator = implement(
  updateFacilitatorContract,
  updateFacilitatorHandler
);

export const deleteFacilitator = implement(
  deleteFacilitatorContract,
  deleteFacilitatorHandler
);

export const restoreFacilitator = implement(
  restoreFacilitatorContract,
  restoreFacilitatorHandler
);

export const loadFacilitatorDetail = Effect.fn("Panel.loadFacilitatorDetail")(
  function* loadFacilitatorDetail(options: {
    readonly eventId: EventId;
    readonly includeDeleted: boolean;
    readonly slug: string;
  }) {
    const facilitators = yield* FacilitatorStore;

    const read = options.includeDeleted
      ? facilitators.readBySlugIncludingDeleted
      : facilitators.readBySlug;

    const found = yield* read({
      eventId: options.eventId,
      slug: options.slug,
    }).pipe(
      Effect.map(Option.some),
      Effect.catchTag("NotFound", () => Effect.succeed(Option.none()))
    );

    if (Option.isNone(found)) {
      return Option.none();
    }

    const sessions = yield* (yield* SessionStore).listByFacilitator({
      eventId: options.eventId,
      facilitatorId: found.value.id,
    });

    return Option.some({ facilitator: found.value, sessions });
  }
);
