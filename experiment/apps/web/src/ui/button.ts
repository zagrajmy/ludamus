import type { Attribute, Html, HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";
import type { Child } from "./html.js";
import { icon } from "./icon.js";
import type { IconData } from "./icon.js";

export type ButtonVariant = "danger" | "primary" | "secondary";

export type ButtonSize = "lg" | "md" | "sm";

const sizeClasses: Readonly<Record<ButtonSize, string>> = {
  lg: "px-6 py-3 text-base",
  md: "px-4 py-2 text-sm",
  sm: "px-3 py-1.5 text-xs gap-1.5 rounded-xl",
};

const iconSizeClasses: Readonly<Record<ButtonSize, string>> = {
  lg: "w-5 h-5",
  md: "w-4 h-4",
  sm: "w-3.5 h-3.5",
};

const variantClasses: Readonly<Record<ButtonVariant, string>> = {
  danger: "btn btn-danger",
  primary: "btn btn-primary",
  secondary: "btn btn-secondary",
};

type CommonOptions<Message> = Readonly<{
  attributes?: readonly Attribute<Message>[];
  disabled?: boolean;
  extraClass?: string;
  fullWidthMobile?: boolean;
  icon?: IconData;
  size?: ButtonSize;
  text: Child;
  variant?: ButtonVariant;
}>;

export type ButtonOptions<Message> = CommonOptions<Message> &
  Readonly<{ type?: "button" | "reset" | "submit" }>;

export type LinkButtonOptions<Message> = CommonOptions<Message> &
  Readonly<{ href: string }>;

const classes = <Message>(
  options: CommonOptions<Message>,
  fullWidthByDefault: boolean
) =>
  cx(
    variantClasses[options.variant ?? "primary"],
    sizeClasses[options.size ?? "md"],
    (options.fullWidthMobile ?? fullWidthByDefault) && "max-md:w-full",
    options.disabled === true && "opacity-50 cursor-not-allowed",
    options.extraClass
  );

const body = <Message>(
  options: CommonOptions<Message>,
  h: HtmlBuilder<Message>
) => [
  ...(options.icon === undefined
    ? []
    : [
        icon(options.icon, { class: iconSizeClasses[options.size ?? "md"] }, h),
      ]),
  h.span([h.Class("btn-label")], [options.text]),
];

export const button = <Message>(
  options: ButtonOptions<Message>,
  h: HtmlBuilder<Message>
) =>
  h.button(
    [
      h.Type(options.type ?? "submit"),
      h.Class(classes(options, true)),
      ...(options.disabled === true ? [h.Disabled(true)] : []),
      ...(options.attributes ?? []),
    ],
    body(options, h)
  );

export const linkButton = <Message>(
  options: LinkButtonOptions<Message>,
  h: HtmlBuilder<Message>
) =>
  h.a(
    [
      ...(options.disabled === true
        ? [h.AriaDisabled(true), h.Tabindex(-1)]
        : [h.Href(options.href)]),
      h.Class(classes(options, false)),
      ...(options.attributes ?? []),
    ],
    body(options, h)
  );

export const iconButton = <Message>(
  options: Readonly<{
    attributes?: readonly Attribute<Message>[];
    icon: IconData;
    iconClass?: string;
    label: string;
    tone?: "clear" | "danger" | "default" | "primary";
  }>,
  h: HtmlBuilder<Message>
) =>
  h.button(
    [
      h.Type("button"),
      h.Class(
        cx(
          "icon-btn",
          options.tone === "clear" && "icon-btn-clear",
          options.tone === "danger" && "icon-btn-danger",
          options.tone === "primary" && "icon-btn-primary"
        )
      ),
      ...(options.attributes ?? []),
    ],
    [
      icon(options.icon, { class: options.iconClass ?? "w-4 h-4" }, h),
      h.span([h.Class("sr-only")], [options.label]),
    ]
  );
