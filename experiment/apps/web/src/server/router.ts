import { NotificationStore } from "@zagrajmy/core/ports/notification-store";
import { Effect, Option, Predicate } from "effect";

import { contentSlugs } from "../client/content-page/flags.js";
import type { ContentSlug } from "../client/content-page/flags.js";
import { PageFlags } from "../client/model.js";
import { loadAbout } from "./pages/about.js";
import { loadContentPage } from "./pages/content-page.js";
import { ENROLL_PAGE_PATH, loadEnrollPage } from "./pages/enroll-page.js";
import { loadEventPage } from "./pages/event-page.js";
import { loadEventsFeed } from "./pages/events-feed.js";
import { loadLanding } from "./pages/landing.js";
import { OFFER_PAGE_PATH, loadOfferPage } from "./pages/offer-page.js";
import { isPanelPath, routePanel } from "./pages/panel/router.js";
import {
  ACCEPT_PAGE_PATH,
  routeProposalAccept,
} from "./pages/proposal-accept.js";
import { loadPropose, proposeSlugOf } from "./pages/propose.js";
import { rootOrigin } from "./request-context.js";
import type { RequestContext } from "./request-context.js";
import { Routed } from "./routed.js";

export { Routed } from "./routed.js";

const isContentSlug = (slug: string): slug is ContentSlug =>
  contentSlugs.some((known) => known === slug);

const legacyContentPath = /^\/page\/\/?(?<slug>[a-z-]+)\/$/u;

const staticPaths = new Set([
  "/",
  "/about/",
  "/events/",
  "/timeline/",
  ...contentSlugs.map((slug) => `/${slug}/`),
]);

const page = (flags: PageFlags, status = 200) => Routed.Page({ flags, status });

const notFound = (context: RequestContext) =>
  page(PageFlags.NotFound({ flags: { path: context.url.pathname } }), 404);

export const route = Effect.fn("Router.route")(function* route(
  context: RequestContext
) {
  const { pathname, search } = context.url;

  const acceptPath = ACCEPT_PAGE_PATH.exec(pathname);

  if (acceptPath !== null) {
    return yield* routeProposalAccept(context, {
      eventSlug: decodeURIComponent(acceptPath.groups?.eventSlug ?? ""),
      sessionId: Number(acceptPath.groups?.sessionId),
    });
  }

  const enrollPath = ENROLL_PAGE_PATH.exec(pathname);

  if (enrollPath !== null) {
    const enroll = yield* loadEnrollPage(context, {
      eventSlug: decodeURIComponent(enrollPath.groups?.eventSlug ?? ""),
      sessionId: Number(enrollPath.groups?.sessionId),
    });

    return Predicate.isTagged("Page")(enroll)
      ? page(PageFlags.EnrollPage({ flags: enroll.flags }))
      : Routed.Redirect({
          flashes: enroll.flashes,
          location: enroll.location,
          status: 302,
        });
  }

  const notificationPath = /^\/notifications\/(?<id>\d+)\/do\/open$/u.exec(
    pathname
  );

  if (notificationPath !== null && Option.isSome(context.viewer)) {
    const store = yield* NotificationStore;

    const found = yield* store.readForRecipient({
      id: Number(notificationPath.groups?.id),
      userId: context.viewer.value.id,
    });

    if (Option.isNone(found)) {
      return notFound(context);
    }

    return Routed.Redirect({
      location: found.value.url === "" ? "/notifications/" : found.value.url,
      status: 302,
    });
  }

  const offerPath = OFFER_PAGE_PATH.exec(pathname);

  if (offerPath !== null) {
    const offer = yield* loadOfferPage(
      context,
      decodeURIComponent(offerPath.groups?.token ?? "")
    );

    return Predicate.isTagged("Page")(offer)
      ? page(PageFlags.OfferPage({ flags: offer.flags }))
      : Routed.Redirect({
          flashes: offer.flashes,
          location: offer.location,
          status: 302,
        });
  }

  const proposeSlug = proposeSlugOf(pathname);

  if (Predicate.isTagged("Some")(proposeSlug)) {
    const propose = yield* loadPropose(context, proposeSlug.value);

    return Predicate.isTagged("Flags")(propose)
      ? page(PageFlags.Propose({ flags: propose.flags }))
      : Routed.Redirect({
          flashes: propose.flashes,
          location: propose.location,
          status: 302,
        });
  }

  const eventSlug = /^\/event\/(?<slug>[^/]+)\/$/u.exec(pathname)?.groups?.slug;

  if (eventSlug !== undefined) {
    const eventPage = yield* loadEventPage(
      context,
      decodeURIComponent(eventSlug)
    );

    return Predicate.isTagged("Some")(eventPage)
      ? page(PageFlags.EventPage({ flags: eventPage.value }))
      : notFound(context);
  }

  if (pathname.startsWith("/chronology/")) {
    return Routed.Redirect({
      location: `${pathname.slice("/chronology".length)}${search}`,
      status: 301,
    });
  }

  if (isPanelPath(pathname)) {
    return yield* routePanel(context);
  }

  if (pathname === "/") {
    if (!context.isRootSphere) {
      return page(
        PageFlags.EventsFeed({ flags: yield* loadEventsFeed(context) })
      );
    }

    if (Predicate.isTagged("Some")(context.viewer)) {
      return page(
        PageFlags.NotPorted({
          flags: {
            pageName: context.translator.t("Your dashboard"),
            path: pathname,
          },
        }),
        501
      );
    }

    return page(PageFlags.Landing({ flags: yield* loadLanding(context) }));
  }

  if (pathname === "/events/" || pathname === "/timeline/") {
    return Routed.Redirect({ location: `/${search}`, status: 301 });
  }

  if (pathname === "/about/") {
    return context.isRootSphere
      ? page(PageFlags.About({ flags: yield* loadAbout(context) }))
      : Routed.Redirect({
          location: `${rootOrigin(context)}/about/`,
          status: 301,
        });
  }

  const slug = pathname.slice(1, -1);

  if (isContentSlug(slug) && pathname === `/${slug}/`) {
    return page(PageFlags.ContentPage({ flags: yield* loadContentPage(slug) }));
  }

  const legacy = legacyContentPath.exec(pathname)?.groups?.slug;

  if (legacy !== undefined && isContentSlug(legacy)) {
    return Routed.Redirect({ location: `/${legacy}/`, status: 301 });
  }

  if (!pathname.endsWith("/") && staticPaths.has(`${pathname}/`)) {
    return Routed.Redirect({ location: `${pathname}/${search}`, status: 301 });
  }

  return notFound(context);
});
