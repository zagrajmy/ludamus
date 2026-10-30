import { Option, Schema } from "effect";
import type { HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";
import type { Translator } from "./i18n.js";
import { icon } from "./icon.js";
import { exclamationTriangleMini } from "./icons.js";

export const AvatarPerson = Schema.Struct({
  avatarUrl: Schema.OptionFromOptional(Schema.String),
  name: Schema.String,
});
export type AvatarPerson = typeof AvatarPerson.Type;

const palette = (name: string) => {
  const length = [...name].length;

  if (length % 4 === 0) {
    return { background: "bg-coral-400", text: "text-neutral-900" };
  }

  if (length % 3 === 0) {
    return { background: "bg-teal-400", text: "text-neutral-900" };
  }

  if (length % 2 === 0) {
    return { background: "bg-teal-500", text: "text-neutral-900" };
  }

  return {
    background: "bg-warm-400 dark:bg-warm-800",
    text: "text-neutral-900 dark:text-neutral-50",
  };
};

export const avatar = <Message>(
  options: Readonly<{
    flagged?: boolean;
    person: AvatarPerson;
    size?: string;
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
) => {
  const { name } = options.person;
  const flagged = options.flagged === true;

  if (name === "" && Option.isNone(options.person.avatarUrl) && !flagged) {
    return h.empty;
  }

  const colors = palette(name);

  return h.div(
    [
      h.Class(cx(options.size ?? "size-8", "shrink-0 relative")),
      h.Role("img"),
      h.DataAttribute("ph-block", ""),
      h.AriaLabel(
        flagged
          ? options.translator.t("%(name_value)s (flagged)", {
              name_value: name,
            })
          : name
      ),
    ],
    [
      h.div(
        [
          h.Class(
            cx(
              "absolute inset-0 border border-white/80 dark:border-neutral-900",
              flagged && "ring-2 ring-danger",
              "rounded-full overflow-hidden"
            )
          ),
        ],
        [
          h.div(
            [
              h.Class(
                cx(
                  "absolute inset-0",
                  colors.background,
                  "flex items-center justify-center"
                )
              ),
              h.AriaHidden(true),
            ],
            [
              h.span(
                [
                  h.Class(cx("text-xs font-semibold", colors.text)),
                  h.DataAttribute("ph-mask", ""),
                ],
                [[...name].slice(0, 2).join("").toUpperCase()]
              ),
            ]
          ),
          Option.match(options.person.avatarUrl, {
            onNone: () => h.empty,
            onSome: (src) =>
              h.img([
                h.Src(src),
                h.Alt(""),
                h.Width("32"),
                h.Height("32"),
                h.Class("absolute inset-0 h-full w-full object-cover"),
                h.Loading("lazy"),
                h.DataAttribute("avatar-image", ""),
                h.Attribute("onerror", "this.hidden=true"),
              ]),
          }),
        ]
      ),
      flagged
        ? h.span(
            [
              h.Class(
                "absolute -bottom-[5px] -right-[5px] z-10 rounded-full bg-danger p-0.5 ring-2 ring-white dark:ring-neutral-900"
              ),
              h.AriaHidden(true),
            ],
            [icon(exclamationTriangleMini, { class: "size-2.5 text-white" }, h)]
          )
        : h.empty,
    ]
  );
};
