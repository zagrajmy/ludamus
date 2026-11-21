import { expect, layer } from "@effect/vitest";
import { CurrentSphere, CurrentViewer, SphereId, UserId } from "@zagrajmy/core";
import { claimOffer } from "@zagrajmy/core/enrollment/claim-offer-capability";
import { expireOffers } from "@zagrajmy/core/enrollment/expire-offers-capability";
import { readEnrollFooter } from "@zagrajmy/core/enrollment/read-enroll-footer-capability";
import { readEnrollmentForm } from "@zagrajmy/core/enrollment/read-enrollment-form-capability";
import { submitEnrollments } from "@zagrajmy/core/enrollment/submit-enrollments-capability";
import { DateTime, Duration, Effect, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import { TestClock } from "effect/testing";

import { DatabaseTest } from "../src/database-test.js";
import { MailOutbox } from "../src/enrollment-notifier.js";
import type { OutgoingMail } from "../src/enrollment-notifier.js";
import { toSqlDateTime } from "../src/rows.js";
import { countRows, seedNow } from "./seed.js";

const TESTER = 1;

const SUPERUSER = 6;

const WAITER = 7;

const SEAT_AVAILABLE = 11;

const WAITING_LIST_ONLY = 12;

const WAITLIST_PROMOTION = 1;

const LATE_RESIGNATION_1 = 3;

const LATE_RESIGNATION_2 = 5;

const asViewer =
  (userId: number, sphereId = 1) =>
  <A, E, R>(effect: Effect.Effect<A, E, R>) =>
    effect.pipe(
      Effect.provideService(
        CurrentViewer,
        Option.some({ id: UserId.make(userId), isSuperuser: false })
      ),
      Effect.provideService(CurrentSphere, {
        domain: "localhost:8000",
        id: SphereId.make(sphereId),
        name: "Root",
      })
    );

const atSeedTime = Effect.gen(function* atSeedTime() {
  yield* TestClock.setTime(DateTime.toEpochMillis(yield* seedNow));
});

const StatusRow = Schema.Struct({ status: Schema.String, userId: Schema.Int });

const statuses = (sessionId: number) =>
  Effect.gen(function* readStatuses() {
    const sql = yield* SqlClient;

    return yield* sql`SELECT user_id AS userId, status FROM session_participant
      WHERE session_id = ${sessionId} ORDER BY user_id`.pipe(
      Effect.flatMap(Schema.decodeUnknownEffect(Schema.Array(StatusRow)))
    );
  });

const NotificationRow = Schema.Struct({
  kind: Schema.String,
  title: Schema.String,
  url: Schema.String,
});

const notificationsOf = (userId: number) =>
  Effect.gen(function* readNotifications() {
    const sql = yield* SqlClient;

    return yield* sql`SELECT kind, title, url FROM notification WHERE recipient_id = ${userId}
      ORDER BY id DESC LIMIT 5`.pipe(
      Effect.flatMap(Schema.decodeUnknownEffect(Schema.Array(NotificationRow)))
    );
  });

const explicit = (sessionId: number, userId: number, value: string) =>
  submitEnrollments.handler({
    choices: [{ userId, value }],
    guests: null,
    mode: "explicit",
    party: null,
    sessionId,
  });

layer(DatabaseTest, { buildPerTest: true })("enrollment capabilities", (it) => {
  it.effect(
    "a session with room offers the viewer a seat: Seat Available Demo has 5 seats left",
    () =>
      Effect.gen(function* roomLeft() {
        yield* atSeedTime;

        const form = yield* readEnrollmentForm.handler({
          party: null,
          sessionId: SEAT_AVAILABLE,
        });

        const [footer] = yield* readEnrollFooter.handler({
          sessionIds: [SEAT_AVAILABLE],
        });

        expect(form.seats.seatsLeft).toBe(5);
        expect(form.rows[0]).toMatchObject({
          boxChecked: true,
          checked: false,
          disabled: false,
          isViewer: true,
        });
        expect(form.ctaLabel).toBe("Join this session");
        expect(footer?.footer.actions).toMatchObject({
          badge: null,
          submitLabel: "Enroll",
          submitValue: "enroll",
        });
      }).pipe(asViewer(TESTER))
  );

  it.effect(
    "taking the seat writes one confirmed row and flips the footer to Cancel",
    () =>
      Effect.gen(function* takeSeat() {
        yield* atSeedTime;

        const done = yield* explicit(SEAT_AVAILABLE, TESTER, "enroll");

        expect(yield* statuses(SEAT_AVAILABLE)).toEqual([
          { status: "confirmed", userId: TESTER },
        ]);
        expect(done.footer.actions).toMatchObject({
          badge: { label: "You're enrolled" },
          submitLabel: "Cancel",
          submitValue: "cancel",
        });
        expect(done.notices).toEqual([
          {
            args: [],
            items: [{ msgid: "%(name)s", name: "E2E Tester" }],
            level: "success",
            msgid: "Enrolled: {}",
            vars: {},
          },
        ]);
      }).pipe(asViewer(TESTER))
  );

  it.effect(
    "a full session offers the waiting list and refuses a seat without writing",
    () =>
      Effect.gen(function* fullSession() {
        yield* atSeedTime;

        const [footer] = yield* readEnrollFooter.handler({
          sessionIds: [WAITING_LIST_ONLY],
        });

        expect(footer?.footer.actions?.submitValue).toBe("waitlist");

        const before = yield* statuses(WAITING_LIST_ONLY);

        const refused = yield* explicit(
          WAITING_LIST_ONLY,
          TESTER,
          "enroll"
        ).pipe(Effect.flip);

        expect(refused._tag).toBe("EnrollmentRefused");
        expect(yield* statuses(WAITING_LIST_ONLY)).toEqual(before);

        const joined = yield* explicit(WAITING_LIST_ONLY, TESTER, "waitlist");

        expect(joined.footer.actions?.badge?.label).toBe("On the waiting list");
        expect(yield* statuses(WAITING_LIST_ONLY)).toContainEqual({
          status: "waiting",
          userId: TESTER,
        });
      }).pipe(asViewer(TESTER))
  );

  it.effect(
    "a session id from another sphere is NotFound and writes nothing",
    () =>
      Effect.gen(function* foreignSession() {
        yield* atSeedTime;
        const before = yield* countRows("session_participant");

        const read = yield* readEnrollmentForm
          .handler({ party: null, sessionId: SEAT_AVAILABLE })
          .pipe(Effect.flip);

        const written = yield* explicit(SEAT_AVAILABLE, TESTER, "enroll").pipe(
          Effect.flip
        );

        expect(read._tag).toBe("NotFound");
        expect(written._tag).toBe("NotFound");
        expect(yield* countRows("session_participant")).toBe(before);
      }).pipe(asViewer(TESTER, 4))
  );

  it.effect(
    "a cancel frees the seat and promotes the first waiter in AUTO mode, who is notified and mailed",
    () => {
      const mails: OutgoingMail[] = [];

      return Effect.gen(function* cancelPromotes() {
        yield* atSeedTime;

        const done = yield* submitEnrollments.handler({
          choices: [],
          guests: null,
          mode: "desired",
          party: null,
          sessionId: WAITLIST_PROMOTION,
        });

        expect(done.notices.map((notice) => notice.msgid)).toEqual([
          "Cancelled: {}",
        ]);
        expect(yield* statuses(WAITLIST_PROMOTION)).toEqual([
          { status: "confirmed", userId: WAITER },
        ]);

        const [promoted] = yield* notificationsOf(WAITER);
        expect(promoted?.kind).toBe("waitlist_promoted");
        expect(promoted?.title).toContain("Waitlist Promotion Demo");
        expect(promoted?.url).toBe(
          `http://localhost:8000/event/waitlist-demo/session/${WAITLIST_PROMOTION}/enrollment/`
        );
        expect(mails.map((mail) => mail.to)).toEqual(["e2e-waiter@test.local"]);
      }).pipe(
        asViewer(SUPERUSER),
        Effect.provideService(MailOutbox, {
          send: (mail) =>
            Effect.sync(() => {
              mails.push(mail);
            }),
        })
      );
    }
  );

  it.effect(
    "the sweep releases a lapsed offer once and is a no-op the second time",
    () =>
      Effect.gen(function* sweep() {
        yield* atSeedTime;
        const sql = yield* SqlClient;
        const now = yield* DateTime.now;
        const lapsed = toSqlDateTime(DateTime.subtract(now, { minutes: 5 }));

        yield* sql`INSERT INTO session_participant ${sql.insert({
          claim_token: "lapsed-token",
          claimed_at: null,
          creation_time: lapsed,
          enrolled_by_id: null,
          modification_time: lapsed,
          offer_expires_at: lapsed,
          offered_at: lapsed,
          party_id: null,
          session_id: SEAT_AVAILABLE,
          status: "offered",
          user_id: TESTER,
        })}`;

        const first = yield* expireOffers.handler({});
        const second = yield* expireOffers.handler({});

        expect(first.expired).toBe(1);
        expect(second).toEqual({ expired: 0, promoted: 0 });
        expect(yield* statuses(SEAT_AVAILABLE)).toEqual([]);
        expect((yield* notificationsOf(TESTER))[0]?.kind).toBe("offer_expired");
      }).pipe(asViewer(TESTER))
  );

  it.effect(
    "a claim over an overlapping seat fails with conflict and drops the offer (plan 021)",
    () =>
      Effect.gen(function* claimConflict() {
        yield* atSeedTime;
        const sql = yield* SqlClient;
        const now = yield* DateTime.now;
        const stamp = toSqlDateTime(now);

        yield* sql`INSERT INTO session_participant ${sql.insert({
          claim_token: "",
          claimed_at: null,
          creation_time: stamp,
          enrolled_by_id: null,
          modification_time: stamp,
          offer_expires_at: null,
          offered_at: null,
          party_id: null,
          session_id: LATE_RESIGNATION_1,
          status: "confirmed",
          user_id: WAITER,
        })}`;

        yield* sql`INSERT INTO session_participant ${sql.insert({
          claim_token: "held-token",
          claimed_at: null,
          creation_time: stamp,
          enrolled_by_id: null,
          modification_time: stamp,
          offer_expires_at: toSqlDateTime(
            DateTime.addDuration(now, Duration.hours(2))
          ),
          offered_at: stamp,
          party_id: null,
          session_id: LATE_RESIGNATION_2,
          status: "offered",
          user_id: WAITER,
        })}`;

        const claimed = yield* claimOffer.handler({ token: "held-token" });

        expect(claimed.outcome).toBe("conflict");
        expect(yield* statuses(LATE_RESIGNATION_2)).not.toContainEqual(
          expect.objectContaining({ userId: WAITER })
        );
      }).pipe(asViewer(TESTER))
  );
});
