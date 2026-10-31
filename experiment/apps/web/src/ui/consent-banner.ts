import type { HtmlBuilder } from "foldkit/html";

import { button } from "./button.js";
import type { Translator } from "./i18n.js";

export const consentStorageKey = "prologue.consent";

export type ConsentChoice = "accepted" | "declined";

export const consentBanner = <Message>(
  options: Readonly<{
    isAnswered: boolean;
    isEnabled: boolean;
    onChoose: (choice: ConsentChoice) => Message;
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
) => {
  if (!options.isEnabled || options.isAnswered) {
    return h.empty;
  }

  const { translator } = options;

  return h.div(
    [h.Class("sticky bottom-0 z-40 h-0 shrink-0")],
    [
      h.section(
        [
          h.Id("consent-banner"),
          h.Class(
            "consent-banner absolute bottom-3 left-3 right-3 sm:bottom-4 sm:left-4 sm:right-auto sm:max-w-sm rounded-2xl border border-border bg-bg-secondary/95 backdrop-blur-lg shadow-lg"
          ),
          h.AriaLabel(translator.t("Cookie consent")),
        ],
        [
          h.div(
            [h.Class("p-4 flex flex-col gap-3")],
            [
              h.div(
                [h.Class("flex items-start gap-2.5")],
                [
                  h.span(
                    [
                      h.Class(
                        "text-xl leading-none translate-y-[-.25px] shrink-0"
                      ),
                      h.AriaHidden(true),
                    ],
                    ["🍪"]
                  ),
                  h.p(
                    [
                      h.Class(
                        "text-sm text-foreground-secondary [&_a]:text-primary [&_a]:hover:underline text-balance"
                      ),
                    ],
                    [
                      translator.t(
                        "Cookies and session recordings help us see what to fix."
                      ),
                      " ",
                      h.a(
                        [h.Href("/privacy-policy/")],
                        [translator.t("Privacy Policy")]
                      ),
                    ]
                  ),
                ]
              ),
              h.div(
                [h.Class("flex flex-row justify-end gap-2")],
                [
                  button(
                    {
                      attributes: [
                        h.DataAttribute("consent-choice", "declined"),
                        h.OnClick(options.onChoose("declined")),
                      ],
                      fullWidthMobile: false,
                      text: translator.t("No cookies!"),
                      type: "button",
                      variant: "secondary",
                    },
                    h
                  ),
                  button(
                    {
                      attributes: [
                        h.DataAttribute("consent-choice", "accepted"),
                        h.OnClick(options.onChoose("accepted")),
                      ],
                      fullWidthMobile: false,
                      text: translator.t("Cool"),
                      type: "button",
                    },
                    h
                  ),
                ]
              ),
            ]
          ),
        ]
      ),
    ]
  );
};
