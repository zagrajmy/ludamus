import type { SqlClient } from "effect/sql/SqlClient";
import type { Fragment } from "effect/sql/Statement";

export const seatsQuery = (options: {
  readonly sql: SqlClient;
  readonly now: string;
  readonly where: Fragment;
  readonly limit: number;
}) => {
  const { sql, now, where, limit } = options;

  const eligible = sql`
    ec.event_id = s.event_id
    AND ec.start_time < ${now} AND ${now} < ec.end_time
    AND s.participants_limit <> 0
    AND (ec.limit_to_end_time = 0 OR a.start_time < ec.end_time)`;

  return sql`
    WITH seat AS (
      SELECT s.id AS sessionId, s.participants_limit AS participantsLimit,
        (SELECT COUNT(*) FROM session_participant p
         WHERE p.session_id = s.id AND p.status IN ('confirmed', 'offered')) AS enrolledCount,
        (SELECT COUNT(*) FROM session_participant p
         WHERE p.session_id = s.id AND p.status = 'waiting') AS waitingCount,
        (SELECT MAX(ec.percentage_slots) FROM enrollment_config ec WHERE ${eligible}) AS maxPercentage,
        (SELECT json_group_array(ec.id ORDER BY ec.id) FROM enrollment_config ec WHERE ${eligible}) AS eligibleWindowIds
      FROM session s LEFT JOIN agenda_item a ON a.session_id = s.id
      WHERE ${where}
      LIMIT ${limit}
    ), sized AS (
      SELECT seat.*,
        CASE
          WHEN participantsLimit = 0 THEN 0
          WHEN maxPercentage IS NULL THEN participantsLimit
          ELSE (participantsLimit * maxPercentage + 99) / 100
        END AS effectiveParticipantsLimit
      FROM seat
    )
    SELECT sessionId, participantsLimit, enrolledCount, waitingCount,
      eligibleWindowIds, effectiveParticipantsLimit,
      MAX(0, effectiveParticipantsLimit - enrolledCount) AS seatsLeft,
      (participantsLimit <> 0 AND enrolledCount >= effectiveParticipantsLimit) AS isFull
    FROM sized`;
};
