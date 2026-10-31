import type { Html, HtmlBuilder } from "foldkit/html";

import { ShellMessage } from "../../client/shell/message.js";
import type { ShellModel } from "../../client/shell/model.js";
import { consentBanner } from "../../ui/consent-banner.js";
import { cx } from "../../ui/cx.js";
import { flashMessages } from "../../ui/flash.js";
import { footer } from "../../ui/footer.js";
import type { Child } from "../../ui/html.js";
import type { Translator } from "../../ui/i18n.js";
import { navbar } from "../../ui/navbar.js";

export type PageLayout = "bleed" | "contained" | "panel";

export type PageBody = Readonly<{
  content: readonly Child[];
  layout: PageLayout;
}>;

export const mainContentId = "main-content";

const mainClasses: Readonly<Record<Exclude<PageLayout, "panel">, string>> = {
  bleed: "grow flex flex-col w-full mb-8",
  contained:
    "grow flex flex-col max-w-7xl mx-auto px-4 md:px-6 lg:px-8 py-6 w-full mb-8",
};

export const shellView = <Message>(
  options: Readonly<{
    body: PageBody;
    shell: ShellModel;
    toMessage: (message: ShellMessage) => Message;
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
): Html => {
  const { shell, toMessage, translator } = options;
  const { layout } = options.body;
  const isPanel = layout === "panel";

  return h.div(
    [
      h.Class(
        isPanel
          ? "panel-shell app-shell relative font-sans antialiased bg-background text-foreground"
          : "app-shell font-sans antialiased bg-background text-foreground print:bg-white"
      ),
    ],
    [
      h.div(
        [h.Id("app-scroll"), h.Class("app-scroll relative")],
        [
          h.a(
            [
              h.Href(`#${mainContentId}`),
              h.Class(
                "sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[70] focus:rounded-lg focus:bg-bg-secondary focus:px-4 focus:py-2 focus:shadow-lg"
              ),
            ],
            [translator.t("Skip to main content")]
          ),
          navbar(
            {
              isMenuOpen: shell.isAccountMenuOpen,
              isNotificationsOpen: shell.isNotificationsOpen,
              notifications: shell.notifications,
              onToggleNotifications: (isOpen) =>
                toMessage(ShellMessage.ToggledNotificationsMenu({ isOpen })),
              isRootSphere: shell.isRootSphere,
              links: shell.links,
              onToggleMenu: (isOpen) =>
                toMessage(ShellMessage.ToggledAccountMenu({ isOpen })),
              sphereLogoUrl: shell.sphere.logoUrl,
              sphereName: shell.sphere.name,
              translator,
              viewer: shell.viewer,
            },
            h
          ),
          ...(layout === "panel"
            ? options.body.content
            : [
                flashMessages(
                  {
                    flashes: shell.flashes,
                    onDismiss: (id) =>
                      toMessage(ShellMessage.DismissedFlash({ id })),
                    translator,
                  },
                  h
                ),
                h.main(
                  [
                    h.Id(mainContentId),
                    h.Tabindex(-1),
                    h.Class(cx(mainClasses[layout], "outline-none")),
                  ],
                  options.body.content
                ),
              ]),
          footer(
            {
              aboutHref: shell.links.about,
              brandHref: shell.links.brand,
              onChangeTheme: (theme) =>
                toMessage(ShellMessage.ChangedTheme({ theme })),
              supportEmail: shell.supportEmail,
              theme: shell.theme,
              translator,
              year: shell.year,
            },
            h
          ),
          consentBanner(
            {
              isAnswered: shell.isConsentAnswered,
              isEnabled: shell.analyticsEnabled,
              onChoose: (choice) =>
                toMessage(ShellMessage.ChoseConsent({ choice })),
              translator,
            },
            h
          ),
        ]
      ),
    ]
  );
};
