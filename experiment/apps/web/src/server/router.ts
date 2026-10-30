import { Data, Effect } from "effect";

import { contentSlugs } from "../client/content-page/flags.js";
import type { ContentSlug } from "../client/content-page/flags.js";
import { PageFlags } from "../client/model.js";
import { loadAbout } from "./pages/about.js";
import { loadContentPage } from "./pages/content-page.js";
import { loadEventsFeed } from "./pages/events-feed.js";
import { loadLanding } from "./pages/landing.js";
import { rootOrigin } from "./request-context.js";
import type { RequestContext } from "./request-context.js";

export type Routed = Data.TaggedEnum<{
  Page: { readonly flags: PageFlags; readonly status: number };
  Redirect: { readonly location: string; readonly status: 301 | 302 };
}>;
export const Routed = Data.taggedEnum<Routed>();

const isContentSlug = (slug: string): slug is ContentSlug =>
  contentSlugs.some((known) => known === slug);

const legacyContentPath = /^\/page\/\/?([a-z-]+)\/$/u;

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

  if (pathname === "/") {
    if (!context.isRootSphere) {
      return page(
        PageFlags.EventsFeed({ flags: yield* loadEventsFeed(context) })
      );
    }

    if (context.viewer._tag === "Some") {
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

  const legacy = legacyContentPath.exec(pathname)?.[1];

  if (legacy !== undefined && isContentSlug(legacy)) {
    return Routed.Redirect({ location: `/${legacy}/`, status: 301 });
  }

  if (!pathname.endsWith("/") && staticPaths.has(`${pathname}/`)) {
    return Routed.Redirect({ location: `${pathname}/${search}`, status: 301 });
  }

  return notFound(context);
});
