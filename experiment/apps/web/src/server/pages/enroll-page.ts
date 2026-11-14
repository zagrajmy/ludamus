import type {
  EnrollmentForm,
  EnrollmentNotice,
  RefusalDestination,
} from "@zagrajmy/core/contracts";
import { readEnrollmentForm } from "@zagrajmy/core/enrollment/read-enrollment-form-capability";
import { formatDate } from "@zagrajmy/i18n";
import type { Locale } from "@zagrajmy/i18n";
import { DateTime, Effect, Match, Option } from "effect";

import type { EnrollPageFlags } from "../../client/enroll-page/flags.js";
import { noticeText } from "../../client/enroll-page/notices.js";
import type { FlashNote } from "../flash.js";
import { renderSafeMarkdown } from "../markdown.js";
import { mediaUrl, placeholderCoverUrl } from "../request-context.js";
import type { RequestContext } from "../request-context.js";
import { PageOutcome } from "./page-outcome.js";
import { providePanelServices } from "./panel/context.js";

export const ENROLL_PAGE_PATH =
  /^\/event\/(?<eventSlug>[^/]+)\/session\/(?<sessionId>\d+)\/enrollment\/$/u;

const format = (at: DateTime.Utc, locale: Locale, pattern: string) =>
  formatDate({ format: pattern, locale, value: DateTime.formatIso(at) });

const faceOf = (person: {
  readonly avatarUrl: string;
  readonly name: string;
  readonly useGravatar: boolean;
}) => ({
  avatarUrl:
    person.avatarUrl === "" || person.useGravatar
      ? Option.none<string>()
      : Option.some(person.avatarUrl),
  name: person.name,
});

const flashes = (
  notices: readonly EnrollmentNotice[],
  context: RequestContext
): readonly FlashNote[] =>
  notices.map((notice) => ({
    level: notice.level,
    text: noticeText(notice, context.translator),
  }));

const partyParamOf = (form: EnrollmentForm, party: string | null) => {
  if (form.selectedPartyId !== null) {
    return String(form.selectedPartyId);
  }

  return form.partyChoices.length > 0 ? "none" : party;
};

const refusedLocation = (options: {
  readonly destination: RefusalDestination;
  readonly eventSlug: string;
  readonly pathname: string;
}) =>
  Match.value(options.destination).pipe(
    Match.when("event", () => `/event/${options.eventSlug}/`),
    Match.when("index", () => "/"),
    Match.orElse(() => options.pathname)
  );

const flagsOf = (
  form: EnrollmentForm,
  context: RequestContext,
  party: string | null
): EnrollPageFlags => {
  const { locale } = context.translator;

  const stored = [form.sessionCoverImage, form.eventCoverImage].find(
    (path) => path !== ""
  );

  const cover = Option.some(
    stored === undefined
      ? placeholderCoverUrl(form.sessionId)
      : mediaUrl(stored)
  );

  return {
    avatars: form.rows.map((row) => ({
      avatar: faceOf(row.person),
      userId: row.userId,
    })),
    coverUrl: cover,
    descriptionHtml: renderSafeMarkdown(form.description),
    eventUrl: `/event/${form.eventSlug}/`,
    form,
    locale,
    partiesUrl: "/crowd/profile/parties/",
    partyParam: partyParamOf(form, party),
    presenterAvatar:
      form.presenter === null
        ? Option.none()
        : Option.some(faceOf(form.presenter)),
    shadowbanDates: form.shadowbanWarnings.map((warning) =>
      format(warning.shadowbannedAt, locale, "d.m.Y")
    ),
    whenLabel:
      form.agenda === null
        ? ""
        : `${format(form.agenda.startTime, locale, "l, j E")} · ${format(form.agenda.startTime, locale, "G:i")}–${format(form.agenda.endTime, locale, "G:i")}`,
  };
};

type EnrollPageOutcome = PageOutcome<EnrollPageFlags>;

const redirect = (
  location: string,
  notes: readonly FlashNote[] = []
): EnrollPageOutcome => PageOutcome.Redirect({ flashes: notes, location });

export const loadEnrollPage = Effect.fn("EnrollPage.load")(
  function* loadEnrollPage(
    context: RequestContext,
    path: { readonly eventSlug: string; readonly sessionId: number }
  ) {
    const here = `${context.url.pathname}${context.url.search}`;
    const login = `/crowd/auth0/do/login?next=${encodeURIComponent(here)}`;

    if (Option.isNone(context.viewer)) {
      return redirect(login);
    }

    const party = context.url.searchParams.get("party");

    const notFound = redirect("/", [
      { level: "error", text: context.translator.t("Session not found.") },
    ]);

    return yield* readEnrollmentForm
      .handler({ party, sessionId: path.sessionId })
      .pipe(
        providePanelServices(context),
        Effect.map((form): EnrollPageOutcome =>
          form.eventSlug === path.eventSlug
            ? PageOutcome.Page({ flags: flagsOf(form, context, party) })
            : notFound
        ),
        Effect.catchTag("NotFound", () => Effect.succeed(notFound)),
        Effect.catchTag("EnrollmentRefused", (refused) =>
          Effect.succeed(
            redirect(
              refusedLocation({
                destination: refused.destination,
                eventSlug: refused.eventSlug ?? path.eventSlug,
                pathname: context.url.pathname,
              }),
              flashes(refused.notices, context)
            )
          )
        ),
        Effect.catchTag("LoginRequired", () => Effect.succeed(redirect(login)))
      );
  }
);
