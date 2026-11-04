import { Option } from "effect";
import type { Html, HtmlBuilder } from "foldkit/html";

import type {
  PanelCategory,
  PanelChromeModel,
  PanelNav,
} from "../../client/panel/chrome.js";
import { eventIndexPath, eventPath } from "../../client/panel/chrome.js";
import { PanelMessage } from "../../client/panel/message.js";
import type { ShellModel } from "../../client/shell/model.js";
import { cx } from "../../ui/cx.js";
import { flashMessages } from "../../ui/flash.js";
import type { Child } from "../../ui/html.js";
import type { Translator } from "../../ui/i18n.js";
import { icon } from "../../ui/icon.js";
import type { IconData } from "../../ui/icon.js";
import {
  arrowDownTrayOutline,
  arrowUpTrayOutline,
  buildingOffice2Outline,
  calendarDaysOutline,
  chevronDownOutline,
  cog6ToothOutline,
  documentTextOutline,
  homeOutline,
  identificationOutline,
  keyOutline,
  mapOutline,
  megaphoneOutline,
  noSymbolOutline,
  plusOutline,
  printerOutline,
  rectangleStackOutline,
  tagOutline,
  ticketOutline,
  userGroupOutline,
} from "../../ui/icons.js";

type H = HtmlBuilder<PanelMessage>;

export type PanelHeader = Readonly<{
  actions: Option.Option<Html>;
  adornment: Option.Option<Html>;
  subtitle: readonly Child[];
  title: string;
}>;

const sidebarIcon = (iconClass: string, h: H) =>
  h.span(
    [h.Class("block rotate-180")],
    [
      h.svg(
        [
          h.Attribute("xmlns", "http://www.w3.org/2000/svg"),
          h.Width("24"),
          h.Height("24"),
          h.ViewBox("0 0 24 24"),
          h.Attribute("fill", "none"),
          h.Attribute("stroke", "currentColor"),
          h.Attribute("stroke-width", "2"),
          h.Attribute("stroke-linecap", "round"),
          h.Attribute("stroke-linejoin", "round"),
          h.Class(iconClass),
          h.AriaHidden(true),
        ],
        [
          h.path(
            [
              h.Attribute("stroke", "none"),
              h.D("M0 0h24v24H0z"),
              h.Attribute("fill", "none"),
            ],
            []
          ),
          h.path(
            [
              h.D(
                "M4 6a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2l0 -12"
              ),
            ],
            []
          ),
          h.path([h.D("M15 4l0 16")], []),
        ]
      ),
    ]
  );

type LinkSpec = Readonly<{
  href: string;
  icon: IconData;
  key?: PanelNav;
  label: string;
  newTab?: boolean;
}>;

const sidebarLink = (link: LinkSpec, active: PanelNav, h: H) =>
  h.a(
    [
      h.Href(link.href),
      ...(link.newTab === true ? [h.Target("_blank"), h.Rel("noopener")] : []),
      ...(link.key !== undefined && link.key === active
        ? [h.AriaCurrent("page")]
        : []),
      h.Title(link.label),
      h.Class(
        "flex text-sm items-center px-2 py-3 lg:folded:justify-center text-foreground-secondary hover:bg-bg-secondary hover:text-foreground dark:hover:bg-bg-tertiary aria-[current=page]:text-foreground aria-[current=page]:bg-bg-secondary dark:aria-[current=page]:bg-bg-tertiary rounded-lg transition hover:duration-0"
      ),
    ],
    [
      icon(link.icon, { class: "size-4.5 mr-2 lg:folded:mr-0" }, h),
      h.span([h.Class("lg:folded:hidden")], [link.label]),
    ]
  );

const category = (
  options: Readonly<{
    collapsed: readonly PanelCategory[];
    extraClass?: string;
    key: PanelCategory;
    label: string;
    links: readonly Html[];
  }>,
  h: H
) => {
  const isCollapsed = options.collapsed.includes(options.key);

  return h.div(
    [
      ...(options.extraClass === undefined
        ? []
        : [h.Class(options.extraClass)]),
      h.DataAttribute("cat", options.key),
    ],
    [
      h.button(
        [
          h.Type("button"),
          h.AriaExpanded(!isCollapsed),
          h.AriaControls(`sidebar-cat-${options.key}`),
          h.Class(
            "lg:folded:hidden flex w-full items-center justify-between px-2 pt-2 pb-1 text-xs font-semibold uppercase tracking-wider text-foreground-muted hover:text-foreground active:scale-100!"
          ),
          h.DataAttribute("action", "toggle-category"),
          h.OnClick(PanelMessage.ClickedCategory({ category: options.key })),
        ],
        [
          h.span([], [options.label]),
          h.span(
            [
              h.Class(
                cx(
                  "sidebar-cat-chevron transition-transform duration-150",
                  isCollapsed && "-rotate-90"
                )
              ),
            ],
            [icon(chevronDownOutline, { class: "w-4 h-4" }, h)]
          ),
        ]
      ),
      h.div(
        [
          h.Id(`sidebar-cat-${options.key}`),
          h.Class(
            cx(
              "sidebar-cat-body flex flex-col gap-0.5",
              isCollapsed && "hidden!"
            )
          ),
        ],
        options.links
      ),
    ]
  );
};

const eventSelector = (
  chrome: PanelChromeModel,
  translator: Translator,
  h: H
) =>
  chrome.events.length === 0
    ? h.empty
    : h.div(
        [h.Class("relative min-w-0 flex-1 lg:folded:hidden")],
        [
          h.label(
            [h.For("eventSelector"), h.Class("sr-only")],
            [translator.t("Event")]
          ),
          h.select(
            [
              h.Id("eventSelector"),
              h.Class(
                "w-full appearance-none text-ellipsis bg-bg-secondary border border-border text-foreground rounded-lg pl-3 pr-8 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary dark:bg-bg-tertiary"
              ),
              h.DataAttribute("action", "switch-event"),
              h.OnChange((slug) =>
                PanelMessage.ChangedEvent({ href: eventIndexPath(slug) })
              ),
            ],
            [
              ...(Option.isNone(chrome.currentEvent)
                ? [
                    h.option(
                      [h.Value(""), h.Disabled(true), h.Selected(true)],
                      [translator.t("Choose an event")]
                    ),
                  ]
                : []),
              ...chrome.events.map((event) =>
                h.option(
                  [
                    h.Value(event.slug),
                    h.DataAttribute("url", eventIndexPath(event.slug)),
                    ...(Option.exists(
                      chrome.currentEvent,
                      (current) => current.slug === event.slug
                    )
                      ? [h.Selected(true)]
                      : []),
                  ],
                  [event.name]
                )
              ),
            ]
          ),
          h.svg(
            [
              h.Class(
                "pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-foreground-muted"
              ),
              h.ViewBox("0 0 20 20"),
              h.Attribute("fill", "currentColor"),
            ],
            [
              h.path(
                [
                  h.Attribute("fill-rule", "evenodd"),
                  h.D(
                    "M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                  ),
                  h.Attribute("clip-rule", "evenodd"),
                ],
                []
              ),
            ]
          ),
        ]
      );

const eventCategories = (
  slug: string,
  chrome: PanelChromeModel,
  translator: Translator,
  h: H
): readonly Html[] => {
  const { t, tc } = translator;
  const active = chrome.activeNav;
  const link = (spec: LinkSpec) => sidebarLink(spec, active, h);

  return [
    link({
      href: eventIndexPath(slug),
      icon: homeOutline,
      key: "index",
      label: t("Dashboard"),
    }),
    category(
      {
        collapsed: chrome.collapsed,
        key: "program",
        label: t("Program"),
        links: [
          link({
            href: eventPath(slug, "cfp/"),
            icon: rectangleStackOutline,
            key: "cfp",
            label: t("Call for Proposals"),
          }),
          link({
            href: eventPath(slug, "proposals/"),
            icon: documentTextOutline,
            key: "proposals",
            label: t("Proposals"),
          }),
          link({
            href: eventPath(slug, "facilitators/"),
            icon: userGroupOutline,
            key: "facilitators",
            label: t("Facilitators"),
          }),
          link({
            href: eventPath(slug, "discounts/"),
            icon: ticketOutline,
            label: t("Discounts"),
          }),
          link({
            href: eventPath(slug, "import/"),
            icon: arrowDownTrayOutline,
            label: t("Google Docs Import"),
          }),
        ],
      },
      h
    ),
    category(
      {
        collapsed: chrome.collapsed,
        key: "schedule",
        label: tc("Sidebar category", "Schedule"),
        links: [
          link({
            href: eventPath(slug, "venues/"),
            icon: buildingOffice2Outline,
            key: "venues",
            label: t("Venues"),
          }),
          link({
            href: `/event/${slug}/maps/`,
            icon: mapOutline,
            label: t("Maps"),
            newTab: true,
          }),
          link({
            href: eventPath(slug, "tracks/"),
            icon: tagOutline,
            key: "tracks",
            label: t("Tracks"),
          }),
          link({
            href: eventPath(slug, "timetable/"),
            icon: calendarDaysOutline,
            key: "timetable",
            label: t("Schedule"),
          }),
          link({
            href: eventPath(slug, "export/"),
            icon: arrowUpTrayOutline,
            label: t("Konwencik export"),
          }),
          link({
            href: `/event/${slug}/print/`,
            icon: printerOutline,
            label: t("Print Materials"),
            newTab: true,
          }),
        ],
      },
      h
    ),
    category(
      {
        collapsed: chrome.collapsed,
        key: "live",
        label: tc("Sidebar category", "Live"),
        links: [
          link({
            href: eventPath(slug, "errata/"),
            icon: megaphoneOutline,
            label: t("Errata"),
          }),
        ],
      },
      h
    ),
    category(
      {
        collapsed: chrome.collapsed,
        key: "settings",
        label: t("Settings"),
        links: [
          link({
            href: eventPath(slug, "settings/"),
            icon: cog6ToothOutline,
            key: "settings",
            label: t("Event Settings"),
          }),
          link({
            href: eventPath(slug, "bans/"),
            icon: noSymbolOutline,
            label: t("Bans"),
          }),
        ],
      },
      h
    ),
  ];
};

const sidebar = (chrome: PanelChromeModel, translator: Translator, h: H) => {
  const { t } = translator;
  const active = chrome.activeNav;

  return h.aside(
    [
      h.Id("sidebar"),
      h.Class(
        cx(
          "transition-transform duration-300 ease-in-out scrollbar-none w-64 lg:folded:w-16 overflow-x-hidden overflow-y-auto border-r border-border bg-bg-tertiary text-foreground dark:bg-bg-secondary flex-shrink-0 fixed inset-y-0 left-0 z-50 lg:translate-x-0 lg:sticky lg:inset-auto lg:top-0 lg:z-auto lg:max-h-screen",
          !chrome.isSidebarOpen && "-translate-x-full"
        )
      ),
    ],
    [
      h.div(
        [
          h.Class(
            "sticky top-0 z-10 flex items-center pt-4 justify-end gap-1 lg:folded:flex-col lg:folded:pt-2 lg:folded:justify-center bg-bg-tertiary p-2 dark:bg-bg-secondary"
          ),
        ],
        [
          eventSelector(chrome, translator, h),
          h.a(
            [
              h.Href("/panel/events/new/"),
              ...(active === "event-create" ? [h.AriaCurrent("page")] : []),
              h.AriaLabel(t("New event")),
              h.Title(t("New event")),
              h.Class(
                "inline-flex items-center justify-center p-2 shrink-0 rounded-lg transition text-foreground-muted hover:text-foreground hover:bg-bg-secondary dark:hover:bg-bg-tertiary aria-[current=page]:text-foreground aria-[current=page]:bg-bg-secondary dark:aria-[current=page]:bg-bg-tertiary"
              ),
            ],
            [icon(plusOutline, { class: "size-5" }, h)]
          ),
          h.button(
            [
              h.Id("sidebarFoldBtn"),
              h.Type("button"),
              h.Class(
                "hidden lg:inline-flex items-center justify-center p-2 text-foreground-muted hover:text-foreground hover:bg-bg-secondary dark:hover:bg-bg-tertiary rounded-lg transition flex-shrink-0"
              ),
              h.Title(t("Toggle sidebar")),
              h.AriaLabel(t("Toggle sidebar")),
              h.DataAttribute("action", "toggle-fold"),
              h.OnClick(PanelMessage.ClickedFold()),
            ],
            [sidebarIcon("size-5", h)]
          ),
        ]
      ),
      h.nav(
        [
          h.AriaLabel(t("Panel sections")),
          h.Class("px-2 pb-2 gap-0.5 flex flex-col"),
        ],
        [
          ...Option.match(chrome.currentEvent, {
            onNone: () => [],
            onSome: (event) =>
              eventCategories(event.slug, chrome, translator, h),
          }),
          category(
            {
              collapsed: chrome.collapsed,
              extraClass:
                "not-first:mt-4 not-first:pt-2 not-first:border-t not-first:border-border",
              key: "sphere",
              label: t("Sphere"),
              links: [
                sidebarLink(
                  {
                    href: "/multiverse/panel/team/",
                    icon: keyOutline,
                    label: t("Team"),
                  },
                  active,
                  h
                ),
                sidebarLink(
                  {
                    href: "/multiverse/panel/guilds/",
                    icon: identificationOutline,
                    label: t("Guilds"),
                  },
                  active,
                  h
                ),
                sidebarLink(
                  {
                    href: "/multiverse/panel/",
                    icon: cog6ToothOutline,
                    label: t("Sphere settings"),
                  },
                  active,
                  h
                ),
              ],
            },
            h
          ),
        ]
      ),
    ]
  );
};

const defaultActions = (
  chrome: PanelChromeModel,
  translator: Translator,
  h: H
) =>
  h.div(
    [h.Class("hidden sm:flex items-center space-x-4 shrink-0")],
    Option.match(chrome.currentEvent, {
      onNone: () => [],
      onSome: (event) => [
        h.span(
          [h.Class("text-sm text-foreground-muted hidden md:inline")],
          [`${translator.t("Event:")} `, h.strong([], [event.dateLabel])]
        ),
        event.isProposalActive
          ? h.span(
              [
                h.Class(
                  "px-3 py-1 bg-success-bg text-success-text text-sm rounded-full whitespace-nowrap"
                ),
              ],
              [translator.t("Proposals Open")]
            )
          : h.span(
              [
                h.Class(
                  "px-3 py-1 bg-bg-tertiary text-foreground-secondary text-sm rounded-full whitespace-nowrap"
                ),
              ],
              [translator.t("Proposals Closed")]
            ),
      ],
    })
  );

export const panelLayout = (
  options: Readonly<{
    chrome: PanelChromeModel;
    content: readonly Child[];
    header: PanelHeader;
    overlays: readonly Html[];
    shell: ShellModel;
    translator: Translator;
  }>,
  h: H
): Html => {
  const { chrome, header, translator } = options;
  const { t } = translator;

  const flashes = options.shell.flashes.filter(
    (flash) => !chrome.dismissedFlashIds.includes(flash.id)
  );

  return h.div(
    [
      h.Class("flex flex-1"),
      h.OnKeyDownPreventDefault((key) =>
        key === "Escape" && chrome.isSidebarOpen
          ? Option.some(PanelMessage.PressedEscape())
          : Option.none()
      ),
    ],
    [
      h.button(
        [
          h.Type("button"),
          h.Id("sidebarOverlay"),
          h.Class(
            cx(
              "transition-opacity duration-300 ease-in-out fixed inset-0 bg-black/50 z-40 lg:hidden w-full h-full cursor-default",
              !chrome.isSidebarOpen && "hidden"
            )
          ),
          h.AriaLabel(t("Close navigation")),
          h.DataAttribute("action", "toggle-sidebar"),
          h.OnClick(PanelMessage.ToggledSidebar({ isOpen: false })),
        ],
        []
      ),
      sidebar(chrome, translator, h),
      h.main(
        [
          h.DataAttribute("ph-mask", ""),
          h.Class(
            "flex min-h-0 min-w-0 flex-1 flex-col [&_.tab-shell]:rounded-t-none [&_.tab-shell-bar]:pt-1.5 max-sm:[&_.tab-shell-bar]:px-1.5 max-sm:[&_.tab-shell-body]:px-1.5"
          ),
        ],
        [
          h.header(
            [
              h.Class(
                "btn-strip-compact bg-bg-secondary border-border border-b px-3 sm:px-4 py-2 sm:py-3 sticky top-0 z-10"
              ),
            ],
            [
              h.div(
                [h.Class("flex flex-wrap items-center justify-between gap-2")],
                [
                  h.button(
                    [
                      h.Type("button"),
                      h.DataAttribute("action", "toggle-sidebar"),
                      h.AriaLabel(t("Open navigation")),
                      h.Class(
                        "lg:hidden p-2 -ml-2 text-foreground-secondary hover:text-foreground hover:bg-bg-tertiary rounded-lg flex-shrink-0"
                      ),
                      h.OnClick(PanelMessage.ToggledSidebar({ isOpen: true })),
                    ],
                    [sidebarIcon("size-6", h)]
                  ),
                  h.div(
                    [h.Class("min-w-0 grow basis-48")],
                    [
                      h.div(
                        [h.Class("flex items-center gap-2 min-w-0")],
                        [
                          h.h2(
                            [
                              h.Class(
                                "text-[1.0625rem]/tight sm:text-xl font-bold text-foreground line-clamp-2 wrap-anywhere"
                              ),
                            ],
                            [header.title]
                          ),
                          Option.getOrElse(header.adornment, () => h.empty),
                        ]
                      ),
                      h.p(
                        [
                          h.Class(
                            "mt-1 text-foreground-muted text-sm lg:text-base text-box-trim-start text-pretty"
                          ),
                        ],
                        header.subtitle
                      ),
                    ]
                  ),
                  Option.getOrElse(header.actions, () =>
                    defaultActions(chrome, translator, h)
                  ),
                ]
              ),
            ]
          ),
          flashMessages(
            {
              flashes,
              onDismiss: (id) => PanelMessage.DismissedFlash({ id }),
              translator,
            },
            h
          ),
          h.div(
            [
              h.Class(
                "relative z-0 flex min-h-0 flex-1 flex-col [&>.tab-shell]:border-0"
              ),
            ],
            options.content
          ),
        ]
      ),
      ...options.overlays,
    ]
  );
};

export const crumbs = (
  options: Readonly<{
    backHref: string;
    backLabel: string;
    eventName: string;
    eventSlug: string;
  }>,
  h: H
): readonly Child[] => [
  h.a(
    [
      h.Href(eventIndexPath(options.eventSlug)),
      h.Class(
        "underline underline-offset-3 decoration-foreground-muted/50 hover:text-foreground hover:decoration-foreground/50"
      ),
    ],
    [options.eventName]
  ),
  " ",
  h.span([h.AriaHidden(true)], ["·"]),
  " ",
  h.a(
    [
      h.Href(options.backHref),
      h.Class(
        "underline underline-offset-3 decoration-foreground-muted/50 hover:text-foreground hover:decoration-foreground/50"
      ),
    ],
    [options.backLabel]
  ),
];
