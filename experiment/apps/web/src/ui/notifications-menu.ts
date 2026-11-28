import type { NavbarNotifications } from "@zagrajmy/core/notification";
import type { HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";
import type { Translator } from "./i18n.js";
import { icon } from "./icon.js";
import { bellOutline } from "./icons.js";
import { disclosureMenu, menuSurface } from "./menu.js";

export const NOTIFICATIONS_PATH = "/notifications/";

export const notificationOpenPath = (id: number) =>
  `/notifications/${id}/do/open`;

export const notificationsMenu = <Message>(
  options: Readonly<{
    isOpen: boolean;
    notifications: NavbarNotifications;
    onToggle: (isOpen: boolean) => Message;
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
) => {
  const { t } = options.translator;
  const { items, unreadCount } = options.notifications;

  return disclosureMenu(
    {
      id: "navbar-notifications-panel",
      isOpen: options.isOpen,
      onToggle: options.onToggle,
      panel: (isOpen) =>
        menuSurface(
          {
            children: [
              h.div(
                [
                  h.Class(
                    "px-3.5 py-2.5 border-b rounded-t-lg border-border flex items-center justify-between gap-2"
                  ),
                ],
                [
                  h.p(
                    [
                      h.Class(
                        "text-sm font-medium text-foreground-primary mb-0"
                      ),
                    ],
                    [t("Notifications")]
                  ),
                ]
              ),
              ...(items.length === 0
                ? [
                    h.p(
                      [
                        h.Class(
                          "px-3.5 py-4 text-sm text-foreground-secondary mb-0"
                        ),
                      ],
                      [t("No notifications yet.")]
                    ),
                  ]
                : items.map((item) =>
                    h.a(
                      [
                        h.Key(String(item.id)),
                        h.Href(notificationOpenPath(item.id)),
                        h.Class(
                          cx(
                            "block px-3.5 py-3 text-sm border-b last:border-b-0 transition-colors duration-150 hover:bg-bg-tertiary border-border",
                            !item.isRead && "bg-bg-tertiary/40"
                          )
                        ),
                      ],
                      [
                        h.span(
                          [
                            h.Class(
                              "block font-medium text-foreground-primary"
                            ),
                          ],
                          [item.title]
                        ),
                        ...(item.body === ""
                          ? []
                          : [
                              h.span(
                                [
                                  h.Class(
                                    "block text-xs mt-0.5 text-foreground-secondary line-clamp-2"
                                  ),
                                ],
                                [item.body]
                              ),
                            ]),
                      ]
                    )
                  )),
              h.a(
                [
                  h.Href(NOTIFICATIONS_PATH),
                  h.Class(
                    "block px-3.5 py-2.5 text-sm text-center rounded-b-lg font-medium transition-colors duration-150 text-foreground-secondary hover:text-foreground-primary hover:bg-bg-tertiary"
                  ),
                ],
                [t("View all")]
              ),
            ],
            extraClass:
              "w-72 rounded-lg shadow-lg border bg-bg-secondary border-border shadow-(--shadow-elevated)",
            isOpen,
          },
          h
        ),
      panelClass: "absolute right-0 top-full mt-2 z-50",
      trigger: [
        icon(bellOutline, { class: "w-5 h-5" }, h),
        ...(unreadCount === 0
          ? []
          : [
              h.span(
                [
                  h.Class(
                    "absolute -top-1 -right-1 min-w-5 h-5 px-1 rounded-full bg-coral-500 text-white text-xs font-semibold flex items-center justify-center"
                  ),
                ],
                [unreadCount > 99 ? "99+" : String(unreadCount)]
              ),
            ]),
      ],
      triggerClass:
        "relative w-9 h-9 rounded-full flex items-center justify-center cursor-pointer transition-colors duration-150 hover:bg-bg-tertiary focus:outline-none focus-visible:bg-bg-tertiary text-foreground-secondary hover:text-foreground-primary",
      triggerLabel:
        unreadCount === 0
          ? t("Notifications")
          : `${t("Notifications")} (${unreadCount} ${t("unread")})`,
    },
    h
  );
};
