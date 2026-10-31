import { implement } from "@zagrajmy/capability/implement";
import { Effect, Option, Predicate, Result } from "effect";

import { submitEnrollmentsContract } from "../contracts.js";
import { NotFound } from "../ports/store-error.js";
import { fullName } from "../user.js";
import { EnrollmentRefused } from "./api.js";
import type {
  EnrollmentNotice,
  SubmitEnrollmentsInput,
  SubmittedEnrollments,
} from "./api.js";
import {
  loadEnrollmentContext,
  loadSession,
  notice,
  partyIdOf,
  refuse,
} from "./context.js";
import type { EnrollmentContext } from "./context.js";
import {
  desiredStateRequests,
  explicitRequests,
  processEnrollments,
} from "./enroll.js";
import type { EnrollmentRequest, ExplicitChoice } from "./enroll.js";
import { batchNotices, overflowNotice } from "./notices.js";
import {
  EnrollmentNotifier,
  EnrollmentStore,
  EnrollmentTransaction,
  OfferExpiryScheduler,
} from "./ports.js";
import { fillFreedSeats, holdSeat } from "./promotion-service.js";
import { MAX_GUESTS } from "./read-enrollment-form-capability.js";
import {
  INCLUDE_VALUE,
  normalizedChoice,
  rejectChoice,
  rosterChoices,
} from "./roster.js";
import {
  canEnrollUsers,
  usedSlots,
  allowedSlots,
  availableAllowance,
} from "./rules.js";
import { shadowbannedSeats, viewerFooter } from "./viewer-footer.js";

const EXPLICIT_CHOICES: ReadonlySet<string> = new Set([
  "cancel",
  "enroll",
  "waitlist",
  INCLUDE_VALUE,
]);

const isExplicitChoice = (value: string): value is ExplicitChoice =>
  EXPLICIT_CHOICES.has(value);

const valueFor = (input: SubmitEnrollmentsInput, userId: number): string =>
  normalizedChoice(
    input.choices.find((choice) => choice.userId === userId)?.value ?? ""
  );

const allowanceRefusal = Effect.fn("SubmitEnrollments.allowanceRefusal")(
  function* allowanceRefusal(
    context: EnrollmentContext,
    input: SubmitEnrollmentsInput
  ) {
    if (Option.isNone(context.slotAllowance)) {
      return Option.none<EnrollmentNotice>();
    }

    const store = yield* EnrollmentStore;
    const allowance = context.slotAllowance.value;
    const capped = [context.viewer.id, ...context.companionIds];

    const newSeats = context.people
      .filter((facts) => capped.includes(facts.person.id))
      .filter((facts) => {
        const value = valueFor(input, facts.person.id);

        return (
          value === "enroll" ||
          (value === INCLUDE_VALUE && facts.status === null)
        );
      });

    if (newSeats.length === 0) {
      return Option.none<EnrollmentNotice>();
    }

    const occupying = yield* store.occupyingUserIds({
      eventId: context.session.eventId,
      userIds: capped,
    });

    const allowed = allowedSlots(allowance);

    if (
      canEnrollUsers({
        allowedSlots: allowed,
        occupyingUserIds: occupying,
        userIdsToEnroll: newSeats.map((facts) => facts.person.id),
      })
    ) {
      return Option.none<EnrollmentNotice>();
    }

    const [first] = newSeats;

    return Option.some(
      notice(
        "error",
        `${first?.person.name ?? "User"}: Cannot enroll more users. You have already enrolled ${usedSlots(occupying)} out of ${allowed} unique people (each person can enroll in multiple sessions). Only ${availableAllowance({ allowedSlots: allowed, occupyingUserIds: occupying })} slots remaining for new people.`
      )
    );
  }
);

const formErrors = Effect.fn("SubmitEnrollments.formErrors")(
  function* formErrors(
    context: EnrollmentContext,
    input: SubmitEnrollmentsInput
  ) {
    const errors: EnrollmentNotice[] = context.people.flatMap((facts) => {
      const rejection = rejectChoice({
        choices: rosterChoices(facts, context.policy),
        personName: facts.person.name,
        policy: context.policy,
        value: valueFor(input, facts.person.id),
        viewerEmail: context.viewer.email,
      });

      return rejection === null
        ? []
        : [notice("error", rejection.msgid, rejection.vars)];
    });

    if (
      input.guests !== null &&
      (input.guests < 0 || input.guests > MAX_GUESTS)
    ) {
      errors.push(
        input.guests < 0
          ? notice(
              "error",
              "Ensure this value is greater than or equal to %(limit_value)s.",
              { limit_value: "0" }
            )
          : notice(
              "error",
              "Ensure this value is less than or equal to %(limit_value)s.",
              { limit_value: String(MAX_GUESTS) }
            )
      );
    }

    if (errors.length > 0) {
      return errors;
    }

    return Option.toArray(yield* allowanceRefusal(context, input));
  }
);

const invalidFormNotices = (
  context: EnrollmentContext,
  errors: readonly EnrollmentNotice[]
): readonly EnrollmentNotice[] => {
  const restricted =
    context.eligible.length > 0 &&
    context.eligible.every((window) => window.restrictToConfiguredUsers);

  if (!restricted) {
    return [
      ...errors,
      notice("warning", "Please review the enrollment options below."),
    ];
  }

  if (context.viewer.email === "") {
    return [
      ...errors,
      notice(
        "error",
        "Email address is required for enrollment in this session."
      ),
    ];
  }

  return context.viewerIsConfigured
    ? [
        ...errors,
        notice("warning", "Please review the enrollment options below."),
      ]
    : [
        ...errors,
        notice(
          "error",
          "Enrollment access permission is required for this session. Please contact the organizers to obtain access."
        ),
      ];
};

const requestsFor = (
  context: EnrollmentContext,
  input: SubmitEnrollmentsInput
): readonly EnrollmentRequest[] => {
  if (input.mode === "desired") {
    return desiredStateRequests({
      conflictedUserIds: context.conflictedUserIds,
      household: context.people.map((facts) => ({
        choices: rosterChoices(facts, context.policy),
        desiredIn: valueFor(input, facts.person.id) === INCLUDE_VALUE,
        isActive: facts.person.isActive,
        isMember: facts.isMember,
        name: facts.person.name,
        needsAccept: facts.needsAccept,
        status: facts.status,
        userId: facts.person.id,
      })),
      seating: {
        eligibleWindows: context.eligible,
        enrolledCount: context.session.seats.enrolledCount,
        participantsLimit: context.session.participantsLimit,
        viewerIsConfigured: context.viewerIsConfigured,
      },
    });
  }

  return explicitRequests(
    context.people.map((facts) => {
      const value = valueFor(input, facts.person.id);

      return {
        choice: isExplicitChoice(value) ? value : null,
        isActive: facts.person.isActive,
        isMember: facts.isMember,
        name: facts.person.name,
        needsAccept: facts.needsAccept,
        userId: facts.person.id,
      };
    })
  );
};

const commit = Effect.fn("SubmitEnrollments.commit")(function* commit(options: {
  readonly context: EnrollmentContext;
  readonly input: SubmitEnrollmentsInput;
  readonly requests: readonly EnrollmentRequest[];
  readonly guestsTarget: number | null;
}) {
  const { context } = options;
  const { session, viewer } = context;
  const transaction = yield* EnrollmentTransaction;
  const store = yield* EnrollmentStore;
  const partyId = partyIdOf(context);

  return yield* transaction.atomic(
    Effect.gen(function* underSessionLock() {
      const exists = yield* store.lockSessionRow(session.sessionId);

      if (!exists) {
        return yield* new NotFound({
          entity: "Session",
          key: String(session.sessionId),
        });
      }

      yield* store.lockSeatHolders([
        viewer.id,
        ...options.requests.map((request) => request.userId),
      ]);

      const overspent = yield* allowanceRefusal(context, options.input);

      if (Option.isSome(overspent)) {
        return yield* refuse({
          destination: "enrollPage",
          eventSlug: session.eventSlug,
          notices: [overspent.value],
        });
      }

      const locked = yield* store.readSeatState({
        householdUserIds: context.people.map((facts) => facts.person.id),
        now: context.now,
        sessionId: session.sessionId,
        viewerId: viewer.id,
      });

      if (Option.isNone(locked)) {
        return yield* new NotFound({
          entity: "Session",
          key: String(session.sessionId),
        });
      }

      const decided = processEnrollments({
        guestsTarget: options.guestsTarget,
        partyId,
        requests: options.requests,
        session: {
          ...locked.value,
          viewerIsConfigured: context.viewerIsConfigured,
        },
      });

      if (Result.isFailure(decided)) {
        return yield* refuse({
          destination: "enrollPage",
          eventSlug: session.eventSlug,
          notices: [overflowNotice(decided.failure)],
        });
      }

      const batch = decided.success;

      yield* store.apply({
        guestName: `${fullName(viewer)} +1`,
        sessionId: session.sessionId,
        viewerId: viewer.id,
        writes: batch.writes.filter(
          (write) => !Predicate.isTagged(write, "HoldSeat")
        ),
      });

      const expiries = yield* Effect.all(
        batch.heldSeats.map((held) =>
          holdSeat({
            actorName: fullName(viewer),
            partyId,
            sessionId: session.sessionId,
            sessionTitle: locked.value.title,
            userId: held.userId,
          })
        )
      );

      return { batch, expiries };
    })
  );
});

const submit = Effect.fn("SubmitEnrollments.submit")(function* submit(
  input: SubmitEnrollmentsInput
) {
  const context = yield* loadEnrollmentContext(input);
  const { session, viewer } = context;
  const errors = yield* formErrors(context, input);

  if (errors.length > 0) {
    return yield* refuse({
      destination: "stay",
      eventSlug: session.eventSlug,
      notices: invalidFormNotices(context, errors),
    });
  }

  const requests = requestsFor(context, input);

  if (
    !(
      requests.length > 0 &&
      requests.every((request) => request.choice === "cancel")
    ) &&
    context.eligible.length === 0
  ) {
    return yield* refuse({
      destination: "event",
      eventSlug: session.eventSlug,
      notices: [
        notice(
          "error",
          "No enrollment configuration is available for this session."
        ),
      ],
    });
  }

  const guestsAllowed = context.eligible.some(
    (window) => window.allowAnonymousEnrollment
  );

  const guestsTarget = guestsAllowed ? input.guests : null;

  const guestsChanged =
    guestsTarget !== null && guestsTarget !== session.viewerGuestCount;

  if (requests.length === 0 && !guestsChanged) {
    return yield* refuse({
      destination: "enrollPage",
      eventSlug: session.eventSlug,
      notices: [
        notice(
          "warning",
          guestsTarget !== null || input.mode === "desired"
            ? "No changes."
            : "Please select at least one user to enroll."
        ),
      ],
    });
  }

  const { batch, expiries } = yield* commit({
    context,
    guestsTarget,
    input,
    requests,
  });

  const scheduler = yield* OfferExpiryScheduler;
  const notifier = yield* EnrollmentNotifier;

  yield* Effect.all(
    expiries.map((item) => scheduler.scheduleExpiry(item)),
    { discard: true }
  );

  if (batch.freedSeat) {
    yield* fillFreedSeats(session.sessionId);
  }

  yield* Effect.all(
    batch.enrolledMemberUserIds.map((recipientUserId) =>
      notifier.notifyPartyEnrolled({
        actorName: fullName(viewer),
        eventSlug: session.eventSlug,
        recipientUserId,
        sessionId: session.sessionId,
        sessionTitle: session.title,
      })
    ),
    { discard: true }
  );

  if (batch.signedUpUsers.length > 0 && session.presenterId !== null) {
    yield* Effect.logInfo(
      "signups recorded; the presenter's shadowban mail is not ported"
    ).pipe(
      Effect.annotateLogs({
        sessionId: session.sessionId,
        signups: batch.signedUpUsers.length,
      })
    );
  }

  yield* Effect.logInfo("enrollments submitted").pipe(
    Effect.annotateLogs({
      cancelled: batch.cancelledUsers.length,
      confirmed: batch.confirmedUsers.length,
      freedSeat: batch.freedSeat,
      held: batch.heldSeats.length,
      mode: input.mode,
      sessionId: session.sessionId,
      skipped: batch.skippedUsers.length,
      waiting: batch.waitingUsers.length,
    })
  );

  return batchNotices(batch);
});

const freshFooter = Effect.fn("SubmitEnrollments.freshFooter")(
  function* freshFooter(sessionId: number) {
    const store = yield* EnrollmentStore;
    const { session, viewerId } = yield* loadSession(sessionId);
    const [viewer] = yield* store.readPeople([viewerId]);

    return {
      eventSlug: session.eventSlug,
      footer: yield* viewerFooter({
        session,
        viewerEmail: viewer?.email ?? "",
        viewerId,
      }),
      seats: session.viewerShadowbanned
        ? shadowbannedSeats(session.seats)
        : session.seats,
    };
  }
);

export const submitEnrollments = implement(submitEnrollmentsContract, (input) =>
  submit(input).pipe(
    Effect.flatMap((notices) =>
      freshFooter(input.sessionId).pipe(
        Effect.map(({ eventSlug, footer, seats }): SubmittedEnrollments => ({
          eventSlug,
          footer,
          notices,
          seats,
          sessionId: input.sessionId,
        }))
      )
    ),
    Effect.catchTag("EnrollmentRefused", (refused) =>
      input.mode === "explicit"
        ? freshFooter(input.sessionId).pipe(
            Effect.flatMap(({ footer }) =>
              Effect.fail(
                new EnrollmentRefused({
                  destination: refused.destination,
                  eventSlug: refused.eventSlug,
                  footer,
                  notices: refused.notices,
                })
              )
            ),
            Effect.catchTag("EnrollmentRefused", () => Effect.fail(refused))
          )
        : Effect.fail(refused)
    )
  )
);
