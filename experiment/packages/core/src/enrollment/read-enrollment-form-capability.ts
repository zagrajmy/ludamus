import { implement } from "@zagrajmy/capability/implement";
import { Effect } from "effect";

import { readEnrollmentFormContract } from "../contracts.js";
import { SessionId, UserId } from "../ids.js";
import { SafetyStore } from "../ports/safety-store.js";
import { fullName } from "../user.js";
import type { EnrollmentForm } from "./api.js";
import { loadEnrollmentContext } from "./context.js";
import { rosterChoices, rosterRow } from "./roster.js";
import { shadowbannedSeats } from "./viewer-footer.js";

export const MAX_GUESTS = 10;

export const readEnrollmentForm = implement(
  readEnrollmentFormContract,
  (input) =>
    Effect.gen(function* readEnrollmentFormHandler() {
      const context = yield* loadEnrollmentContext(input);
      const safety = yield* SafetyStore;
      const { session } = context;

      const warnings = yield* safety.sessionShadowbanWarnings({
        sessionId: SessionId.make(session.sessionId),
        viewerId: UserId.make(context.viewer.id),
      });

      const rows = context.people.map((facts) =>
        rosterRow(facts, rosterChoices(facts, context.policy))
      );

      const seats = session.viewerShadowbanned
        ? shadowbannedSeats(session.seats)
        : session.seats;

      const [viewerRow] = rows;

      const joins =
        viewerRow !== undefined &&
        viewerRow.boxChecked &&
        !viewerRow.checked &&
        !viewerRow.disabled;

      const joinLabel =
        seats.seatsLeft > 0 ? "Join this session" : "Join the waiting list";

      const ctaLabel = joins ? joinLabel : "Confirm";

      const guestsAllowed = context.eligible.some(
        (window) => window.allowAnonymousEnrollment
      );

      const form: EnrollmentForm = {
        agenda: session.agenda,
        ctaLabel,
        description: session.description,
        eventCoverImage: session.eventCoverImage,
        eventName: session.eventName,
        eventSlug: session.eventSlug,
        facilitatorName: session.facilitatorName,
        guests: guestsAllowed
          ? { count: session.viewerGuestCount, max: MAX_GUESTS }
          : null,
        minAge: session.minAge,
        partyChoices: context.choices,
        presenter: session.presenter,
        rows,
        seats,
        selectedPartyId:
          context.selectedParty === null ? null : context.selectedParty.id,
        sessionCoverImage: session.sessionCoverImage,
        sessionId: session.sessionId,
        shadowbanWarnings: warnings.map((warning) => ({
          person: {
            avatarUrl: warning.user.avatarUrl,
            email: warning.user.email,
            name: fullName(warning.user),
            useGravatar: warning.user.useGravatar,
          },
          shadowbannedAt: warning.shadowbannedAt,
        })),
        title: session.title,
      };

      return form;
    })
);
