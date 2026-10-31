import { implement } from "@zagrajmy/capability/implement";
import { Effect, Option } from "effect";

import {
  createTrackContract,
  deleteTrackContract,
  updateTrackContract,
} from "../contracts.js";
import { SpaceId, UserId } from "../ids.js";
import type { EventId, TrackId } from "../ids.js";
import { CurrentSphere } from "../ports/current-sphere.js";
import { PanelStore } from "../ports/panel-store.js";
import { SpaceStore } from "../ports/space-store.js";
import { TrackStore } from "../ports/track-store.js";
import { StoreTransaction } from "../ports/transaction.js";
import { requirePanelEvent } from "./access.js";
import { FormInvalid, formError } from "./schemas.js";
import type { TrackEditForm, TrackForm } from "./schemas.js";
import { djangoSlugify, uniqueSlug } from "./slugs.js";

const TRACK_NAME_MAX_LENGTH = 255;

const TRACK_SLUG_ATTEMPTS = 4;

export const DUPLICATE_TRACK_NAME =
  "A track with this name already exists in this event. Pick another name.";

export const FOREIGN_TRACK_SELECTION =
  "Choose spaces from this event and managers from this sphere.";

export const cleanTrackName = (raw: string) => {
  const name = raw.trim();

  if (name === "") {
    return Option.none<string>();
  }

  return Option.some(name);
};

const validName = (raw: string) => {
  const name = cleanTrackName(raw);

  if (Option.isNone(name)) {
    return Effect.fail(
      new FormInvalid({
        errors: [formError("name", "Track name is required.")],
      })
    );
  }

  return name.value.length > TRACK_NAME_MAX_LENGTH
    ? Effect.fail(
        new FormInvalid({
          errors: [
            formError("name", "Track name is too long (max 255 characters)."),
          ],
        })
      )
    : Effect.succeed(name.value);
};

const scopedSelection = Effect.fn("Panel.scopedTrackSelection")(
  function* scopedSelection(options: {
    readonly eventId: EventId;
    readonly form: TrackForm;
  }) {
    const sphere = yield* CurrentSphere;
    const spaces = yield* (yield* SpaceStore).listByEvent(options.eventId);
    const managers = yield* (yield* PanelStore).sphereManagers(sphere.id);
    const spaceIds = new Set<number>(spaces.map((space) => space.id));
    const managerIds = new Set<number>(managers.map((manager) => manager.id));

    if (
      !options.form.spaceIds.every((id) => spaceIds.has(id)) ||
      !options.form.managerIds.every((id) => managerIds.has(id))
    ) {
      return yield* new FormInvalid({
        errors: [formError("", FOREIGN_TRACK_SELECTION)],
      });
    }

    const sorted = (ids: readonly number[]) =>
      [...new Set(ids)].toSorted((left, right) => left - right);

    return {
      managerIds: sorted(options.form.managerIds).map((id) => UserId.make(id)),
      spaceIds: sorted(options.form.spaceIds).map((id) => SpaceId.make(id)),
    };
  }
);

const trackSlug = Effect.fn("Panel.trackSlug")(function* trackSlug(options: {
  readonly eventId: EventId;
  readonly excludeId: TrackId | null;
  readonly name: string;
}) {
  const tracks = yield* TrackStore;

  return yield* uniqueSlug({
    attempts: TRACK_SLUG_ATTEMPTS,
    base: djangoSlugify(options.name),
    exists: (slug) =>
      tracks.slugExists({
        eventId: options.eventId,
        excludeId: options.excludeId,
        slug,
      }),
    trim: (base) => base,
  });
});

const duplicateName = () =>
  Effect.fail(
    new FormInvalid({ errors: [formError("name", DUPLICATE_TRACK_NAME)] })
  );

export const createTrackHandler = Effect.fn("Panel.createTrack")(
  function* createTrackHandler(form: TrackForm) {
    const { event } = yield* requirePanelEvent({
      mode: "write",
      slug: form.eventSlug,
    });

    const name = yield* validName(form.name);
    const transaction = yield* StoreTransaction;

    return yield* transaction.atomic(
      Effect.gen(function* createScopedTrack() {
        const selection = yield* scopedSelection({ eventId: event.id, form });

        const slug = yield* trackSlug({
          eventId: event.id,
          excludeId: null,
          name,
        });

        const track = yield* (yield* TrackStore)
          .create({
            eventId: event.id,
            track: { ...selection, isPublic: form.isPublic, name, slug },
          })
          .pipe(Effect.catchTag("DuplicateName", duplicateName));

        return { slug: track.slug };
      })
    );
  }
);

export const updateTrackHandler = Effect.fn("Panel.updateTrack")(
  function* updateTrackHandler(form: TrackEditForm) {
    const { event } = yield* requirePanelEvent({
      mode: "write",
      slug: form.eventSlug,
    });

    const tracks = yield* TrackStore;
    const transaction = yield* StoreTransaction;

    return yield* transaction.atomic(
      Effect.gen(function* updateScopedTrack() {
        const track = yield* tracks.readBySlug({
          eventId: event.id,
          slug: form.trackSlug,
        });

        const name = yield* validName(form.name);
        const selection = yield* scopedSelection({ eventId: event.id, form });

        const slug =
          name === track.name
            ? track.slug
            : yield* trackSlug({
                eventId: event.id,
                excludeId: track.id,
                name,
              });

        const updated = yield* tracks
          .update({
            eventId: event.id,
            id: track.id,
            track: { ...selection, isPublic: form.isPublic, name, slug },
          })
          .pipe(Effect.catchTag("DuplicateName", duplicateName));

        return { slug: updated.slug };
      })
    );
  }
);

export const deleteTrackHandler = Effect.fn("Panel.deleteTrack")(
  function* deleteTrackHandler(ref: {
    readonly eventSlug: string;
    readonly trackSlug: string;
  }) {
    const { event } = yield* requirePanelEvent({
      mode: "write",
      slug: ref.eventSlug,
    });

    const tracks = yield* TrackStore;
    const transaction = yield* StoreTransaction;

    yield* transaction.atomic(
      Effect.gen(function* deleteScopedTrack() {
        const track = yield* tracks.readBySlug({
          eventId: event.id,
          slug: ref.trackSlug,
        });

        yield* tracks.delete({ eventId: event.id, id: track.id });
      })
    );

    return {};
  }
);

export const createTrack = implement(createTrackContract, createTrackHandler);

export const updateTrack = implement(updateTrackContract, updateTrackHandler);

export const deleteTrack = implement(deleteTrackContract, deleteTrackHandler);

export const loadTracksPage = Effect.fn("Panel.loadTracksPage")(
  function* loadTracksPage(eventId: EventId) {
    return yield* (yield* TrackStore).listWithAssignments(eventId);
  }
);

export const loadTrackFormOptions = Effect.fn("Panel.loadTrackFormOptions")(
  function* loadTrackFormOptions(eventId: EventId) {
    const sphere = yield* CurrentSphere;
    const spaces = yield* (yield* SpaceStore).listByEvent(eventId);
    const managers = yield* (yield* PanelStore).sphereManagers(sphere.id);

    return { managers, spaces };
  }
);

export const loadTrackEdit = Effect.fn("Panel.loadTrackEdit")(
  function* loadTrackEdit(options: {
    readonly eventId: EventId;
    readonly trackSlug: string;
  }) {
    const tracks = yield* TrackStore;

    const track = yield* tracks.readBySlug({
      eventId: options.eventId,
      slug: options.trackSlug,
    });

    const spaceIds = yield* tracks.spaceIds(track.id);
    const managerIds = yield* tracks.managerIds(track.id);

    return { managerIds, spaceIds, track };
  }
);
