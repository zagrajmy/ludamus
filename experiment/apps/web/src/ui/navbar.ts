import { Option } from "effect";
import type { HtmlBuilder } from "foldkit/html";

import { avatar } from "./avatar.js";
import { logoLockup, logoMark } from "./brand.js";
import { cx } from "./cx.js";
import type { Translator } from "./i18n.js";
import { icon } from "./icon.js";
import type { IconData } from "./icon.js";
import {
  arrowRightOnRectangleOutline,
  homeOutline,
  megaphoneOutline,
  squares2x2Outline,
  userCircleOutline,
} from "./icons.js";
import { disclosureMenu, menuSurface } from "./menu.js";

export type NavbarViewer = Readonly<{
  avatarUrl: Option.Option<string>;
  email: string;
  name: string;
}>;

export type NavbarLinks = Readonly<{
  board: Option.Option<string>;
  dashboard: string;
  home: string;
  login: string;
  logout: string;
  panel: Option.Option<string>;
  profile: string;
  sphere: string;
}>;

export type NavbarOptions<Message> = Readonly<{
  isMenuOpen: boolean;
  isRootSphere: boolean;
  links: NavbarLinks;
  onToggleMenu: (isOpen: boolean) => Message;
  sphereLogoUrl: Option.Option<string>;
  sphereName: string;
  translator: Translator;
  viewer: Option.Option<NavbarViewer>;
}>;

const menuItemClass =
  "flex items-center gap-1.5 px-3.5 py-2.75 text-sm transition-colors duration-150 hover:bg-bg-tertiary text-foreground-secondary";

const menuItem = <Message>(
  options: Readonly<{
    extraClass?: string;
    href: string;
    icon: IconData;
    label: string;
  }>,
  h: HtmlBuilder<Message>
) =>
  h.a(
    [
      h.Key(options.href),
      h.Href(options.href),
      h.Class(cx(menuItemClass, options.extraClass)),
    ],
    [icon(options.icon, { class: "w-4 h-4 opacity-60" }, h), options.label]
  );

const accountMenu = <Message>(
  options: NavbarOptions<Message> & Readonly<{ signedIn: NavbarViewer }>,
  h: HtmlBuilder<Message>
) => {
  const { links, signedIn: viewer, translator } = options;
  const displayName = viewer.name === "" ? translator.t("User") : viewer.name;

  return disclosureMenu(
    {
      hover: true,
      id: "navbar-profile-panel",
      isOpen: options.isMenuOpen,
      onToggle: options.onToggleMenu,
      panel: (isOpen) =>
        h.div(
          [],
          [
            h.span(
              [
                h.AriaHidden(true),
                h.Class(
                  "absolute right-0 -top-2 block h-2 w-48 pointer-events-auto [clip-path:polygon(81.25%_0,100%_0,100%_100%,0_100%)]"
                ),
              ],
              []
            ),
            menuSurface(
              {
                children: [
                  h.div(
                    [
                      h.Class(
                        "px-3.5 py-2.5 border-b rounded-t-lg border-border"
                      ),
                    ],
                    [
                      h.p(
                        [
                          h.Class(
                            "text-sm font-medium truncate text-foreground-primary"
                          ),
                          h.DataAttribute("ph-block", ""),
                          h.Title(displayName),
                        ],
                        [displayName]
                      ),
                      h.p(
                        [
                          h.Class(
                            "text-xs truncate mt-0.5 text-foreground-secondary"
                          ),
                          h.DataAttribute("ph-block", ""),
                          h.Title(viewer.email),
                        ],
                        [viewer.email]
                      ),
                    ]
                  ),
                  Option.match(links.panel, {
                    onNone: () => h.empty,
                    onSome: (href) =>
                      menuItem(
                        {
                          href,
                          icon: squares2x2Outline,
                          label: translator.t("Panel"),
                        },
                        h
                      ),
                  }),
                  menuItem(
                    {
                      href: links.dashboard,
                      icon: homeOutline,
                      label: translator.t("Your dashboard"),
                    },
                    h
                  ),
                  Option.match(links.board, {
                    onNone: () => h.empty,
                    onSome: (href) =>
                      menuItem(
                        {
                          href,
                          icon: megaphoneOutline,
                          label: translator.t("Board"),
                        },
                        h
                      ),
                  }),
                  menuItem(
                    {
                      href: links.profile,
                      icon: userCircleOutline,
                      label: translator.t("Edit profile"),
                    },
                    h
                  ),
                  menuItem(
                    {
                      extraClass: "border-t rounded-b-lg border-border",
                      href: links.logout,
                      icon: arrowRightOnRectangleOutline,
                      label: translator.t("Log out"),
                    },
                    h
                  ),
                ],
                extraClass:
                  "w-48 rounded-lg shadow-lg border bg-bg-secondary border-border shadow-(--shadow-elevated)",
                isOpen,
              },
              h
            ),
          ]
        ),
      panelClass: "absolute right-0 top-full mt-2 z-50",
      trigger: [
        avatar(
          {
            person: { avatarUrl: viewer.avatarUrl, name: viewer.name },
            size: "size-10",
            translator,
          },
          h
        ),
      ],
      triggerClass:
        "relative w-9 h-9 rounded-full bg-neutral-800 flex items-center justify-center cursor-pointer transition-shadow duration-150 ring-2 ring-transparent hover:ring-coral-500/30 focus:outline-none focus:ring-coral-500/50 before:absolute before:-inset-1 before:content-['']",
      triggerLabel: translator.t("Account menu"),
    },
    h
  );
};

export const navbar = <Message>(
  options: NavbarOptions<Message>,
  h: HtmlBuilder<Message>
) => {
  const { links, translator } = options;
  const hasLogo = Option.isSome(options.sphereLogoUrl);

  return h.nav(
    [
      h.Class(
        "sticky top-0 z-50 border-b bg-bg-secondary border-border panel:static print:hidden"
      ),
    ],
    [
      h.div(
        [
          h.Class(
            "max-w-7xl mx-auto px-4 md:px-6 lg:px-8 panel:max-w-none lg:panel:px-4"
          ),
        ],
        [
          h.div(
            [h.Class("flex justify-between h-14")],
            [
              h.div(
                [h.Class("flex items-center gap-6")],
                [
                  h.div(
                    [
                      h.Class(
                        "flex items-center gap-1 text-neutral-800 dark:text-neutral-200"
                      ),
                    ],
                    [
                      h.a(
                        [
                          h.Href(links.home),
                          h.Class("flex items-center gap-1"),
                          h.DataAttribute("brand-hover", "tuck-in"),
                        ],
                        [
                          logoMark("size-6 sm:hidden w-auto", h),
                          h.span([h.Class("sr-only sm:hidden")], ["zagrajmy"]),
                          logoLockup(
                            { extraClass: "hidden sm:block h-8 w-auto" },
                            h
                          ),
                        ]
                      ),
                      options.isRootSphere
                        ? h.empty
                        : h.a(
                            [
                              h.Href(links.sphere),
                              h.Class(
                                "flex items-center gap-2 text-xl font-semibold tracking-tight"
                              ),
                            ],
                            [
                              h.span(
                                [
                                  h.Class("text-foreground-muted"),
                                  h.AriaHidden(true),
                                ],
                                ["/"]
                              ),
                              Option.match(options.sphereLogoUrl, {
                                onNone: () => h.empty,
                                onSome: (src) =>
                                  h.img([
                                    h.Src(src),
                                    h.Alt(""),
                                    h.Width("24"),
                                    h.Height("24"),
                                    h.Class(
                                      "h-6 w-[35px] rounded object-contain"
                                    ),
                                  ]),
                              }),
                              h.span(
                                [h.Class(cx(hasLogo && "max-sm:hidden"))],
                                [options.sphereName]
                              ),
                            ]
                          ),
                    ]
                  ),
                ]
              ),
              h.div(
                [h.Class("flex items-center gap-2 -translate-y-px")],
                [
                  Option.match(options.viewer, {
                    onNone: () =>
                      h.span(
                        [h.Class("inline-flex -translate-y-[.5px]")],
                        [
                          h.a(
                            [
                              h.Href(links.login),
                              h.Class("btn btn-primary text-sm"),
                            ],
                            [translator.t("Log in")]
                          ),
                        ]
                      ),
                    onSome: (viewer) =>
                      accountMenu({ ...options, signedIn: viewer }, h),
                  }),
                ]
              ),
            ]
          ),
        ]
      ),
    ]
  );
};
