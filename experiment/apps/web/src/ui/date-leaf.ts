import type { HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";
import type { DateLeaf } from "./i18n.js";

export { DateLeaf } from "./i18n.js";

export const dateLeaf = <Message>(leaf: DateLeaf, h: HtmlBuilder<Message>) =>
  h.time(
    [
      h.Datetime(leaf.datetime),
      h.Class(
        "relative flex w-[58px] flex-col items-center overflow-hidden rounded-[7px] bg-bg-secondary text-center leading-none tabular-nums text-foreground shadow-[0_3px_10px_rgb(60_40_20/.10),0_1px_2px_rgb(60_40_20/.08)] ring-1 ring-black/8 dark:bg-bg-tertiary dark:shadow-[0_6px_16px_rgb(0_0_0/.32)] dark:ring-white/8"
      ),
    ],
    [
      h.span([h.Class("sr-only")], [leaf.label]),
      h.span(
        [
          h.AriaHidden(true),
          h.Class(
            cx(
              "self-stretch whitespace-nowrap bg-coral-600 pt-1 font-bold uppercase text-white dark:bg-coral-700",
              leaf.bandIsLong
                ? "pb-1 text-[9px] tracking-[.02em]"
                : "pb-[3px] text-[10px] tracking-[.12em]"
            )
          ),
        ],
        [leaf.band]
      ),
      h.span(
        [
          h.AriaHidden(true),
          h.Class(
            cx(
              "whitespace-nowrap font-bold",
              leaf.isRange
                ? "pt-2 pb-px text-base tracking-[-.045em]"
                : "pt-1.5 text-[26px] tracking-[-.02em]",
              leaf.isSunday && "text-coral-700 dark:text-coral-400"
            )
          ),
        ],
        [leaf.day]
      ),
      h.span(
        [
          h.AriaHidden(true),
          h.Class(
            cx(
              "mt-[3px] whitespace-nowrap font-semibold uppercase",
              leaf.isRange ? "text-[9px]" : "text-[10px] tracking-[.06em]",
              leaf.isToday
                ? "text-coral-700 dark:text-coral-300"
                : "text-foreground-muted"
            )
          ),
        ],
        [leaf.weekday]
      ),
      h.span(
        [
          h.AriaHidden(true),
          h.Class(
            cx(
              "mt-[7px] self-stretch whitespace-nowrap border-t border-dashed border-warm-300 pt-[5px] pb-1.5 text-xs font-semibold dark:border-neutral-600",
              leaf.isOngoing && "text-coral-700 dark:text-coral-300"
            )
          ),
        ],
        [leaf.hour]
      ),
    ]
  );
