import type { Html, HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";
import { icon } from "./icon.js";
import type { IconData } from "./icon.js";

export const statCard = <Message>(
  options: Readonly<{
    label: string;
    of?: number;
    suffix?: string;
    value: number | string;
  }>,
  h: HtmlBuilder<Message>
) =>
  h.div(
    [h.Class("rounded-xl border border-border bg-bg-tertiary p-3")],
    [
      h.div(
        [h.Class("text-2xl font-semibold tabular-nums")],
        [
          `${options.value}${options.of === undefined ? "" : `/${options.of}`}${options.suffix ?? ""}`,
        ]
      ),
      h.div([h.Class("mt-0.5 text-xs text-foreground-muted")], [options.label]),
    ]
  );

export const statusHero = <Message>(
  options: Readonly<{
    errorCode?: string;
    heading: string;
    icon: IconData;
    iconColor: string;
    lead: string;
  }>,
  h: HtmlBuilder<Message>
): ReadonlyArray<Html> => {
  const compact = options.errorCode !== undefined && options.errorCode !== "";

  return [
    h.div(
      [h.Class(cx("mb-6", compact && "flex items-center gap-4"))],
      [
        h.div(
          [
            h.Class(
              "w-16 h-16 rounded-2xl flex items-center justify-center bg-white dark:bg-neutral-900"
            ),
          ],
          [icon(options.icon, { class: cx("w-8 h-8", options.iconColor) }, h)]
        ),
        compact
          ? h.span(
              [h.Class("text-6xl font-bold text-foreground-muted")],
              [options.errorCode ?? ""]
            )
          : h.empty,
      ]
    ),
    h.h1(
      [
        h.Class(
          cx(
            compact ? "text-2xl" : "text-3xl",
            "font-bold mb-3 text-foreground"
          )
        ),
      ],
      [options.heading]
    ),
    h.p(
      [h.Class(cx(compact ? "mb-2" : "text-lg mb-6", "text-foreground-muted"))],
      [options.lead]
    ),
  ];
};

export const emptyState = <Message>(
  options: Readonly<{
    action?: Html;
    icon: IconData;
    lead: string;
    title: string;
  }>,
  h: HtmlBuilder<Message>
) =>
  h.div(
    [h.Class("text-center py-16")],
    [
      h.div(
        [h.Class("text-foreground-muted")],
        [
          h.div(
            [h.Class("mb-4")],
            [icon(options.icon, { class: "w-16 h-16 mx-auto opacity-50" }, h)]
          ),
          h.p([h.Class("text-xl font-medium mb-2")], [options.title]),
          h.p([h.Class("text-sm")], [options.lead]),
        ]
      ),
      options.action === undefined
        ? h.empty
        : h.div([h.Class("mt-6")], [options.action]),
    ]
  );
