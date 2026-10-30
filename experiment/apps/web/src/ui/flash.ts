import { Schema } from "effect";
import type { HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";
import type { Translator } from "./i18n.js";
import { icon } from "./icon.js";
import {
  checkCircleOutline,
  exclamationTriangleOutline,
  informationCircleOutline,
  xMarkOutline,
} from "./icons.js";

export const FlashLevel = Schema.Literals([
  "error",
  "info",
  "success",
  "warning",
]);

export type FlashLevel = typeof FlashLevel.Type;

export const Flash = Schema.Struct({
  id: Schema.String,
  level: FlashLevel,
  text: Schema.String,
});

export type Flash = typeof Flash.Type;

const isSticky = (level: FlashLevel) =>
  level === "error" || level === "warning";

const tone: Readonly<Record<FlashLevel, string>> = {
  error: "alert-danger",
  info: "alert-info",
  success: "alert-success",
  warning: "alert-warning",
};

export const flashMessages = <Message>(
  options: Readonly<{
    flashes: readonly Flash[];
    onDismiss: (id: string) => Message;
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
) =>
  options.flashes.length === 0
    ? h.empty
    : h.div(
        [
          h.Class("flash-region"),
          h.Role("region"),
          h.AriaLive("polite"),
          h.AriaLabel(options.translator.t("Notifications")),
        ],
        options.flashes.map((flash) =>
          h.div(
            [
              h.Key(flash.id),
              h.Class(
                cx(
                  "alert backdrop-blur-lg flex items-center",
                  tone[flash.level]
                )
              ),
              h.DataAttribute(
                "flash",
                isSticky(flash.level) ? "sticky" : "transient"
              ),
              h.DataAttribute("flash-mounted", "true"),
              h.Role(isSticky(flash.level) ? "alert" : "status"),
              h.AriaLive(isSticky(flash.level) ? "assertive" : "polite"),
            ],
            [
              icon(
                isSticky(flash.level)
                  ? exclamationTriangleOutline
                  : flash.level === "success"
                    ? checkCircleOutline
                    : informationCircleOutline,
                { class: "w-5 h-5 mr-3 shrink-0" },
                h
              ),
              h.span([h.Class("text-sm")], [flash.text]),
              h.button(
                [
                  h.Type("button"),
                  h.DataAttribute("flash-dismiss", ""),
                  h.Class(
                    "ml-auto pl-3 shrink-0 opacity-70 hover:opacity-100 transition-opacity cursor-pointer"
                  ),
                  h.AriaLabel(options.translator.t("Dismiss")),
                  h.OnClick(options.onDismiss(flash.id)),
                ],
                [icon(xMarkOutline, { class: "w-4 h-4" }, h)]
              ),
            ]
          )
        )
      );
