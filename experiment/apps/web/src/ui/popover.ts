import type { HtmlBuilder } from "foldkit/html";

import { icon } from "./icon.js";
import { informationCircleOutline } from "./icons.js";

export const infoPopover = <Message>(
  options: Readonly<{ body: string; title: string }>,
  h: HtmlBuilder<Message>
) =>
  h.details(
    [h.DataAttribute("info-popover", ""), h.Class("relative flex")],
    [
      h.summary(
        [
          h.Class(
            "list-none cursor-pointer text-foreground-muted/70 hover:text-foreground-muted inline-flex p-1 -m-1 rounded-md focus-visible:outline-2 focus-visible:outline-primary"
          ),
          h.AriaLabel(options.title),
          h.Title(options.title),
        ],
        [icon(informationCircleOutline, { class: "w-5 h-5" }, h)]
      ),
      h.div(
        [h.Class("absolute left-0 top-full w-80 z-30 pt-2")],
        [
          h.div(
            [h.Class("card p-4 shadow-lg")],
            [
              h.p(
                [h.Class("text-sm font-medium text-foreground")],
                [options.title]
              ),
              h.p(
                [h.Class("text-sm mt-1 text-foreground-secondary")],
                [options.body]
              ),
            ]
          ),
        ]
      ),
    ]
  );
