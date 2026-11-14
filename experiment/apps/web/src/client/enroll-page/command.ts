import { SubmitEnrollmentsInput } from "@zagrajmy/core/contracts";
import type {
  EnrollmentNotice,
  RefusalDestination,
} from "@zagrajmy/core/contracts";
import { Effect, Match, Schema } from "effect";
import { Command } from "foldkit";

import { Locale, translator } from "../../ui/i18n.js";
import { navigateWithFlash } from "../panel/navigate.js";
import { Backend } from "../rpc.js";
import { EnrollPageMessage } from "./message.js";
import { noticeText } from "./notices.js";

const flashOf = (notices: readonly EnrollmentNotice[], locale: Locale) =>
  notices.map((notice) => ({
    level: notice.level,
    text: noticeText(notice, translator(locale)),
  }));

const here = () => `${window.location.pathname}${window.location.search}`;

export const destinationHref = (options: {
  readonly destination: RefusalDestination;
  readonly eventSlug: string;
}): string =>
  Match.value(options.destination).pipe(
    Match.when("event", () => `/event/${options.eventSlug}/`),
    Match.when("index", () => "/"),
    Match.orElse(here)
  );

export const LOGIN_PATH = "/crowd/auth0/do/login";

export const SubmitEnrollPage = Command.define("SubmitEnrollPage", {
  args: {
    eventSlug: Schema.String,
    input: SubmitEnrollmentsInput,
    locale: Locale,
  },
  execute: ({ eventSlug, input, locale }) =>
    Effect.gen(function* submitEnrollPage() {
      const backend = yield* Backend;

      yield* backend.submitEnrollments(input).pipe(
        Effect.flatMap((done) =>
          navigateWithFlash(
            `/event/${done.eventSlug}/`,
            flashOf(done.notices, locale)
          )
        ),
        Effect.catchTag("EnrollmentRefused", (refused) => {
          const target = destinationHref({
            destination: refused.destination,
            eventSlug: refused.eventSlug ?? eventSlug,
          });

          return navigateWithFlash(target, flashOf(refused.notices, locale));
        }),
        Effect.catchTag(["LoginRequired", "SignInRequired"], () =>
          navigateWithFlash(
            `${LOGIN_PATH}?next=${encodeURIComponent(here())}`,
            []
          )
        ),
        Effect.catch(() =>
          navigateWithFlash(here(), [
            {
              level: "error",
              text: translator(locale).t("Session not found."),
            },
          ])
        )
      );

      return EnrollPageMessage.LeftEnrollPage();
    }).pipe(Effect.provide(Backend.layer)),
  messages: [EnrollPageMessage.LeftEnrollPage],
});
