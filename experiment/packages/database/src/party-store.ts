import {
  MembershipRequest,
  PartyConsentMode,
  PartyId,
  PartyMembershipId,
  PartyMembershipStatus,
  PartyStore,
  StoreError,
  UserId,
} from "@zagrajmy/core";
import type { Party, PartyMember } from "@zagrajmy/core";
import { DateTime, Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import type { Fragment } from "effect/sql/Statement";

import {
  decodeFirst,
  decodeInput,
  decodeRows,
  IdRow,
  SqlDateTime,
  toSqlDateTime,
} from "./rows.js";
import { USER_SUMMARY_COLUMNS, UserSummaryRow } from "./shared-rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const LEADER_COLUMNS = `
  u.id AS leaderId, u.name AS leaderName, u.slug AS leaderSlug, u.username AS leaderUsername,
  u.email AS leaderEmail, u.avatar_url AS leaderAvatarUrl, u.use_gravatar AS leaderUseGravatar,
  u.user_type AS leaderUserType, u.manager_id AS leaderManagerId`;

const PartyRow = Schema.Struct({
  createdAt: SqlDateTime,
  id: PartyId,
  leaderAvatarUrl: UserSummaryRow.fields.avatarUrl,
  leaderEmail: UserSummaryRow.fields.email,
  leaderId: UserSummaryRow.fields.id,
  leaderManagerId: UserSummaryRow.fields.managerId,
  leaderName: UserSummaryRow.fields.name,
  leaderSlug: UserSummaryRow.fields.slug,
  leaderUseGravatar: UserSummaryRow.fields.useGravatar,
  leaderUserType: UserSummaryRow.fields.userType,
  leaderUsername: UserSummaryRow.fields.username,
  name: Schema.String,
});

type PartyRow = typeof PartyRow.Type;

const MemberRow = Schema.Struct({
  ...UserSummaryRow.fields,
  claimToken: Schema.String,
  consentMode: PartyConsentMode,
  membershipId: PartyMembershipId,
  partyId: PartyId,
  status: PartyMembershipStatus,
});

const InviteRow = Schema.Struct({
  ...PartyRow.fields,
  membershipId: PartyMembershipId,
});

const PartyIdRow = Schema.Struct({ id: PartyId });

const StatusRow = Schema.Struct({ status: PartyMembershipStatus });

const ViewerInput = Schema.Struct({ partyId: PartyId, viewerId: UserId });

const CreateInput = Schema.Struct({
  inviteToken: Schema.String,
  leaderId: UserId,
  name: Schema.String,
});

const LeaderInput = Schema.Struct({ leaderId: UserId, partyId: PartyId });

const RenameInput = Schema.Struct({
  leaderId: UserId,
  name: Schema.String,
  partyId: PartyId,
});

const TokenWriteInput = Schema.Struct({
  leaderId: UserId,
  partyId: PartyId,
  token: Schema.String,
});

const TokenReadInput = Schema.Struct({
  token: Schema.String,
  viewerId: UserId,
});

const JoinInput = Schema.Struct({ token: Schema.String, userId: UserId });

const InviteActionInput = Schema.Struct({
  membershipId: PartyMembershipId,
  userId: UserId,
});

const RemoveInput = Schema.Struct({
  leaderId: UserId,
  membershipId: PartyMembershipId,
  partyId: PartyId,
});

const ConsentInput = Schema.Struct({
  mode: PartyConsentMode,
  partyId: PartyId,
  userId: UserId,
});

const LeaveInput = Schema.Struct({ partyId: PartyId, userId: UserId });

const leaderOf = (row: PartyRow) => ({
  avatarUrl: row.leaderAvatarUrl,
  email: row.leaderEmail,
  id: row.leaderId,
  managerId: row.leaderManagerId,
  name: row.leaderName,
  slug: row.leaderSlug,
  useGravatar: row.leaderUseGravatar,
  userType: row.leaderUserType,
  username: row.leaderUsername,
});

export const makePartyStore = Effect.gen(function* makePartyStore() {
  const sql = yield* SqlClient;

  const partyColumns = sql.literal(
    `p.id AS id, p.name AS name, p.created_at AS createdAt, ${LEADER_COLUMNS}`
  );

  const partiesWhere = Effect.fn("PartyStore.partiesWhere")(
    function* partiesWhere(options: {
      readonly operation: string;
      readonly viewerId: UserId;
      readonly where: Fragment;
    }) {
      const parties = yield* sql`
      SELECT ${partyColumns} FROM party p JOIN user u ON u.id = p.leader_id
      WHERE ${options.where}
        AND (p.leader_id = ${options.viewerId} OR EXISTS (
          SELECT 1 FROM party_membership vm
          WHERE vm.party_id = p.id AND vm.member_id = ${options.viewerId} AND vm.status = 'active'))
      ORDER BY p.id LIMIT ${ROW_BUDGET.parties}
    `.pipe(decodeRows(options.operation, PartyRow));

      if (parties.length === 0) {
        return [];
      }

      const members = yield* sql`
      SELECT m.id AS membershipId, m.party_id AS partyId, m.consent_mode AS consentMode,
        m.status AS status,
        CASE WHEN u.manager_id = ${options.viewerId} THEN u.claim_token ELSE '' END AS claimToken,
        ${sql.literal(USER_SUMMARY_COLUMNS("u"))}
      FROM party_membership m JOIN party p ON p.id = m.party_id JOIN user u ON u.id = m.member_id
      WHERE ${sql.in(
        "m.party_id",
        parties.map((party) => party.id)
      )}
      ORDER BY m.party_id, (m.member_id = p.leader_id) DESC, m.id
      LIMIT ${ROW_BUDGET.parties * ROW_BUDGET.parties}
    `.pipe(decodeRows(options.operation, MemberRow));

      const byParty = new Map<PartyId, PartyMember[]>();

      for (const {
        partyId,
        membershipId,
        consentMode,
        status,
        claimToken,
        ...user
      } of members) {
        const list = byParty.get(partyId) ?? [];
        list.push({ claimToken, consentMode, membershipId, status, user });
        byParty.set(partyId, list);
      }

      return parties.map((party): Party => ({
        createdAt: party.createdAt,
        id: party.id,
        leader: leaderOf(party),
        members: byParty.get(party.id) ?? [],
        name: party.name,
      }));
    }
  );

  const listForViewer = Effect.fn("PartyStore.listForViewer")(
    function* listForViewer(viewerId: UserId) {
      const valid = yield* decodeInput(
        "PartyStore.listForViewer",
        UserId
      )(viewerId);

      return yield* partiesWhere({
        operation: "PartyStore.listForViewer",
        viewerId: valid,
        where: sql`1 = 1`,
      });
    }
  );

  const readForViewer = Effect.fn("PartyStore.readForViewer")(
    function* readForViewer(options: typeof ViewerInput.Type) {
      const input = yield* decodeInput(
        "PartyStore.readForViewer",
        ViewerInput
      )(options);

      const parties = yield* partiesWhere({
        operation: "PartyStore.readForViewer",
        viewerId: input.viewerId,
        where: sql`p.id = ${input.partyId}`,
      });

      return Option.fromNullishOr(parties[0]);
    }
  );

  const listInvites = Effect.fn("PartyStore.listInvites")(function* listInvites(
    viewerId: UserId
  ) {
    const valid = yield* decodeInput(
      "PartyStore.listInvites",
      UserId
    )(viewerId);

    const rows = yield* sql`
      SELECT m.id AS membershipId, ${partyColumns}
      FROM party_membership m JOIN party p ON p.id = m.party_id JOIN user u ON u.id = p.leader_id
      WHERE m.member_id = ${valid} AND m.status = 'invited'
      ORDER BY m.id LIMIT ${ROW_BUDGET.parties}
    `.pipe(decodeRows("PartyStore.listInvites", InviteRow));

    return rows.map((row) => ({
      leader: leaderOf(row),
      membershipId: row.membershipId,
      partyId: row.id,
      partyName: row.name,
    }));
  });

  const create = Effect.fn("PartyStore.create")(function* create(
    options: typeof CreateInput.Type
  ) {
    const input = yield* decodeInput("PartyStore.create", CreateInput)(options);
    const now = toSqlDateTime(yield* DateTime.now);

    return yield* Effect.gen(function* insertParty() {
      const rows = yield* sql`
        INSERT INTO party ${sql.insert({
          created_at: now,
          invite_token: input.inviteToken,
          leader_id: input.leaderId,
          name: input.name,
        })} RETURNING id
      `.pipe(decodeRows("PartyStore.create", PartyIdRow));

      const partyId = rows[0]?.id;

      if (partyId === undefined) {
        return yield* new StoreError({
          operation: "PartyStore.create",
          reason: "insert returned no id",
        });
      }

      yield* sql`INSERT INTO party_membership ${sql.insert({
        consent_mode: "accept_by_default",
        member_id: input.leaderId,
        party_id: partyId,
        status: "active",
      })}`;

      return partyId;
    }).pipe(
      sql.withTransaction,
      Effect.catchTag("SqlError", () =>
        Effect.fail(
          new StoreError({ operation: "PartyStore.create", reason: "SqlError" })
        )
      )
    );
  });

  const rename = Effect.fn("PartyStore.rename")(function* rename(
    options: typeof RenameInput.Type
  ) {
    const input = yield* decodeInput("PartyStore.rename", RenameInput)(options);

    const rows = yield* sql`
      UPDATE party SET name = ${input.name} WHERE id = ${input.partyId} AND leader_id = ${input.leaderId} RETURNING id
    `.pipe(decodeRows("PartyStore.rename", IdRow));

    return rows.length > 0;
  });

  const remove = Effect.fn("PartyStore.delete")(function* remove(
    options: typeof LeaderInput.Type
  ) {
    const input = yield* decodeInput("PartyStore.delete", LeaderInput)(options);

    const rows = yield* Effect.gen(function* deleteParty() {
      const owned = sql`SELECT id FROM party WHERE id = ${input.partyId} AND leader_id = ${input.leaderId}`;
      yield* sql`UPDATE session_participant SET party_id = NULL WHERE party_id IN (${owned})`;
      yield* sql`DELETE FROM party_membership WHERE party_id IN (${owned})`;

      return yield* sql`DELETE FROM party WHERE id = ${input.partyId} AND leader_id = ${input.leaderId} RETURNING id`;
    }).pipe(
      sql.withTransaction,
      Effect.catchTag("SqlError", () =>
        Effect.fail(
          new StoreError({ operation: "PartyStore.delete", reason: "SqlError" })
        )
      )
    );

    return rows.length > 0;
  });

  const setInviteToken = Effect.fn("PartyStore.setInviteToken")(
    function* setInviteToken(options: typeof TokenWriteInput.Type) {
      const input = yield* decodeInput(
        "PartyStore.setInviteToken",
        TokenWriteInput
      )(options);

      const rows = yield* sql`
      UPDATE party SET invite_token = ${input.token} WHERE id = ${input.partyId} AND leader_id = ${input.leaderId}
      RETURNING id
    `.pipe(decodeRows("PartyStore.setInviteToken", IdRow));

      return rows.length > 0;
    }
  );

  const readByInviteToken = Effect.fn("PartyStore.readByInviteToken")(
    function* readByInviteToken(options: typeof TokenReadInput.Type) {
      const input = yield* decodeInput(
        "PartyStore.readByInviteToken",
        TokenReadInput
      )(options);

      if (input.token === "") {
        return Option.none();
      }

      const row = yield* sql`
      SELECT ${partyColumns},
        EXISTS (SELECT 1 FROM party_membership m WHERE m.party_id = p.id
          AND m.member_id = ${input.viewerId} AND m.status = 'active') AS alreadyMember
      FROM party p JOIN user u ON u.id = p.leader_id WHERE p.invite_token = ${input.token}
    `.pipe(
        decodeFirst(
          "PartyStore.readByInviteToken",
          Schema.Struct({
            ...PartyRow.fields,
            alreadyMember: Schema.BooleanFromBit,
          })
        )
      );

      return row.pipe(
        Option.map((party) => ({
          alreadyMember: party.alreadyMember,
          id: party.id,
          leader: leaderOf(party),
          name: party.name,
        }))
      );
    }
  );

  const joinViaToken = Effect.fn("PartyStore.joinViaToken")(
    function* joinViaToken(options: typeof JoinInput.Type) {
      const input = yield* decodeInput(
        "PartyStore.joinViaToken",
        JoinInput
      )(options);

      if (input.token === "") {
        return Option.none();
      }

      const party =
        yield* sql`SELECT id FROM party WHERE invite_token = ${input.token}`.pipe(
          decodeFirst("PartyStore.joinViaToken", PartyIdRow)
        );

      if (Option.isNone(party)) {
        return Option.none();
      }

      const partyId = party.value.id;

      const existing = yield* sql`
      SELECT status FROM party_membership WHERE party_id = ${partyId} AND member_id = ${input.userId}
    `.pipe(decodeFirst("PartyStore.joinViaToken", StatusRow));

      if (Option.isNone(existing)) {
        yield* sql`INSERT INTO party_membership ${sql.insert({
          consent_mode: "accept_invites",
          member_id: input.userId,
          party_id: partyId,
          status: "active",
        })}`.pipe(decodeRows("PartyStore.joinViaToken", IdRow));

        return Option.some({ joined: true, partyId });
      }

      if (existing.value.status === "invited") {
        yield* sql`
        UPDATE party_membership SET status = 'active' WHERE party_id = ${partyId} AND member_id = ${input.userId}
      `.pipe(decodeRows("PartyStore.joinViaToken", IdRow));

        return Option.some({ joined: true, partyId });
      }

      return Option.some({ joined: false, partyId });
    }
  );

  const createMembershipIfAbsent = Effect.fn(
    "PartyStore.createMembershipIfAbsent"
  )(function* createMembershipIfAbsent(request: typeof MembershipRequest.Type) {
    const input = yield* decodeInput(
      "PartyStore.createMembershipIfAbsent",
      MembershipRequest
    )(request);

    const rows = yield* sql`
        INSERT INTO party_membership ${sql.insert({
          consent_mode: input.consentMode,
          member_id: input.userId,
          party_id: input.partyId,
          status: input.status,
        })} ON CONFLICT (party_id, member_id) DO NOTHING RETURNING id
      `.pipe(decodeRows("PartyStore.createMembershipIfAbsent", IdRow));

    return rows.length > 0;
  });

  const acceptInvite = Effect.fn("PartyStore.acceptInvite")(
    function* acceptInvite(options: typeof InviteActionInput.Type) {
      const input = yield* decodeInput(
        "PartyStore.acceptInvite",
        InviteActionInput
      )(options);

      const rows = yield* sql`
      UPDATE party_membership SET status = 'active'
      WHERE id = ${input.membershipId} AND member_id = ${input.userId} AND status = 'invited' RETURNING id
    `.pipe(decodeRows("PartyStore.acceptInvite", IdRow));

      return rows.length > 0;
    }
  );

  const declineInvite = Effect.fn("PartyStore.declineInvite")(
    function* declineInvite(options: typeof InviteActionInput.Type) {
      const input = yield* decodeInput(
        "PartyStore.declineInvite",
        InviteActionInput
      )(options);

      const rows = yield* sql`
      DELETE FROM party_membership
      WHERE id = ${input.membershipId} AND member_id = ${input.userId} AND status = 'invited' RETURNING id
    `.pipe(decodeRows("PartyStore.declineInvite", IdRow));

      return rows.length > 0;
    }
  );

  const removeMember = Effect.fn("PartyStore.removeMember")(
    function* removeMember(options: typeof RemoveInput.Type) {
      const input = yield* decodeInput(
        "PartyStore.removeMember",
        RemoveInput
      )(options);

      const rows = yield* sql`
      DELETE FROM party_membership
      WHERE id = ${input.membershipId} AND party_id = ${input.partyId} AND member_id <> ${input.leaderId}
        AND party_id IN (SELECT id FROM party WHERE leader_id = ${input.leaderId})
      RETURNING status
    `.pipe(decodeRows("PartyStore.removeMember", StatusRow));

      return Option.map(Option.fromNullishOr(rows[0]), (row) => row.status);
    }
  );

  const setConsent = Effect.fn("PartyStore.setConsent")(function* setConsent(
    options: typeof ConsentInput.Type
  ) {
    const input = yield* decodeInput(
      "PartyStore.setConsent",
      ConsentInput
    )(options);

    const rows = yield* sql`
      UPDATE party_membership SET consent_mode = ${input.mode}
      WHERE party_id = ${input.partyId} AND member_id = ${input.userId} AND status = 'active'
        AND party_id NOT IN (SELECT id FROM party WHERE leader_id = ${input.userId})
        AND member_id NOT IN (SELECT id FROM user WHERE user_type = 'connected')
      RETURNING id
    `.pipe(decodeRows("PartyStore.setConsent", IdRow));

    return rows.length > 0;
  });

  const leave = Effect.fn("PartyStore.leave")(function* leave(
    options: typeof LeaveInput.Type
  ) {
    const input = yield* decodeInput("PartyStore.leave", LeaveInput)(options);

    const rows = yield* sql`
      DELETE FROM party_membership
      WHERE party_id = ${input.partyId} AND member_id = ${input.userId} AND status = 'active'
        AND party_id NOT IN (SELECT id FROM party WHERE leader_id = ${input.userId})
      RETURNING id
    `.pipe(decodeRows("PartyStore.leave", IdRow));

    return rows.length > 0;
  });

  return PartyStore.of({
    acceptInvite,
    create,
    createMembershipIfAbsent,
    declineInvite,
    delete: remove,
    joinViaToken,
    leave,
    listForViewer,
    listInvites,
    readByInviteToken,
    readForViewer,
    removeMember,
    rename,
    setConsent,
    setInviteToken,
  });
});

export const PartyStoreLive = Layer.effect(PartyStore, makePartyStore);
