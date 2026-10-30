import type { Html, HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";
import { icon } from "./icon.js";
import type { IconData } from "./icon.js";

export type TabVariant = "segment" | "underline";

export type TabLink = Readonly<{
  active: boolean;
  href: string;
  icon?: IconData;
  key: string;
  label: string;
}>;

const segmentLink =
  "flex items-center gap-1.5 rounded-xl px-3 py-1.5 sm:py-2 text-sm font-semibold whitespace-nowrap text-foreground-muted transition-colors hover:text-foreground aria-selected:bg-bg-secondary aria-selected:text-foreground aria-selected:shadow-sm";

const underlineLink =
  "tab-nav-link inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-t-lg px-4 py-2 text-sm font-medium text-foreground-muted transition-colors aria-[selected=false]:hover:bg-warm-100 aria-[selected=false]:hover:text-foreground dark:aria-[selected=false]:hover:bg-bg-tertiary aria-selected:relative aria-selected:z-10 aria-selected:-mb-px aria-selected:bg-bg-secondary aria-selected:py-2.5 aria-selected:text-foreground aria-selected:shadow-[0_-1px_3px_0_rgba(0,0,0,0.06)]";

export const tabLink = <Message>(
  tab: TabLink,
  variant: TabVariant,
  h: HtmlBuilder<Message>
) =>
  h.a(
    [
      h.Key(tab.key),
      h.Class(variant === "segment" ? segmentLink : underlineLink),
      h.Role("tab"),
      h.Href(tab.href),
      h.AriaSelected(tab.active),
      h.DataAttribute("tab", tab.key),
    ],
    [
      tab.icon === undefined
        ? h.empty
        : icon(tab.icon, { class: "w-4 h-4" }, h),
      tab.label,
    ]
  );

export const tabList = <Message>(
  options: Readonly<{
    ariaLabel?: string;
    extraClass?: string;
    tabs: ReadonlyArray<TabLink>;
    variant?: TabVariant;
  }>,
  h: HtmlBuilder<Message>
) => {
  const variant = options.variant ?? "underline";
  const label =
    options.ariaLabel === undefined ? [] : [h.AriaLabel(options.ariaLabel)];
  const links = options.tabs.map((tab) => tabLink(tab, variant, h));

  return variant === "segment"
    ? h.nav(
        [
          h.Class(
            cx(
              "inline-flex items-stretch gap-0.5 rounded-2xl border border-border bg-bg-tertiary p-1",
              options.extraClass
            )
          ),
          h.Role("tablist"),
          ...label,
        ],
        links
      )
    : h.div(
        [h.Class("tab-nav-scroll")],
        [
          h.nav(
            [
              h.Class(cx("tab-nav flex items-end gap-1", options.extraClass)),
              h.Role("tablist"),
              ...label,
            ],
            links
          ),
        ]
      );
};

export const tabShell = <Message>(
  options: Readonly<{ body: Html; bodyClass?: string; tabs: Html }>,
  h: HtmlBuilder<Message>
) =>
  h.div(
    [
      h.Class(
        "tab-shell flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border"
      ),
    ],
    [
      h.div(
        [
          h.Class(
            "tab-shell-bar bg-warm-150 px-3 pt-3 border-b border-border dark:bg-bg-tertiary [&_.tab-nav-link[aria-selected=true]]:border-border [&_.tab-nav-link[aria-selected=true]]:border-b-0 [&_.tab-nav-link[aria-selected=true]]:border"
          ),
        ],
        [options.tabs]
      ),
      h.div(
        [
          h.Class(
            cx(
              "tab-shell-body flex-1 bg-bg-secondary px-3 py-4 shadow-[0_-1px_16px_0_rgba(0,0,0,0.06)] sm:px-4 sm:py-6 lg:px-6",
              options.bodyClass
            )
          ),
        ],
        [options.body]
      ),
    ]
  );
