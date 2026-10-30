import * as Dialog from "@foldkit/ui/dialog";
import type { Html, HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";
import type { Child } from "./html.js";
import type { Translator } from "./i18n.js";
import { icon } from "./icon.js";
import { exclamationTriangleOutline, xMarkMini } from "./icons.js";

export { Dialog };

export type ModalOptions<Message> = Readonly<{
  body: readonly Child[];
  footer?: readonly Child[];
  model: Dialog.Model;
  panelClass?: string;
  title: string;
  toParentMessage: (message: Dialog.Message) => Message;
  translator: Translator;
}>;

const frame = <Message>(
  options: Readonly<{
    content: (render: Dialog.RenderInfo) => readonly Child[];
    hasDescription?: boolean;
    model: Dialog.Model;
    panelClass?: string;
    role?: "alertdialog" | "dialog";
    toParentMessage: (message: Dialog.Message) => Message;
  }>,
  h: HtmlBuilder<Message>
): Html =>
  h.submodel({
    model: options.model,
    slotId: options.model.id,
    toParentMessage: options.toParentMessage,
    view: Dialog.view,
    viewInputs: {
      hasDescription: options.hasDescription ?? false,
      toView: (render) =>
        h.dialog(
          [...render.dialog, h.Role(options.role ?? "dialog")],
          render.isVisible
            ? [
                h.div(
                  [
                    ...render.backdrop,
                    h.Class("fixed inset-0 bg-black/40 backdrop-blur-[4px]"),
                  ],
                  []
                ),
                h.div(
                  [
                    h.Class(
                      "pointer-events-none fixed inset-0 flex items-center justify-center p-4"
                    ),
                  ],
                  [
                    h.div(
                      [
                        ...render.panel,
                        h.Class(
                          cx(
                            "pointer-events-auto flex w-[calc(100%-2rem)] max-w-md flex-col rounded-2xl border border-border bg-bg-secondary shadow-lg",
                            options.panelClass
                          )
                        ),
                      ],
                      options.content(render)
                    ),
                  ]
                ),
              ]
            : []
        ),
    },
  });

export const modal = <Message>(
  options: ModalOptions<Message>,
  h: HtmlBuilder<Message>
) =>
  frame(
    {
      content: (render) => [
        h.div(
          [
            h.Class(
              "px-6 py-4 border-b border-border flex items-center justify-between shrink-0"
            ),
          ],
          [
            h.h3(
              [
                ...render.title,
                h.Class("text-lg font-semibold text-foreground"),
              ],
              [options.title]
            ),
            h.button(
              [
                ...render.closeButton,
                h.AriaLabel(options.translator.t("Close")),
                h.Class(
                  "size-11 flex items-center justify-center rounded-lg hover:bg-warm-200 dark:hover:bg-neutral-700 text-foreground-muted"
                ),
              ],
              [icon(xMarkMini, { class: "w-5 h-5" }, h)]
            ),
          ]
        ),
        h.div(
          [
            ...render.initialFocus,
            h.Class("flex-auto min-h-0 px-6 py-4"),
            h.Tabindex(-1),
          ],
          options.body
        ),
        options.footer === undefined
          ? h.empty
          : h.div(
              [
                h.Class(
                  "modal-footer flex justify-end gap-2 border-t border-border px-6 pt-3"
                ),
              ],
              options.footer
            ),
      ],
      model: options.model,
      ...(options.panelClass === undefined
        ? {}
        : { panelClass: options.panelClass }),
      toParentMessage: options.toParentMessage,
    },
    h
  );

export const confirmDialog = <Message>(
  options: Readonly<{
    confirmLabel?: string;
    message: string;
    model: Dialog.Model;
    onConfirm: Message;
    title?: string;
    toParentMessage: (message: Dialog.Message) => Message;
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
) =>
  frame(
    {
      content: (render) => [
        h.div(
          [h.Class("flex items-start gap-3 px-6 py-4")],
          [
            h.span(
              [h.Class("mt-0.5 flex-shrink-0 text-danger")],
              [icon(exclamationTriangleOutline, { class: "w-6 h-6" }, h)]
            ),
            h.div(
              [],
              [
                h.h3(
                  [...render.title, h.Class("font-semibold text-foreground")],
                  [options.title ?? options.translator.t("Please confirm")]
                ),
                h.p(
                  [
                    ...render.description,
                    h.Class(
                      "mt-1 text-sm text-foreground-secondary whitespace-pre-line text-pretty"
                    ),
                  ],
                  [options.message]
                ),
              ]
            ),
          ]
        ),
        h.div(
          [h.Class("modal-footer-lg flex justify-end gap-2 px-6")],
          [
            h.button(
              [
                ...render.closeButton,
                ...render.initialFocus,
                h.Class("btn btn-secondary"),
              ],
              [options.translator.t("Cancel")]
            ),
            h.button(
              [
                h.Type("button"),
                h.Class("btn btn-danger"),
                h.OnClick(options.onConfirm),
              ],
              [options.confirmLabel ?? options.translator.t("Confirm")]
            ),
          ]
        ),
      ],
      hasDescription: true,
      model: options.model,
      role: "alertdialog",
      toParentMessage: options.toParentMessage,
    },
    h
  );
