import type { HtmlBuilder } from "foldkit/html";

import type { Translator } from "./i18n.js";
import { icon } from "./icon.js";
import type { IconData } from "./icon.js";

const eye: IconData = {
  paths: [
    { d: "M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z" },
    {
      clipRule: "evenodd",
      d: "M.664 10.59a1.651 1.651 0 010-1.186A10.004 10.004 0 0110 3c4.257 0 7.893 2.66 9.336 6.41.147.381.146.804 0 1.186A10.004 10.004 0 0110 17c-4.257 0-7.893-2.66-9.336-6.41zM14 10a4 4 0 11-8 0 4 4 0 018 0z",
      fillRule: "evenodd",
    },
  ],
  variant: "mini",
};

const lockClosed: IconData = {
  paths: [
    {
      clipRule: "evenodd",
      d: "M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z",
      fillRule: "evenodd",
    },
  ],
  variant: "mini",
};

export const visibilityBadge = <Message>(
  options: Readonly<{ isPublic: boolean; translator: Translator }>,
  h: HtmlBuilder<Message>
) =>
  options.isPublic
    ? h.span(
        [
          h.Class(
            "ml-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-success-bg text-success-text"
          ),
        ],
        [icon(eye, { class: "w-3 h-3" }, h), options.translator.t("public")]
      )
    : h.span(
        [
          h.Class(
            "ml-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-bg-tertiary text-foreground-muted"
          ),
        ],
        [
          icon(lockClosed, { class: "w-3 h-3" }, h),
          options.translator.t("organizers only"),
        ]
      );

export const visibilityIcon = <Message>(
  options: Readonly<{ isPublic: boolean; translator: Translator }>,
  h: HtmlBuilder<Message>
) =>
  options.isPublic
    ? h.span(
        [
          h.Class("ml-1 inline-flex align-middle text-success"),
          h.Title(options.translator.t("Shown publicly")),
        ],
        [
          icon(eye, { class: "w-3 h-3" }, h),
          h.span([h.Class("sr-only")], [options.translator.t("public")]),
        ]
      )
    : h.span(
        [
          h.Class("ml-1 inline-flex align-middle text-foreground-muted"),
          h.Title(options.translator.t("Visible to organizers only")),
        ],
        [
          icon(lockClosed, { class: "w-3 h-3" }, h),
          h.span(
            [h.Class("sr-only")],
            [options.translator.t("organizers only")]
          ),
        ]
      );
