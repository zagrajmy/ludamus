import type { SqlClient } from "effect/sql/SqlClient";

export const lockSessionRowStatement = (sql: SqlClient, sessionId: number) =>
  sql`SELECT id FROM session WHERE id = ${sessionId} AND deleted_at IS NULL`;

export const lockSeatHoldersStatement = (
  sql: SqlClient,
  userIds: readonly number[]
) =>
  sql`SELECT id FROM user
    WHERE ${sql.in("id", userIds)}
      OR id IN (SELECT manager_id FROM user
        WHERE ${sql.in("id", userIds)} AND user_type = 'connected' AND manager_id IS NOT NULL)
    ORDER BY id LIMIT ${userIds.length * 2}`;
