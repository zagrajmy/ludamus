import { CurrentSphere, EventStore, PanelStore } from "@zagrajmy/core";
import type { PanelMode } from "@zagrajmy/core/panel/access";
import { currentPanelAccess, refusalFor } from "@zagrajmy/core/panel/access";
import { loadPanelEventChrome } from "@zagrajmy/core/panel/context";
import { Effect, Option } from "effect";

import { PageFlags } from "../../../client/model.js";
import type { PanelNav } from "../../../client/panel/chrome.js";
import { PanelPageFlags } from "../../../client/panel/flags.js";
import type { PanelPageFlags as PageFlagsType } from "../../../client/panel/flags.js";
import type { RequestContext } from "../../request-context.js";
import { Routed } from "../../routed.js";
import { loadCfp } from "./cfp.js";
import { eventChrome, providePanelServices } from "./context.js";
import {
  loadFacilitatorBin,
  loadFacilitatorForm,
  loadFacilitatorPage,
  loadFacilitators,
} from "./facilitators.js";
import {
  TrackOutsideEvent,
  loadProposalDetail,
  loadProposalForm,
  loadProposals,
} from "./proposals.js";
import { loadTimetable } from "./timetable.js";
import { loadTrackForm, loadTracks } from "./tracks.js";

export const isPanelPath = (pathname: string) =>
  pathname === "/panel/" || pathname.startsWith("/panel/");

const LOGIN_URL = "/crowd/login-required/";

const page = (flags: PageFlags, status = 200) => Routed.Page({ flags, status });

const redirect = (location: string, error?: string) =>
  error === undefined
    ? Routed.Redirect({ location, status: 302 })
    : Routed.Redirect({
        flashes: [{ level: "error", text: error }],
        location,
        status: 302,
      });

const notFound = (context: RequestContext) =>
  page(PageFlags.NotFound({ flags: { path: context.url.pathname } }), 404);

const notPorted = (context: RequestContext) =>
  page(
    PageFlags.NotPorted({
      flags: {
        pageName: context.translator.t("Panel"),
        path: context.url.pathname,
      },
    }),
    501
  );

const gate = Effect.fn("PanelRouter.gate")(function* gate(
  context: RequestContext,
  mode: PanelMode
) {
  const access = yield* currentPanelAccess();

  return refusalFor(access, mode).pipe(
    Option.map((refusal) =>
      refusal.reason === "sign_in"
        ? redirect(
            `${LOGIN_URL}?next=${encodeURIComponent(context.url.pathname + context.url.search).replaceAll("%2F", "/")}`
          )
        : redirect(
            "/",
            context.translator.t(
              "You don't have permission to access the backoffice panel."
            )
          )
    )
  );
});

type PanelChrome = Effect.Success<ReturnType<typeof loadPanelEventChrome>>;

const panelPage = (
  context: RequestContext,
  options: Readonly<{
    activeNav: PanelNav;
    chrome: PanelChrome;
    page: PageFlagsType;
  }>
) =>
  page(
    PageFlags.Panel({
      flags: {
        chrome: eventChrome(context, {
          ...options.chrome,
          activeNav: options.activeNav,
        }),
        page: options.page,
      },
    })
  );

const eventMissing = (context: RequestContext) =>
  redirect("/panel/", context.translator.t("Event not found."));

const routeProposals = Effect.fn("PanelRouter.routeProposals")(
  function* routeProposals(
    context: RequestContext,
    chrome: PanelChrome,
    rest: readonly string[]
  ) {
    const at = (pageFlags: PageFlagsType) =>
      panelPage(context, { activeNav: "proposals", chrome, page: pageFlags });

    const listHref = `/panel/event/${chrome.event.slug}/proposals/`;

    const missing = () =>
      redirect(listHref, context.translator.t("Proposal not found."));

    const [first, second] = rest;

    if (first === undefined) {
      const list = yield* loadProposals(context, chrome).pipe(
        Effect.map(Option.some),
        Effect.catchIf(
          (error): error is TrackOutsideEvent =>
            error instanceof TrackOutsideEvent,
          () => Effect.succeed(Option.none())
        )
      );

      return Option.match(list, {
        onNone: () => notFound(context),
        onSome: (flags) => at(PanelPageFlags.Proposals({ flags })),
      });
    }

    if (first === "create" && second === undefined) {
      const form = yield* loadProposalForm(
        context,
        chrome.event,
        Option.none()
      );

      return Option.match(form, {
        onNone: missing,
        onSome: (flags) => at(PanelPageFlags.ProposalForm({ flags })),
      });
    }

    if (/^\d+$/u.test(first)) {
      const id = Number(first);

      if (second === undefined) {
        const detail = yield* loadProposalDetail(context, chrome.event, id);

        return Option.match(detail, {
          onNone: missing,
          onSome: (flags) => at(PanelPageFlags.ProposalDetail({ flags })),
        });
      }

      if (second === "edit" && rest.length === 2) {
        const form = yield* loadProposalForm(
          context,
          chrome.event,
          Option.some(id)
        );

        return Option.match(form, {
          onNone: missing,
          onSome: (flags) => at(PanelPageFlags.ProposalForm({ flags })),
        });
      }
    }

    return notPorted(context);
  }
);

const routeFacilitators = Effect.fn("PanelRouter.routeFacilitators")(
  function* routeFacilitators(
    context: RequestContext,
    chrome: PanelChrome,
    rest: readonly string[]
  ) {
    const at = (pageFlags: PageFlagsType) =>
      panelPage(context, {
        activeNav: "facilitators",
        chrome,
        page: pageFlags,
      });

    const listHref = `/panel/event/${chrome.event.slug}/facilitators/`;

    const missing = () =>
      redirect(listHref, context.translator.t("Facilitator not found."));

    const [first, second] = rest;

    if (first === undefined) {
      return at(
        PanelPageFlags.Facilitators({
          flags: yield* loadFacilitators(context, chrome),
        })
      );
    }

    if (first === "bin" && second === undefined) {
      return at(
        PanelPageFlags.FacilitatorBin({
          flags: yield* loadFacilitatorBin(context, chrome.event),
        })
      );
    }

    if (first === "create" && second === undefined) {
      const form = yield* loadFacilitatorForm(chrome.event, Option.none());

      return Option.match(form, {
        onNone: missing,
        onSome: (flags) => at(PanelPageFlags.FacilitatorForm({ flags })),
      });
    }

    if (["merge", "columns", "export"].includes(first)) {
      return notPorted(context);
    }

    if (second === undefined) {
      const detail = yield* loadFacilitatorPage(chrome.event, first);

      return Option.match(detail, {
        onNone: missing,
        onSome: (flags) => at(PanelPageFlags.FacilitatorDetail({ flags })),
      });
    }

    if (second === "edit" && rest.length === 2) {
      const form = yield* loadFacilitatorForm(chrome.event, Option.some(first));

      return Option.match(form, {
        onNone: missing,
        onSome: (flags) => at(PanelPageFlags.FacilitatorForm({ flags })),
      });
    }

    return notPorted(context);
  }
);

const routeEventPage = Effect.fn("PanelRouter.routeEventPage")(
  function* routeEventPage(
    context: RequestContext,
    chrome: PanelChrome,
    rest: readonly string[]
  ) {
    const { slug } = chrome.event;
    const section = rest.join("/");

    const at = (activeNav: PanelNav, pageFlags: PageFlagsType) =>
      panelPage(context, { activeNav, chrome, page: pageFlags });

    if (rest.length === 0) {
      const stats = yield* (yield* PanelStore).eventStats(chrome.event.id);

      return at(
        "index",
        PanelPageFlags.Dashboard({
          flags: {
            ...stats,
            totalSessions: stats.pendingProposals + stats.scheduledSessions,
          },
        })
      );
    }

    if (section === "cfp") {
      return at(
        "cfp",
        PanelPageFlags.Cfp({ flags: yield* loadCfp(context, chrome.event) })
      );
    }

    if (section === "timetable") {
      return at(
        "timetable",
        PanelPageFlags.Timetable({
          flags: yield* loadTimetable(context, chrome.event),
        })
      );
    }

    if (section === "tracks") {
      return at(
        "tracks",
        PanelPageFlags.Tracks({ flags: yield* loadTracks(chrome.event) })
      );
    }

    if (section === "tracks/create") {
      const form = yield* loadTrackForm(chrome.event, Option.none());

      return Option.match(form, {
        onNone: () => notPorted(context),
        onSome: (flags) => at("tracks", PanelPageFlags.TrackForm({ flags })),
      });
    }

    if (rest.length === 3 && rest[0] === "tracks" && rest[2] === "edit") {
      const form = yield* loadTrackForm(
        chrome.event,
        Option.fromNullishOr(rest[1])
      );

      return Option.match(form, {
        onNone: () =>
          redirect(
            `/panel/event/${slug}/tracks/`,
            context.translator.t("Track not found.")
          ),
        onSome: (flags) => at("tracks", PanelPageFlags.TrackForm({ flags })),
      });
    }

    if (rest[0] === "proposals") {
      return yield* routeProposals(context, chrome, rest.slice(1));
    }

    if (rest[0] === "facilitators") {
      return yield* routeFacilitators(context, chrome, rest.slice(1));
    }

    return notPorted(context);
  }
);

const routeEvent = Effect.fn("PanelRouter.routeEvent")(function* routeEvent(
  context: RequestContext,
  slug: string,
  rest: readonly string[]
) {
  const chrome = yield* loadPanelEventChrome({ mode: "read", slug }).pipe(
    Effect.map(Option.some),
    Effect.catchTag("NotFound", () => Effect.succeed(Option.none()))
  );

  if (Option.isNone(chrome)) {
    return eventMissing(context);
  }

  return yield* routeEventPage(context, chrome.value, rest);
});

const routeIndex = Effect.fn("PanelRouter.routeIndex")(function* routeIndex() {
  const sphere = yield* CurrentSphere;
  const events = yield* (yield* EventStore).listBySphere(sphere.id);

  return Option.match(Option.fromNullishOr(events[0]), {
    onNone: () => redirect("/panel/events/new/"),
    onSome: (event) => redirect(`/panel/event/${event.slug}/`),
  });
});

export const routePanel = Effect.fn("PanelRouter.route")(function* routePanel(
  context: RequestContext
) {
  const { pathname } = context.url;

  if (!pathname.endsWith("/")) {
    return Routed.Redirect({
      location: `${pathname}/${context.url.search}`,
      status: 301,
    });
  }

  const parts = pathname
    .split("/")
    .filter((part) => part !== "")
    .slice(1);

  return yield* Effect.gen(function* routeGated() {
    const refused = yield* gate(context, "read");

    if (Option.isSome(refused)) {
      return refused.value;
    }

    if (parts.length === 0) {
      return yield* routeIndex();
    }

    const [kind, slug, ...rest] = parts;

    if (kind === "event" && slug !== undefined) {
      return yield* routeEvent(context, slug, rest);
    }

    return notPorted(context);
  }).pipe(
    Effect.catchTag("PanelAccessDenied", () =>
      Effect.succeed(
        redirect(
          "/",
          context.translator.t(
            "You don't have permission to access the backoffice panel."
          )
        )
      )
    ),
    providePanelServices(context)
  );
});

export { notFound };
