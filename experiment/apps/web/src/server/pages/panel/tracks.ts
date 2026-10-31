import type { Event } from "@zagrajmy/core";
import {
  loadTrackEdit,
  loadTrackFormOptions,
  loadTracksPage,
} from "@zagrajmy/core/panel/tracks";
import { Effect, Option, pipe } from "effect";

import type {
  TrackFormFlags,
  TracksFlags,
} from "../../../client/panel/tracks/flags.js";

export const loadTracks = Effect.fn("PanelPages.loadTracks")(
  function* loadTracks(event: Event) {
    const tracks = yield* loadTracksPage(event.id);

    const flags: TracksFlags = {
      eventSlug: event.slug,
      tracks: tracks.map((track) => ({
        isPublic: track.isPublic,
        managerNames: track.managerNames,
        name: track.name,
        slug: track.slug,
        spaceNames: track.spaceNames,
      })),
    };

    return flags;
  }
);

export const loadTrackForm = Effect.fn("PanelPages.loadTrackForm")(
  function* loadTrackForm(event: Event, trackSlug: Option.Option<string>) {
    const options = yield* loadTrackFormOptions(event.id);

    const base = {
      eventSlug: event.slug,
      managers: options.managers.map((manager) => ({
        id: manager.id,
        name: manager.name,
      })),
      spaces: options.spaces.map((space) => ({
        id: space.id,
        name: space.name,
      })),
    };

    if (Option.isNone(trackSlug)) {
      const created: TrackFormFlags = {
        ...base,
        trackSlug: Option.none(),
        values: { isPublic: true, managerIds: [], name: "", spaceIds: [] },
      };

      return Option.some(created);
    }

    type TrackEdit = Effect.Success<ReturnType<typeof loadTrackEdit>>;

    const edit: Option.Option<TrackEdit> = yield* loadTrackEdit({
      eventId: event.id,
      trackSlug: trackSlug.value,
    }).pipe(
      Effect.map(Option.some),
      Effect.catchTag("NotFound", () => Effect.succeed(Option.none<TrackEdit>()))
    );

    return pipe(edit, 
      Option.map(({ managerIds, spaceIds, track }): TrackFormFlags => ({
        ...base,
        trackSlug: Option.some(track.slug),
        values: {
          isPublic: track.isPublic,
          managerIds,
          name: track.name,
          spaceIds,
        },
      }))
    );
  }
);
