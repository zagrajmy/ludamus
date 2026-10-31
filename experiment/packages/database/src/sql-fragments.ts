export const PUBLIC_SCHEDULED_SESSION = `
  s.deleted_at IS NULL
  AND EXISTS (SELECT 1 FROM agenda_item pa WHERE pa.session_id = s.id)
  AND NOT EXISTS (
    SELECT 1 FROM session_tracks pst JOIN track pt ON pt.id = pst.track_id
    WHERE pst.session_id = s.id AND pt.is_public = 0
  )`;

export const OCCUPYING = `('confirmed', 'offered')`;

export const ROW_BUDGET = {
  announcements: 50,
  bans: 2000,
  changeLogPage: 200,
  encounters: 200,
  eventCategories: 500,
  eventFields: 500,
  eventSpaces: 2000,
  eventTimeSlots: 1000,
  eventTracks: 500,
  feedEvents: 500,
  lapsedOffers: 1000,
  panelFacilitators: 5000,
  panelSessions: 5000,
  participationsPerSession: 2000,
  parties: 200,
  proposalCards: 1000,
  scheduledSessions: 5000,
  sphereEvents: 1000,
} as const;
