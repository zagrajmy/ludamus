import type { HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";
import { dateLeaf } from "./date-leaf.js";
import type { DateLeaf } from "./date-leaf.js";

export const coverTint = <Message>(
  options: Readonly<{ extraClass?: string; url: string }>,
  h: HtmlBuilder<Message>
) =>
  h.div(
    [
      h.Class(
        cx(
          "mx-1 mt-1 rounded-xl bg-cover bg-center [--bg-tint:transparent] dark:[--bg-tint:hsl(0_0_15%/.15)]",
          options.extraClass
        )
      ),
      h.Style({
        "background-image": `linear-gradient(to bottom, var(--bg-tint), var(--bg-tint)), url('${options.url.replaceAll("'", "%27")}')`,
      }),
    ],
    []
  );

export const coverStrip = <Message>(
  options: Readonly<{ extraClass?: string; url: string }>,
  h: HtmlBuilder<Message>
) =>
  h.img([
    h.Src(options.url),
    h.Alt(""),
    h.Width("640"),
    h.Height("360"),
    h.Class(
      cx(
        "mx-1 mt-1 h-40 w-[calc(100%-0.5rem)] rounded-xl object-cover",
        options.extraClass
      )
    ),
  ]);

export const feedCover = <Message>(
  options: Readonly<{ leaf: DateLeaf; url: string }>,
  h: HtmlBuilder<Message>
) =>
  h.div(
    [h.Class("relative")],
    [
      coverTint({ extraClass: "aspect-[2/1]", url: options.url }, h),
      h.div(
        [h.Class("absolute left-4 -bottom-7 z-10")],
        [dateLeaf(options.leaf, h)]
      ),
    ]
  );
