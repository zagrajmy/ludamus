import { Option } from "effect";
import type { Html, HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";
import type { Child } from "./html.js";
import { icon } from "./icon.js";
import type { IconData } from "./icon.js";

export const menuSurfaceClass = (
  options: Readonly<{ extraClass: string; isOpen: boolean; origin?: string }>
) =>
  cx(
    options.extraClass,
    options.origin ?? "origin-top-right",
    "opacity-0 scale-[0.98] translate-y-1 blur-[1px] transition-[opacity,scale,translate,filter] duration-160 ease-out data-[menu-visible]:opacity-100 data-[menu-visible]:scale-100 data-[menu-visible]:translate-y-0 data-[menu-visible]:blur-none data-[menu-visible]:duration-210 data-[menu-visible]:ease-spring-a-bit motion-reduce:scale-100 motion-reduce:translate-y-0"
  );

export const menuSurface = <Message>(
  options: Readonly<{
    children: readonly Child[];
    extraClass: string;
    isOpen: boolean;
    origin?: string;
  }>,
  h: HtmlBuilder<Message>
) =>
  h.div(
    [
      h.Class(menuSurfaceClass(options)),
      h.DataAttribute("menu-surface", ""),
      ...(options.isOpen ? [h.DataAttribute("menu-visible", "")] : []),
    ],
    options.children
  );

export type DisclosureMenuOptions<Message> = Readonly<{
  hover?: boolean;
  id: string;
  isOpen: boolean;
  onToggle: (isOpen: boolean) => Message;
  panel: (isOpen: boolean) => Html;
  panelClass: string;
  trigger: readonly Child[];
  triggerClass: string;
  triggerLabel?: string;
}>;

export const disclosureMenu = <Message>(
  options: DisclosureMenuOptions<Message>,
  h: HtmlBuilder<Message>
) =>
  h.div(
    [
      h.Class("relative"),
      h.DataAttribute("menu", ""),
      ...(options.hover === true
        ? [
            h.DataAttribute("menu-hover", ""),
            h.OnMouseEnter(options.onToggle(true)),
            h.OnMouseLeave(options.onToggle(false)),
          ]
        : []),
      h.OnKeyDownPreventDefault((key) =>
        key === "Escape" && options.isOpen
          ? Option.some(options.onToggle(false))
          : Option.none()
      ),
      h.OnFocusLeave(options.onToggle(false)),
    ],
    [
      h.button(
        [
          h.Type("button"),
          h.DataAttribute("menu-button", ""),
          h.AriaControls(options.id),
          h.AriaExpanded(options.isOpen),
          ...(options.triggerLabel === undefined
            ? []
            : [h.AriaLabel(options.triggerLabel)]),
          h.Class(options.triggerClass),
          h.OnClick(options.onToggle(!options.isOpen)),
        ],
        options.trigger
      ),
      h.div(
        [
          h.Id(options.id),
          h.DataAttribute("menu-panel", ""),
          ...(options.isOpen ? [] : [h.Hidden(true)]),
          h.Class(options.panelClass),
        ],
        [options.panel(options.isOpen)]
      ),
    ]
  );

export type MenuItem = Readonly<{
  href: string;
  icon?: IconData;
  key: string;
  label: string;
  tone?: "danger" | "default";
}>;

export const actionDropdown = <Message>(
  options: Readonly<{
    align?: "left" | "right";
    hover?: boolean;
    id: string;
    isOpen: boolean;
    items: readonly Html[];
    label?: string;
    onToggle: (isOpen: boolean) => Message;
    trigger: readonly Child[];
    triggerClass?: string;
  }>,
  h: HtmlBuilder<Message>
) =>
  disclosureMenu(
    {
      ...(options.hover === undefined ? {} : { hover: options.hover }),
      id: options.id,
      isOpen: options.isOpen,
      onToggle: options.onToggle,
      panel: (isOpen) =>
        menuSurface(
          {
            children: options.items,
            extraClass:
              "min-w-52 p-1 rounded-xl border border-border bg-bg-secondary shadow-(--shadow-elevated)",
            isOpen,
            origin: "origin-top",
          },
          h
        ),
      panelClass: cx(
        "absolute top-full z-50 pt-2",
        options.align === "left" ? "left-0" : "right-0"
      ),
      trigger: [
        ...options.trigger,
        ...(options.label === undefined
          ? []
          : [h.span([h.Class("sr-only")], [options.label])]),
      ],
      triggerClass: cx(
        "cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
        options.triggerClass
      ),
    },
    h
  );

export const menuLink = <Message>(item: MenuItem, h: HtmlBuilder<Message>) =>
  h.a(
    [
      h.Key(item.key),
      h.Href(item.href),
      h.Class(
        cx(
          "flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-bg-tertiary",
          item.tone === "danger" ? "text-danger" : "text-foreground-secondary"
        )
      ),
    ],
    [
      item.icon === undefined
        ? h.empty
        : icon(item.icon, { class: "w-4 h-4 opacity-60" }, h),
      item.label,
    ]
  );
