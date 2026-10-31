import type {
  CategoryWindow,
  CfpFlags,
} from "../../../client/panel/cfp/flags.js";
import type { PanelCurrentEvent } from "../../../client/panel/chrome.js";
import { eventPath } from "../../../client/panel/chrome.js";
import { linkButton } from "../../../ui/button.js";
import type { Translator } from "../../../ui/i18n.js";
import { plusOutline } from "../../../ui/icons.js";
import { header, tableHead, tesseraTable } from "../page.js";
import type { PanelH, PanelPageView } from "../page.js";
import { panelTabs } from "../tabs.js";

const windowBadge: Readonly<
  Record<CategoryWindow, Readonly<{ className: string; msgid: string }>>
> = {
  active: { className: "bg-green-100 text-green-700", msgid: "Active" },
  closed: { className: "bg-gray-100 text-gray-600", msgid: "Closed" },
  not_set: { className: "bg-gray-100 text-gray-600", msgid: "Not set" },
  upcoming: { className: "bg-blue-100 text-blue-700", msgid: "Upcoming" },
};

export const cfpTabs = (slug: string, translator: Translator) => [
  {
    href: eventPath(slug, "cfp/"),
    key: "types",
    label: translator.t("Categories"),
  },
  {
    href: eventPath(slug, "cfp/personal-data/"),
    key: "host",
    label: translator.t("Host Data Fields"),
  },
  {
    href: eventPath(slug, "cfp/session-fields/"),
    key: "session",
    label: translator.t("Session Fields"),
  },
  {
    href: eventPath(slug, "cfp/time-slots/"),
    key: "time_slots",
    label: translator.t("Time Slots"),
  },
];

export const cfpView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    page: CfpFlags;
    translator: Translator;
  }>,
  h: PanelH
): PanelPageView => {
  const { event, page, translator } = options;
  const { t, tc } = translator;

  const createButton = linkButton(
    {
      href: eventPath(event.slug, "cfp/create/"),
      icon: plusOutline,
      text: t("New Category"),
    },
    h
  );

  const body =
    page.categories.length === 0
      ? h.div(
          [h.Class("card p-8 text-center")],
          [
            h.p(
              [h.Class("text-foreground-muted mb-4")],
              [
                t(
                  "No categories yet. Add a category to allow facilitators to submit proposals."
                ),
              ]
            ),
            createButton,
          ]
        )
      : tesseraTable(
          {
            body: [
              tableHead(
                [
                  { label: tc("place", "Name") },
                  { label: t("Accepted") },
                  { label: t("Submission window") },
                  { align: "right", label: t("Actions") },
                ],
                h
              ),
              h.tbody(
                [h.Class("bg-bg-secondary divide-y divide-border")],
                page.categories.map((category) =>
                  h.tr(
                    [h.Key(category.slug), h.Class("hover:bg-bg-tertiary")],
                    [
                      h.td(
                        [
                          h.Class(
                            "px-6 py-4 text-sm font-medium text-foreground max-w-xs truncate"
                          ),
                        ],
                        [category.name]
                      ),
                      h.td(
                        [
                          h.Class(
                            "px-6 py-4 whitespace-nowrap text-sm text-foreground-muted"
                          ),
                        ],
                        [
                          `${category.acceptedCount} / ${category.proposalsCount}`,
                        ]
                      ),
                      h.td(
                        [h.Class("px-6 py-4 text-sm text-foreground-muted")],
                        [
                          h.span(
                            [
                              h.Class(
                                `inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${windowBadge[category.window].className}`
                              ),
                            ],
                            [t(windowBadge[category.window].msgid)]
                          ),
                          category.windowLabel === ""
                            ? h.empty
                            : h.span([h.Class("ml-2")], [category.windowLabel]),
                        ]
                      ),
                      h.td(
                        [
                          h.Class(
                            "px-6 py-4 whitespace-nowrap text-right text-sm font-medium"
                          ),
                        ],
                        [
                          h.a(
                            [
                              h.Href(
                                eventPath(event.slug, `cfp/${category.slug}/`)
                              ),
                              h.DataAttribute("row-action", ""),
                              h.Class(
                                "text-primary hover:text-primary/80 mr-4"
                              ),
                            ],
                            [t("Configure")]
                          ),
                          category.hasProposals
                            ? h.span(
                                [h.Class("text-sm text-foreground-muted")],
                                [t("Has proposals")]
                              )
                            : h.button(
                                [
                                  h.Type("button"),
                                  h.Disabled(true),
                                  h.Title(
                                    t("Not available in this version yet.")
                                  ),
                                  h.Class(
                                    "text-sm text-danger hover:text-danger/80 disabled:opacity-50"
                                  ),
                                ],
                                [t("Delete")]
                              ),
                        ]
                      ),
                    ]
                  )
                )
              ),
            ],
          },
          h
        );

  return {
    content: [
      panelTabs(
        {
          active: "types",
          body: [body],
          tabs: cfpTabs(event.slug, translator),
        },
        h
      ),
    ],
    header: header({
      actions: createButton,
      subtitle: [`${event.name} · ${t("Categories")}`],
      title: t("Call for Proposals"),
    }),
    title: t("Call for Proposals"),
  };
};
