import {
  AnnouncementRow,
  FeedEncounterRow,
  FeedEventRow,
} from "@zagrajmy/core/feed";
import { FeedStore } from "@zagrajmy/core/ports/feed-store";
import { Effect, Layer } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { decodeRows } from "./rows.js";

const eventsPerSphere = 500;
const announcementsPerSphere = 50;
const upcomingEncounters = 500;
const pastEncounters = 24;

export const FeedStoreLive = Layer.effect(
  FeedStore,
  Effect.gen(function* makeFeedStore() {
    const sql = yield* SqlClient;

    const visibleEncounters = (
      sphereId: number,
      viewerId: number | null
    ) => sql`
      encounter.sphere_id = ${sphereId}
      AND (
        encounter.is_public = 1
        OR encounter.creator_id = ${viewerId ?? -1}
        OR EXISTS (
          SELECT 1 FROM encounter_rsvp mine
          WHERE mine.encounter_id = encounter.id AND mine.user_id = ${viewerId ?? -1}
        )
      )
    `;

    const encounterColumns = sql`
      encounter.id AS id, encounter.title AS title, encounter.game AS game,
      encounter.place AS place, encounter.start_time AS startTime,
      encounter.end_time AS endTime, encounter.max_participants AS maxParticipants,
      encounter.share_code AS shareCode, encounter.header_image AS headerImage,
      encounter.is_public AS isPublic, encounter.creator_id AS creatorId,
      COALESCE(NULLIF(creator.name, ''), creator.username, '') AS creatorName,
      (SELECT COUNT(*) FROM encounter_rsvp rsvp WHERE rsvp.encounter_id = encounter.id) AS rsvpCount
    `;

    return FeedStore.of({
      listAnnouncements: (sphereId) =>
        sql`
          SELECT id, title, content FROM announcement
          WHERE sphere_id = ${sphereId} AND is_published = 1
          ORDER BY creation_time DESC
          LIMIT ${announcementsPerSphere}
        `.pipe(decodeRows("FeedStore.listAnnouncements", AnnouncementRow)),
      listEvents: (sphereId) =>
        sql`
          SELECT event.id AS id, event.name AS name, event.slug AS slug,
                 event.description AS description, event.start_time AS startTime,
                 event.end_time AS endTime, event.publication_time AS publicationTime,
                 event.proposal_start_time AS proposalStartTime,
                 event.proposal_end_time AS proposalEndTime,
                 event.visibility AS visibility, event.cover_image AS coverImage,
                 (
                   SELECT COUNT(*) FROM session
                   JOIN agenda_item ON agenda_item.session_id = session.id
                   WHERE session.event_id = event.id
                     AND session.deleted_at IS NULL
                     AND NOT EXISTS (
                       SELECT 1 FROM session_tracks
                       JOIN track ON track.id = session_tracks.track_id
                       WHERE session_tracks.session_id = session.id AND track.is_public = 0
                     )
                 ) AS sessionCount
          FROM event
          WHERE event.sphere_id = ${sphereId}
          ORDER BY event.start_time ASC
          LIMIT ${eventsPerSphere}
        `.pipe(decodeRows("FeedStore.listEvents", FeedEventRow)),
      listPastEncounters: ({ now, sphereId, viewerId }) =>
        sql`
          SELECT ${encounterColumns}
          FROM encounter JOIN user creator ON creator.id = encounter.creator_id
          WHERE ${visibleEncounters(sphereId, viewerId)}
            AND (encounter.end_time < ${now} OR (encounter.end_time IS NULL AND encounter.start_time < ${now}))
          ORDER BY encounter.start_time DESC
          LIMIT ${pastEncounters}
        `.pipe(decodeRows("FeedStore.listPastEncounters", FeedEncounterRow)),
      listUpcomingEncounters: ({ now, sphereId, viewerId }) =>
        sql`
          SELECT ${encounterColumns}
          FROM encounter JOIN user creator ON creator.id = encounter.creator_id
          WHERE ${visibleEncounters(sphereId, viewerId)}
            AND NOT (encounter.end_time < ${now} OR (encounter.end_time IS NULL AND encounter.start_time < ${now}))
          ORDER BY encounter.start_time ASC
          LIMIT ${upcomingEncounters}
        `.pipe(
          decodeRows("FeedStore.listUpcomingEncounters", FeedEncounterRow)
        ),
    });
  })
);
