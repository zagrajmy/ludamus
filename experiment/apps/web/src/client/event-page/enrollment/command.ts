import { Effect, Schema } from "effect";
import { Command } from "foldkit";
import { load } from "foldkit/navigation";

import { Locale, translator } from "../../../ui/i18n.js";
import { noticesText } from "../../enroll-page/notices.js";
import { Backend } from "../../rpc.js";
import { EnrollmentSlotMessage } from "../enrollment-slot.js";

const seatsOf = (seats: {
  readonly enrolledCount: number;
  readonly isFull: boolean;
  readonly seatsLeft: number;
  readonly waitingCount: number;
}) => ({
  enrolledCount: seats.enrolledCount,
  isFull: seats.isFull,
  seatsLeft: seats.seatsLeft,
  waitingCount: seats.waitingCount,
});

export const ReadEnrollFooter = Command.define("ReadEnrollFooter", {
  args: { sessionId: Schema.Int },
  execute: ({ sessionId }) =>
    Effect.gen(function* readEnrollFooter() {
      const backend = yield* Backend;

      const [found] = yield* backend.readEnrollFooter({
        sessionIds: [sessionId],
      });

      return found === undefined
        ? EnrollmentSlotMessage.FailedReadEnrollFooter({ sessionId })
        : EnrollmentSlotMessage.GotEnrollFooter({
            eventSlug: found.eventSlug,
            footer: found.footer,
            seats: seatsOf(found.seats),
            sessionId,
            viewerId: found.viewerId,
          });
    }).pipe(
      Effect.orElseSucceed(() =>
        EnrollmentSlotMessage.FailedReadEnrollFooter({ sessionId })
      ),
      Effect.provide(Backend.layer)
    ),
  messages: [
    EnrollmentSlotMessage.GotEnrollFooter,
    EnrollmentSlotMessage.FailedReadEnrollFooter,
  ],
});

export const SubmitFooterChoice = Command.define("SubmitFooterChoice", {
  args: {
    confirm: Schema.String,
    locale: Locale,
    sessionId: Schema.Int,
    value: Schema.String,
    viewerId: Schema.Int,
  },
  execute: ({ confirm, locale, sessionId, value, viewerId }) =>
    Effect.gen(function* submitFooterChoice() {
      const { t } = translator(locale);

      const proceed =
        confirm === "" ||
        // oxlint-disable-next-line eslint/no-alert -- Django's hx-confirm and data-confirm use the native dialog, and the specs answer it through page.once("dialog").
        window.confirm(t(confirm));

      if (!proceed) {
        return EnrollmentSlotMessage.KeptSeat({ sessionId });
      }

      const backend = yield* Backend;

      return yield* backend
        .submitEnrollments({
          choices: [{ userId: viewerId, value }],
          guests: null,
          mode: "explicit",
          party: null,
          sessionId,
        })
        .pipe(
          Effect.map((done) =>
            EnrollmentSlotMessage.SucceededSubmitEnrollments({
              footer: done.footer,
              notice: noticesText(done.notices, translator(locale)),
              seats: seatsOf(done.seats),
              sessionId,
            })
          ),
          Effect.catchTag("EnrollmentRefused", (refused) =>
            Effect.succeed(
              EnrollmentSlotMessage.FailedSubmitEnrollments({
                error: noticesText(refused.notices, translator(locale)),
                footer: refused.footer,
                sessionId,
              })
            )
          )
        );
    }).pipe(
      Effect.orElseSucceed(() =>
        EnrollmentSlotMessage.FailedSubmitEnrollments({
          error: translator(locale).t("Session not found."),
          footer: null,
          sessionId,
        })
      ),
      Effect.provide(Backend.layer)
    ),
  messages: [
    EnrollmentSlotMessage.KeptSeat,
    EnrollmentSlotMessage.SucceededSubmitEnrollments,
    EnrollmentSlotMessage.FailedSubmitEnrollments,
  ],
});

export const LOGIN_PATH = "/crowd/auth0/do/login";

export const ToggleBookmark = Command.define("ToggleBookmark", {
  args: {
    bookmarked: Schema.Boolean,
    count: Schema.Int,
    sessionId: Schema.Int,
  },
  execute: ({ bookmarked, count, sessionId }) =>
    Effect.gen(function* toggleBookmark() {
      const backend = yield* Backend;

      const reverted = EnrollmentSlotMessage.FailedToggleBookmark({
        bookmarked,
        count,
        sessionId,
      });

      return yield* backend.toggleBookmark({ sessionId }).pipe(
        Effect.map((state) =>
          EnrollmentSlotMessage.SucceededToggleBookmark({
            bookmarked: state.bookmarked,
            count: state.count,
            sessionId,
          })
        ),
        Effect.catchTag(["SignInRequired", "LoginRequired"], () =>
          load(
            `${LOGIN_PATH}?next=${encodeURIComponent(`${window.location.pathname}${window.location.search}`)}`
          ).pipe(Effect.as(reverted))
        ),
        Effect.orElseSucceed(() => reverted)
      );
    }).pipe(Effect.provide(Backend.layer)),
  messages: [
    EnrollmentSlotMessage.SucceededToggleBookmark,
    EnrollmentSlotMessage.FailedToggleBookmark,
  ],
});
