import type { HtmlBuilder } from "foldkit/html";

import type { Translator } from "./i18n.js";
import { linkedText } from "./rich-text.js";
import { themeSwitcher } from "./theme-switcher.js";
import type { ThemeChoice } from "./theme-switcher.js";

export const sourceUrl = "https://github.com/zagrajmy/ludamus";

export const licenseUrl =
  "https://github.com/zagrajmy/ludamus/blob/main/LICENSE";

export type FooterOptions<Message> = Readonly<{
  aboutHref: string;
  brandHref: string;
  onChangeTheme: (theme: ThemeChoice) => Message;
  supportEmail: string;
  theme: ThemeChoice;
  translator: Translator;
  year: number;
}>;

const licenseNotice = <Message>(
  translator: Translator,
  h: HtmlBuilder<Message>
) =>
  linkedText(
    translator.t(
      '<a href="%(source_url)s">Source code</a> available under&nbsp;<a href="%(license_url)s">AGPL-3.0</a>.',
      { license_url: licenseUrl, source_url: sourceUrl }
    ),
    h
  );

export const footer = <Message>(
  options: FooterOptions<Message>,
  h: HtmlBuilder<Message>
) => {
  const { translator } = options;

  return h.footer(
    [h.Class("border-t py-6 bg-bg-secondary border-border print:hidden")],
    [
      h.div(
        [
          h.Class(
            "max-w-7xl mx-auto px-4 md:px-6 lg:px-8 panel:max-w-none lg:panel:px-4"
          ),
        ],
        [
          h.div(
            [h.Class("flex justify-end items-center gap-2 mb-4")],
            [
              themeSwitcher(
                {
                  current: options.theme,
                  onChange: options.onChangeTheme,
                  translator,
                },
                h
              ),
            ]
          ),
          h.div(
            [
              h.Class(
                "flex flex-col sm:flex-row justify-between sm:items-center gap-4 text-sm text-foreground-secondary [&_a]:underline [&_a]:decoration-foreground-muted/50 [&_a:hover]:text-primary [&_a:hover]:decoration-primary/50"
              ),
            ],
            [
              h.p(
                [h.Class("text-pretty")],
                [
                  `© 2025–${options.year} `,
                  h.a([h.Href("https://fancysnake.dev/")], ["fancysnake"]),
                  " & ",
                  h.a([h.Href("https://haspar.us/")], ["hasparus"]),
                  ". ",
                  h.br([h.Class("sm:hidden")]),
                  ...licenseNotice(translator, h),
                ]
              ),
              h.div(
                [
                  h.Class(
                    "flex flex-col items-start sm:flex-row sm:flex-wrap sm:justify-end gap-x-4 gap-y-2"
                  ),
                ],
                [
                  h.a(
                    [h.Href(options.aboutHref)],
                    [translator.t("About Zagrajmy")]
                  ),
                  h.a([h.Href(options.brandHref)], [translator.t("Brand")]),
                  h.a(
                    [h.Href(`mailto:${options.supportEmail}`)],
                    [translator.t("Contact")]
                  ),
                  h.a(
                    [h.Href("/privacy-policy/")],
                    [translator.t("Privacy Policy")]
                  ),
                  h.a(
                    [h.Href("/terms-of-service/")],
                    [translator.t("Terms of Service")]
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
