import { DateTime, Effect, Option } from "effect";

import { PartyId, UserId } from "../ids.js";
import type { ParticipationStatus } from "../participation.js";
import type { Party } from "../party.js";
import { CurrentSphere } from "../ports/current-sphere.js";
import { CurrentViewer } from "../ports/current-viewer.js";
import { PartyStore } from "../ports/party-store.js";
import { NotFound } from "../ports/store-error.js";
import { UserDirectory } from "../ports/user-store.js";
import { fullName } from "../user.js";
import { hasSlotAccess, slotAllowance } from "./allowance.js";
import { EnrollmentRefused, LoginRequired } from "./api.js";
import type {
  EnrollmentNotice,
  HouseholdSeat,
  PartyChoice,
  RefusalDestination,
  RosterPerson,
  SessionContext,
} from "./api.js";
import { overlapsWith } from "./conflicts.js";
import { EnrollmentStore } from "./ports.js";
import type { FormPolicy, RosterFacts } from "./roster.js";
import type {
  EnrollmentWindowRules,
  VirtualEnrollmentConfig,
} from "./schemas.js";
import {
  canEnroll,
  policyForActor,
  policyMaxWaitlistSessions,
  requiresSlotAllowance,
  restrictsEveryone,
} from "./windows.js";

export const ENROLL_WITHOUT_PARTY = "none";

export const notice = (
  level: EnrollmentNotice["level"],
  msgid: string,
  vars: Readonly<Record<string, string>> = {}
): EnrollmentNotice => ({ args: [], items: [], level, msgid, vars });

export const refuse = (options: {
  readonly destination: RefusalDestination;
  readonly eventSlug: string | null;
  readonly notices: readonly EnrollmentNotice[];
}) =>
  new EnrollmentRefused({
    destination: options.destination,
    eventSlug: options.eventSlug,
    footer: null,
    notices: options.notices,
  });

export const requireViewer = Effect.gen(function* requireViewer() {
  const viewer = yield* CurrentViewer;

  if (Option.isNone(viewer)) {
    return yield* new LoginRequired({ capability: "enrollment" });
  }

  return viewer.value;
});

export const loadSession = Effect.fn("Enrollment.loadSession")(
  function* loadSession(sessionId: number) {
    const viewer = yield* requireViewer;
    const sphere = yield* CurrentSphere;
    const store = yield* EnrollmentStore;
    const now = yield* DateTime.now;

    const found = yield* store.readSessionContext({
      now,
      sessionId,
      sphereId: sphere.id,
      viewerId: viewer.id,
    });

    if (Option.isNone(found)) {
      return yield* new NotFound({ entity: "Session", key: String(sessionId) });
    }

    const session = found.value;

    if (session.agenda === null && !session.viewerHasParticipation) {
      return yield* refuse({
        destination: "index",
        eventSlug: null,
        notices: [
          notice(
            "error",
            "No enrollment configuration is available for this session."
          ),
        ],
      });
    }

    if (session.agenda !== null && !session.isPubliclyScheduled) {
      return yield* new NotFound({ entity: "Session", key: String(sessionId) });
    }

    if (session.viewerBanned) {
      return yield* refuse({
        destination: "event",
        eventSlug: session.eventSlug,
        notices: [],
      });
    }

    return { now, session, viewerId: viewer.id };
  }
);

interface Selection {
  readonly choices: readonly PartyChoice[];
  readonly selected: Party | null;
  readonly companionsShown: boolean;
}

const selectParty = (options: {
  readonly parties: readonly Party[];
  readonly viewerId: number;
  readonly requested: string | null;
}): Selection | null => {
  const { parties, viewerId, requested } = options;

  const choices = parties.map((party) => ({
    id: party.id,
    isOwnLed: party.leader.id === viewerId,
    leaderName: fullName(party.leader),
    name: party.name,
  }));

  let selected: Party | null;

  if (requested === ENROLL_WITHOUT_PARTY) {
    selected = null;
  } else if (requested === null) {
    selected =
      parties.find((party) => party.leader.id === viewerId) ??
      parties[0] ??
      null;
  } else {
    selected = parties.find((party) => String(party.id) === requested) ?? null;

    if (selected === null) {
      return null;
    }
  }

  return {
    choices,
    companionsShown: selected === null || selected.leader.id === viewerId,
    selected,
  };
};

export interface EnrollmentContext {
  readonly now: DateTime.Utc;
  readonly session: SessionContext;
  readonly viewer: RosterPerson;
  readonly choices: readonly PartyChoice[];
  readonly selectedParty: Party | null;
  readonly people: readonly RosterFacts[];
  readonly policy: FormPolicy;
  readonly eligible: readonly EnrollmentWindowRules[];
  readonly viewerIsConfigured: boolean;
  readonly slotAllowance: Option.Option<VirtualEnrollmentConfig>;
  readonly conflictedUserIds: readonly number[];
  readonly companionIds: readonly number[];
  readonly memberIds: readonly number[];
}

const statusIn = (
  seats: readonly HouseholdSeat[],
  options: { readonly userId: number; readonly sessionId: number }
): ParticipationStatus | null =>
  seats.find(
    (seat) =>
      seat.userId === options.userId && seat.sessionId === options.sessionId
  )?.status ?? null;

const overlapsElsewhere = (
  seats: readonly HouseholdSeat[],
  options: {
    readonly userId: number;
    readonly session: SessionContext;
  }
): boolean => {
  const { agenda } = options.session;

  if (agenda === null) {
    return false;
  }

  return seats.some(
    (seat) =>
      seat.userId === options.userId &&
      seat.sessionId !== options.session.sessionId &&
      seat.startTime !== null &&
      seat.endTime !== null &&
      overlapsWith({
        item: agenda,
        other: { endTime: seat.endTime, startTime: seat.startTime },
      })
  );
};

export const loadEnrollmentContext = Effect.fn("Enrollment.loadContext")(
  function* loadEnrollmentContext(input: {
    readonly sessionId: number;
    readonly party: string | null;
  }) {
    const { now, session, viewerId } = yield* loadSession(input.sessionId);
    const store = yield* EnrollmentStore;
    const parties = yield* PartyStore;
    const users = yield* UserDirectory;

    const selection = selectParty({
      parties: yield* parties.listForViewer(UserId.make(viewerId)),
      requested: input.party,
      viewerId,
    });

    if (selection === null) {
      return yield* refuse({
        destination: "enrollPage",
        eventSlug: session.eventSlug,
        notices: [
          notice("error", "Choose one of your parties or enroll by yourself."),
        ],
      });
    }

    const companions = selection.companionsShown
      ? yield* users.companionsOf(UserId.make(viewerId))
      : [];

    const ownLed =
      selection.selected !== null && selection.selected.leader.id === viewerId;

    const members = ownLed
      ? (selection.selected?.members ?? []).filter(
          (member) =>
            member.user.id !== viewerId &&
            member.user.userType !== "connected" &&
            member.status === "active"
        )
      : [];

    const people = yield* store.readPeople([
      viewerId,
      ...companions.map((companion) => companion.id),
      ...members.map((member) => member.user.id),
    ]);

    const byId = new Map(people.map((person) => [person.id, person]));
    const viewer = byId.get(viewerId);

    if (viewer === undefined) {
      return yield* new NotFound({ entity: "User", key: String(viewerId) });
    }

    const eligible = session.windows.filter((window) =>
      session.seats.eligibleWindowIds.includes(window.pk)
    );

    const restricted = restrictsEveryone(eligible);

    const anyRestricted = eligible.some(
      (window) => window.restrictToConfiguredUsers
    );

    const viewerAllowance = anyRestricted
      ? yield* slotAllowance({
          email: viewer.email,
          eventId: session.eventId,
          now,
          windows: session.windows,
        })
      : Option.none<VirtualEnrollmentConfig>();

    const viewerIsConfigured = Option.exists(
      viewerAllowance,
      (config) => config.userSlots + config.domainSlots > 0
    );

    const actorPolicy = policyForActor({
      isConfiguredUser: viewerIsConfigured,
      windows: eligible,
    });

    const userIds = people.map((person) => person.id);

    const seats = yield* store.householdSeats({
      eventId: session.eventId,
      userIds,
    });

    const conflictedUserIds = yield* store.conflictedUserIds({
      sessionId: session.sessionId,
      userIds,
    });

    const memberAccess = new Map<number, boolean>();

    for (const member of members) {
      const person = byId.get(member.user.id);

      memberAccess.set(
        member.user.id,
        !restricted ||
          (person !== undefined &&
            person.email !== "" &&
            (yield* hasSlotAccess({
              email: person.email,
              eventId: session.eventId,
              now,
              windows: session.windows,
            })))
      );
    }

    const needsAccept = new Map<number, boolean>(
      members.map((member) => [
        member.user.id,
        member.consentMode === "accept_invites",
      ])
    );

    const facts = people.map((person): RosterFacts => ({
      hasConflict: conflictedUserIds.includes(person.id),
      hasTimeConflict: overlapsElsewhere(seats, {
        session,
        userId: person.id,
      }),
      isMember: memberAccess.has(person.id),
      isViewer: person.id === viewerId,
      memberCanEnroll: memberAccess.get(person.id) ?? true,
      needsAccept: needsAccept.get(person.id) ?? false,
      person,
      status: statusIn(seats, {
        sessionId: session.sessionId,
        userId: person.id,
      }),
      waitingSessions: seats.filter(
        (seat) =>
          seat.userId === person.id &&
          seat.status === "waiting" &&
          seat.hasAgenda
      ).length,
    }));

    const context: EnrollmentContext = {
      choices: selection.choices,
      companionIds: companions.map((companion) => companion.id),
      conflictedUserIds,
      eligible,
      memberIds: members.map((member) => member.user.id),
      now,
      people: facts,
      policy: {
        maxWaitlistSessions: policyMaxWaitlistSessions(actorPolicy),
        restrictedOut: eligible.length > 0 && !canEnroll(actorPolicy),
        userCanEnroll: canEnroll(actorPolicy),
      },
      selectedParty: selection.selected,
      session,
      slotAllowance: requiresSlotAllowance(actorPolicy)
        ? viewerAllowance
        : Option.none(),
      viewer,
      viewerIsConfigured,
    };

    return context;
  }
);

export const partyIdOf = (context: EnrollmentContext) =>
  context.selectedParty === null
    ? null
    : PartyId.make(context.selectedParty.id);
