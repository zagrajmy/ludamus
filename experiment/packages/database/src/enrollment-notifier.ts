import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import { EnrollmentNotifier } from "@zagrajmy/core/enrollment/ports";
import type {
  HeldSeatNotification,
  OfferNotification,
  PartyEnrolledNotification,
  PromotionNotification,
} from "@zagrajmy/core/enrollment/schemas";
import { DEFAULT_LOCALE, translator } from "@zagrajmy/i18n";
import { Context, DateTime, Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { asEnrollmentFailure } from "./enrollment-errors.js";
import {
  decodeFirst,
  decodeRows,
  IdRow,
  pythonJson,
  toSqlDateTime,
} from "./rows.js";
import type { PythonJson } from "./rows.js";

export interface OutgoingMail {
  readonly to: string;
  readonly subject: string;
  readonly body: string;
}

export class MailOutbox extends Context.Reference<{
  readonly send: (mail: OutgoingMail) => Effect.Effect<void>;
}>("@zagrajmy/database/MailOutbox", {
  defaultValue: () => ({
    send: (mail) =>
      Effect.logInfo("mail not sent: no outbox configured").pipe(
        Effect.annotateLogs({ subject: mail.subject })
      ),
  }),
}) {}

const encodeHeader = (value: string): string =>
  /^[ -~]*$/u.test(value)
    ? value
    : `=?utf-8?b?${Buffer.from(value, "utf-8").toString("base64")}?=`;

export const fileMailOutbox = (directory: string) =>
  Layer.succeed(MailOutbox, {
    send: (mail) =>
      Effect.gen(function* writeMailFile() {
        const now = yield* DateTime.now;

        const stamp = DateTime.formatIso(now)
          .replaceAll(/[^0-9]/gu, "")
          .slice(0, 14);

        const name = `${stamp}-${crypto.randomUUID()}.log`;

        const message = [
          'Content-Type: text/plain; charset="utf-8"',
          "MIME-Version: 1.0",
          "Content-Transfer-Encoding: 8bit",
          `Subject: ${encodeHeader(mail.subject)}`,
          "From: Zagrajmy <noreply@zagrajmy.net>",
          `To: ${mail.to}`,
          `Date: ${DateTime.toDateUtc(now).toUTCString()}`,
          "",
          mail.subject,
          "",
          mail.body,
          "",
          "-".repeat(79),
          "",
        ].join("\n");

        yield* Effect.tryPromise(async () => {
          await mkdir(directory, { recursive: true });
          await writeFile(path.join(directory, name), message, "utf-8");
        }).pipe(
          Effect.tap(() =>
            Effect.logInfo("mail written to the outbox").pipe(
              Effect.annotateLogs({ file: name, subject: mail.subject })
            )
          ),
          Effect.catch((error) =>
            Effect.logWarning("mail outbox write failed", error)
          )
        );
      }),
  });

const HostRow = Schema.Struct({
  domain: Schema.String,
  eventSlug: Schema.String,
});

const AddressRow = Schema.Struct({ email: Schema.String });

interface Notice {
  readonly recipientUserId: number;
  readonly sessionId: number;
  readonly kind: string;
  readonly title: string;
  readonly body: string;
  readonly path: string;
  readonly payload: Readonly<Record<string, PythonJson>>;
}

const { t } = translator(DEFAULT_LOCALE);

const two = (value: number) => String(value).padStart(2, "0");

const deadlineText = (value: DateTime.Utc): string => {
  const local = DateTime.toParts(
    DateTime.makeZonedUnsafe(value, { timeZone: "Europe/Warsaw" })
  );

  return `${two(local.day)}.${two(local.month)}.${local.year} ${two(local.hour)}:${two(local.minute)}`;
};

const isoPython = (value: DateTime.Utc): string =>
  DateTime.formatIso(value).replace("Z", "+00:00");

const enrollmentPath = (eventSlug: string, sessionId: number) =>
  `/event/${eventSlug}/session/${sessionId}/enrollment/`;

const truncate = (value: string, max: number) =>
  value.length <= max ? value : `${value.slice(0, max - 1)}…`;

export const makeEnrollmentNotifier = Effect.gen(
  function* makeEnrollmentNotifier() {
    const sql = yield* SqlClient;

    const deliver = Effect.fn("EnrollmentNotifier.deliver")(function* deliver(
      notice: Notice
    ) {
      const operation = "EnrollmentNotifier.deliver";
      const outbox = yield* MailOutbox;

      const host =
        yield* sql`SELECT django_site.domain AS domain, e.slug AS eventSlug
      FROM session s JOIN event e ON e.id = s.event_id JOIN sphere ON sphere.id = e.sphere_id
      JOIN django_site ON django_site.id = sphere.site_id WHERE s.id = ${notice.sessionId}`.pipe(
          decodeFirst(operation, HostRow)
        );

      const domain = Option.match(host, {
        onNone: () => "localhost:8000",
        onSome: (row) => row.domain,
      });

      const scheme = domain.includes("localhost") ? "http" : "https";
      const url = `${scheme}://${domain}${notice.path}`;
      const now = toSqlDateTime(yield* DateTime.now);

      yield* sql`INSERT INTO notification ${sql.insert({
        body: notice.body,
        creation_time: now,
        kind: notice.kind,
        payload: pythonJson(notice.payload),
        read_at: null,
        recipient_id: notice.recipientUserId,
        title: truncate(notice.title, 255),
        url,
      })} RETURNING id`.pipe(decodeRows(operation, IdRow));

      const address = yield* sql`SELECT email FROM user
      WHERE id = ${notice.recipientUserId} AND email_verified = 1 AND email <> ''`.pipe(
        decodeFirst(operation, AddressRow)
      );

      yield* Effect.logInfo("notification written").pipe(
        Effect.annotateLogs({
          kind: notice.kind,
          recipient: notice.recipientUserId,
          sessionId: notice.sessionId,
        })
      );

      if (Option.isSome(address)) {
        yield* outbox.send({
          body: `${notice.body}\n\n${url}`,
          subject: notice.title,
          to: address.value.email,
        });
      }
    });

    const notifyPromoted = (notification: PromotionNotification) =>
      deliver({
        body: t(
          "A confirmed spot opened up and you have been enrolled automatically."
        ),
        kind: "waitlist_promoted",
        path: enrollmentPath(notification.eventSlug, notification.sessionId),
        payload: { session_id: notification.sessionId },
        recipientUserId: notification.recipientUserId,
        sessionId: notification.sessionId,
        title: t("You're in: a spot opened in %(session)s", {
          session: notification.sessionTitle,
        }),
      });

    const notifyOffered = (notification: OfferNotification) => {
      const deadline = deadlineText(notification.offerExpiresAt);

      return deliver({
        body: t(
          "A spot opened up — claim it before %(deadline)s using the link below, or it will go to the next person on the waiting list.",
          { deadline }
        ),
        kind: "waitlist_offer",
        path: `/offer/${notification.claimToken}/claim/`,
        payload: {
          claim_token: notification.claimToken,
          offer_expires_at: isoPython(notification.offerExpiresAt),
          session_id: notification.sessionId,
        },
        recipientUserId: notification.recipientUserId,
        sessionId: notification.sessionId,
        title: t("A spot opened in %(session)s — claim it by %(deadline)s", {
          deadline,
          session: notification.sessionTitle,
        }),
      });
    };

    const notifyOfferExpired = (notification: PromotionNotification) =>
      deliver({
        body: t(
          "The seat was not claimed in time and has been released. You can sign up again if you are still interested."
        ),
        kind: "offer_expired",
        path: enrollmentPath(notification.eventSlug, notification.sessionId),
        payload: { session_id: notification.sessionId },
        recipientUserId: notification.recipientUserId,
        sessionId: notification.sessionId,
        title: t("Your offer for %(session)s expired", {
          session: notification.sessionTitle,
        }),
      });

    const notifySeatHeld = (notification: HeldSeatNotification) => {
      const deadline = deadlineText(notification.offerExpiresAt);

      return deliver({
        body: t(
          "The seat is yours once you claim it — do so before %(deadline)s or it will be released.",
          { deadline }
        ),
        kind: "party_seat_held",
        path: `/offer/${notification.claimToken}/claim/`,
        payload: {
          claim_token: notification.claimToken,
          offer_expires_at: isoPython(notification.offerExpiresAt),
          session_id: notification.sessionId,
        },
        recipientUserId: notification.recipientUserId,
        sessionId: notification.sessionId,
        title: t("%(leader)s saved you a seat in %(session)s", {
          leader: notification.actorName,
          session: notification.sessionTitle,
        }),
      });
    };

    const notifyPartyEnrolled = (notification: PartyEnrolledNotification) =>
      deliver({
        body: t(
          "You have a confirmed spot. If it does not fit your plans, you can cancel on the session page."
        ),
        kind: "party_enrolled",
        path: enrollmentPath(notification.eventSlug, notification.sessionId),
        payload: { session_id: notification.sessionId },
        recipientUserId: notification.recipientUserId,
        sessionId: notification.sessionId,
        title: t("%(leader)s enrolled you in %(session)s", {
          leader: notification.actorName,
          session: notification.sessionTitle,
        }),
      });

    const fail = asEnrollmentFailure;

    return EnrollmentNotifier.of({
      notifyOfferExpired: (notification) =>
        notifyOfferExpired(notification).pipe(
          fail("EnrollmentNotifier.notifyOfferExpired")
        ),
      notifyOffered: (notification) =>
        notifyOffered(notification).pipe(
          fail("EnrollmentNotifier.notifyOffered")
        ),
      notifyPartyEnrolled: (notification) =>
        notifyPartyEnrolled(notification).pipe(
          fail("EnrollmentNotifier.notifyPartyEnrolled")
        ),
      notifyPromoted: (notification) =>
        notifyPromoted(notification).pipe(
          fail("EnrollmentNotifier.notifyPromoted")
        ),
      notifySeatHeld: (notification) =>
        notifySeatHeld(notification).pipe(
          fail("EnrollmentNotifier.notifySeatHeld")
        ),
    });
  }
);

export const EnrollmentNotifierLive = Layer.effect(
  EnrollmentNotifier,
  makeEnrollmentNotifier
);
