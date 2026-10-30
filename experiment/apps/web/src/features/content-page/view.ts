import type { HtmlBuilder } from "foldkit/html";

import type {
  ContentPageFlags,
  ContentSlug,
} from "../../client/content-page/flags.js";
import type { Translator } from "../../ui/i18n.js";
import { icon } from "../../ui/icon.js";
import { arrowLeftOutline } from "../../ui/icons.js";
import type { PageContext } from "../page-context.js";
import type { PageTitle } from "../shell/title.js";

const titles: Readonly<Record<ContentSlug, string>> = {
  "privacy-policy": "Privacy Policy",
  "terms-of-service": "Terms of Service",
};

export const contentPageName = (slug: ContentSlug, translator: Translator) =>
  translator.t(titles[slug]);

export const contentPageTitle = (
  flags: ContentPageFlags,
  context: PageContext
): PageTitle => ({
  name: contentPageName(flags.slug, context.translator),
  sphereSuffix: true,
});

export const contentPageView = <Message>(
  flags: ContentPageFlags,
  context: PageContext,
  h: HtmlBuilder<Message>
) =>
  h.div(
    [h.Class("max-w-3xl mx-auto w-full")],
    [
      h.div(
        [h.Class("card")],
        [
          h.div(
            [
              h.Class("card-body prose max-w-none text-foreground"),
              h.InnerHTML(flags.documentHtml),
            ],
            []
          ),
        ]
      ),
      h.div(
        [h.Class("mt-6 text-center")],
        [
          h.a(
            [h.Href("/"), h.Class("btn btn-secondary")],
            [
              icon(arrowLeftOutline, { class: "w-4 h-4" }, h),
              context.translator.t("Back to Home"),
            ]
          ),
        ]
      ),
    ]
  );
