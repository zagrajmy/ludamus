import type { HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";
import type { Translator } from "./i18n.js";
import { icon } from "./icon.js";
import type { IconData } from "./icon.js";

export const pill = <Message>(
  options: Readonly<{
    icon?: IconData;
    maxWidth?: string;
    size?: "md" | "sm";
    title?: string;
    value: string;
  }>,
  h: HtmlBuilder<Message>
) =>
  h.span(
    [
      h.Class(
        cx(
          "inline-flex min-w-0 items-center gap-1 rounded-2xl font-medium",
          options.maxWidth ?? "max-w-[200px]",
          "bg-warm-200/80 dark:bg-neutral-700 text-warm-700 dark:text-neutral-300",
          options.size === "sm"
            ? "text-xs px-2 py-0.5"
            : "text-sm px-2.5 py-0.5"
        )
      ),
      h.Title(options.title ?? options.value),
    ],
    [
      options.icon === undefined
        ? h.empty
        : icon(options.icon, { class: "size-3.5 shrink-0 opacity-80" }, h),
      h.span([h.Class("truncate")], [options.value]),
    ]
  );

const visiblePills = 3;

export const pillList = <Message>(
  options: Readonly<{
    icon?: IconData;
    items: readonly string[];
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
) => {
  if (options.items.length === 0) {
    return h.span(
      [h.Class("text-foreground-muted")],
      [
        h.span([h.AriaHidden(true)], ["—"]),
        h.span([h.Class("sr-only")], [options.translator.t("None")]),
      ]
    );
  }

  const rest = options.items.slice(visiblePills);

  return h.ul(
    [h.Class("flex min-w-0 flex-wrap items-center gap-1")],
    [
      ...options.items.slice(0, visiblePills).map((value) =>
        h.li(
          [h.Class("flex min-w-0")],
          [
            pill(
              {
                ...(options.icon === undefined ? {} : { icon: options.icon }),
                size: "sm",
                value,
              },
              h
            ),
          ]
        )
      ),
      rest.length === 0
        ? h.empty
        : h.li(
            [h.Class("flex")],
            [
              h.span(
                [
                  h.Class(
                    "inline-flex items-center rounded-2xl bg-warm-200/80 dark:bg-neutral-700 text-warm-700 dark:text-neutral-300 text-xs px-2 py-0.5 font-medium"
                  ),
                  h.Title(rest.join(", ")),
                ],
                [
                  `+${rest.length}`,
                  h.span([h.Class("sr-only")], [`: ${rest.join(", ")}`]),
                ]
              ),
            ]
          ),
    ]
  );
};
