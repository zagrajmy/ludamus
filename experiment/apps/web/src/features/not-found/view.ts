import type { HtmlBuilder } from "foldkit/html";

import type { NotPortedFlags } from "../../client/not-found/flags.js";
import { icon } from "../../ui/icon.js";
import {
  homeOutline,
  questionMarkCircleOutline,
  wrenchScrewdriverOutline,
} from "../../ui/icons.js";
import { statusHero } from "../../ui/status.js";
import type { PageContext } from "../page-context.js";
import type { PageTitle } from "../shell/title.js";

export const notFoundTitle = (context: PageContext): PageTitle => ({
  name: `${context.translator.t("Page Not Found")} • 404`,
  sphereSuffix: true,
});

const homeButton = <Message>(context: PageContext, h: HtmlBuilder<Message>) =>
  h.a(
    [h.Href("/"), h.Class("btn btn-primary")],
    [
      icon(homeOutline, { class: "w-5 h-5" }, h),
      context.translator.t("Go to Home"),
    ]
  );

export const notFoundView = <Message>(
  context: PageContext,
  h: HtmlBuilder<Message>
) => {
  const { translator } = context;

  return h.div(
    [h.Class("flex-1 flex items-center justify-center")],
    [
      h.div(
        [h.Class("max-w-screen-sm xl:min-w-[600px] mx-auto px-4")],
        [
          ...statusHero(
            {
              errorCode: "404",
              heading: translator.t("Critical Failure!"),
              icon: questionMarkCircleOutline,
              iconColor: "text-warning",
              lead: translator.t(
                "You rolled a nat 1 on your Navigation check!"
              ),
            },
            h
          ),
          h.p(
            [h.Class("text-sm mb-4 text-foreground-muted")],
            [translator.t("The path you seek has vanished into the mists.")]
          ),
          h.p(
            [h.Class("mb-6 text-foreground")],
            [
              translator.t(
                "The page you're looking for doesn't exist or may have moved."
              ),
            ]
          ),
          h.div(
            [h.Class("flex flex-col sm:flex-row gap-3")],
            [homeButton(context, h)]
          ),
        ]
      ),
    ]
  );
};

export const notPortedTitle = (flags: NotPortedFlags): PageTitle => ({
  name: flags.pageName,
  sphereSuffix: true,
});

export const notPortedView = <Message>(
  flags: NotPortedFlags,
  context: PageContext,
  h: HtmlBuilder<Message>
) =>
  h.div(
    [h.Class("flex-1 flex items-center justify-center")],
    [
      h.div(
        [
          h.Class("max-w-screen-sm mx-auto px-4"),
          h.DataAttribute("not-ported", flags.path),
        ],
        [
          ...statusHero(
            {
              errorCode: "501",
              heading: context.translator.t(
                "This page has not moved to the new app yet."
              ),
              icon: wrenchScrewdriverOutline,
              iconColor: "text-warning",
              lead: flags.pageName,
            },
            h
          ),
          h.div(
            [h.Class("flex flex-col sm:flex-row gap-3")],
            [homeButton(context, h)]
          ),
        ]
      ),
    ]
  );
