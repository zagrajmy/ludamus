import { Match } from "effect";

import { PanelAction } from "../../../client/panel/action.js";
import type { PanelCurrentEvent } from "../../../client/panel/chrome.js";
import { eventPath } from "../../../client/panel/chrome.js";
import { PanelMessage } from "../../../client/panel/message.js";
import type {
  ProposalColumn,
  ProposalRow,
  ProposalsFlags,
} from "../../../client/panel/proposals/flags.js";
import { ProposalListMessage } from "../../../client/panel/proposals/message.js";
import { linkButton } from "../../../ui/button.js";
import type { Translator } from "../../../ui/i18n.js";
import { clockOutline, plusOutline } from "../../../ui/icons.js";
import { header, tableHead } from "../page.js";
import type { PanelH, PanelPageView } from "../page.js";
import { statusBadge } from "../status.js";
import { panelTabs } from "../tabs.js";

const toList = (message: ProposalListMessage) =>
  PanelMessage.RelayedProposalList({ message });

export const proposalTabs = (
  slug: string,
  query: string,
  translator: Translator
) => [
  {
    href: eventPath(slug, "proposals/"),
    key: "list",
    label: translator.t("List"),
  },
  {
    href: eventPath(slug, "proposals/columns/"),
    key: "columns",
    label: translator.t("Columns"),
  },
  {
    href: `${eventPath(slug, "proposals/export/")}?${query}`,
    key: "export",
    label: translator.t("Export"),
  },
];

const filterLabel = (forId: string, text: string, h: PanelH) =>
  h.label(
    [
      h.For(forId),
      h.Title(text),
      h.Class("block text-xs font-medium text-foreground-muted mb-1 truncate"),
    ],
    [text]
  );

const filterSelectClass =
  "filter-input w-full px-3 py-2 border border-border rounded-lg text-sm truncate";

const option = (value: string, text: string, selected: string, h: PanelH) =>
  h.option(
    [h.Value(value), ...(value === selected ? [h.Selected(true)] : [])],
    [text]
  );

const statusLabels = (translator: Translator) =>
  [
    ["pending", translator.t("Pending")],
    ["accepted", translator.t("Accepted")],
    ["on_hold", translator.t("On hold")],
    ["rejected", translator.t("Rejected")],
  ] as const;

const filterCard = (
  model: ProposalsFlags,
  translator: Translator,
  h: PanelH
) => {
  const { t } = translator;
  const status = model.filterStatus;

  return h.div(
    [h.Class("card p-4 mb-6")],
    [
      h.form(
        [
          h.Method("get"),
          h.Id("proposals-filter-form"),
          h.Class("flex flex-wrap gap-4 items-end"),
          h.OnSubmit(toList(ProposalListMessage.SubmittedFilters())),
        ],
        [
          h.div(
            [h.Class("w-full sm:w-48 min-w-0")],
            [
              filterLabel("filter-search", t("Search"), h),
              h.input([
                h.Type("text"),
                h.Id("filter-search"),
                h.Name("search"),
                h.Value(model.filters.search),
                h.Placeholder(
                  t("Search by title, facilitator or field values")
                ),
                h.Class(
                  "filter-input w-full px-3 py-2 border border-border rounded-lg text-sm"
                ),
                h.OnInput((value) =>
                  toList(
                    ProposalListMessage.ChangedFilter({ name: "search", value })
                  )
                ),
              ]),
            ]
          ),
          model.categories.length === 0
            ? h.empty
            : h.div(
                [h.Class("w-full sm:w-48 min-w-0")],
                [
                  filterLabel("filter-category", t("Category"), h),
                  h.select(
                    [
                      h.Id("filter-category"),
                      h.Name("category"),
                      h.Class(filterSelectClass),
                      h.OnChange((value) =>
                        toList(
                          ProposalListMessage.ChangedFilter({
                            name: "category",
                            value,
                          })
                        )
                      ),
                    ],
                    [
                      option(
                        "",
                        t("All categories"),
                        model.filters.category,
                        h
                      ),
                      ...model.categories.map((category) =>
                        option(
                          String(category.id),
                          category.name,
                          model.filters.category,
                          h
                        )
                      ),
                    ]
                  ),
                ]
              ),
          h.div(
            [h.Class("w-full sm:w-48 min-w-0")],
            [
              filterLabel("filter-status", t("Status"), h),
              h.select(
                [
                  h.Id("filter-status"),
                  h.Name("status"),
                  h.Class(filterSelectClass),
                  h.OnChange((value) =>
                    toList(
                      ProposalListMessage.ChangedFilter({
                        name: "status",
                        value,
                      })
                    )
                  ),
                ],
                [
                  option(
                    "all",
                    t("All statuses"),
                    status === "" ? "all" : status,
                    h
                  ),
                  h.optgroup(
                    [h.LabelAttr(t("Not on the timetable"))],
                    statusLabels(translator).map(([value, text]) =>
                      option(value, text, status, h)
                    )
                  ),
                  h.optgroup(
                    [h.LabelAttr(t("On the timetable"))],
                    [option("scheduled", t("Scheduled"), status, h)]
                  ),
                ]
              ),
            ]
          ),
          ...model.fields.map((field) =>
            h.div(
              [h.Key(`field-${field.id}`), h.Class("w-full sm:w-48 min-w-0")],
              [
                filterLabel(`filter-field-${field.id}`, field.name, h),
                h.select(
                  [
                    h.Id(`filter-field-${field.id}`),
                    h.Name(`field_${field.id}`),
                    h.Class(filterSelectClass),
                    h.OnChange((value) =>
                      toList(
                        ProposalListMessage.ChangedFilter({
                          name: `field_${field.id}`,
                          value,
                        })
                      )
                    ),
                  ],
                  [
                    option("", "—", field.value, h),
                    ...field.options.map((choice) =>
                      option(choice.value, choice.label, field.value, h)
                    ),
                  ]
                ),
              ]
            )
          ),
          h.div(
            [h.Class("flex items-center gap-2")],
            [
              h.button([h.Type("submit"), h.Class("sr-only")], [t("Filter")]),
              h.a(
                [
                  h.Href(`${model.listPath}?status=all`),
                  h.Class(
                    "px-4 py-2 text-foreground-muted hover:text-foreground-secondary text-sm"
                  ),
                ],
                [t("Clear")]
              ),
            ]
          ),
        ]
      ),
    ]
  );
};

const sortHeader = (
  column: ProposalColumn,
  model: ProposalsFlags,
  h: PanelH
) => {
  const sortedHref = (value: string) => {
    const params = new URLSearchParams(model.fullPath.split("?")[1] ?? "");

    params.set("sort", value);
    params.delete("page");

    return `${model.listPath}?${params.toString()}`;
  };

  const base =
    "text-left text-xs font-medium text-foreground-muted uppercase tracking-wider";

  const arrow = (glyph: string, extra: string) =>
    h.span([h.AriaHidden(true), h.Class(`ml-1${extra}`)], [glyph]);

  if (model.filters.sort === column.key) {
    return h.th(
      [h.Scope("col"), h.AriaSort("ascending"), h.Class(base)],
      [
        h.a(
          [
            h.Href(sortedHref(`-${column.key}`)),
            h.Class("flex items-center px-6 py-3 hover:text-foreground"),
          ],
          [column.label, arrow("▲", "")]
        ),
      ]
    );
  }

  if (model.filters.sort === `-${column.key}`) {
    return h.th(
      [h.Scope("col"), h.AriaSort("descending"), h.Class(base)],
      [
        h.a(
          [
            h.Href(sortedHref(column.key)),
            h.Class("flex items-center px-6 py-3 hover:text-foreground"),
          ],
          [column.label, arrow("▼", "")]
        ),
      ]
    );
  }

  return h.th(
    [h.Scope("col"), h.AriaSort("none"), h.Class(base)],
    [
      h.a(
        [
          h.Href(sortedHref(column.key)),
          h.Class(
            "group flex items-center px-6 py-3 text-foreground-muted hover:text-foreground"
          ),
        ],
        [column.label, arrow("↕", " opacity-40 group-hover:opacity-70")]
      ),
    ]
  );
};

const cellOf = (
  options: Readonly<{
    column: ProposalColumn;
    model: ProposalsFlags;
    row: ProposalRow;
    translator: Translator;
  }>,
  h: PanelH
) => {
  const { column, row } = options;

  if (column.kind === "status") {
    return statusBadge(
      {
        isScheduled: row.isScheduled,
        status: row.status,
        translator: options.translator,
      },
      h
    );
  }

  if (column.kind === "created") {
    return row.createdLabel;
  }

  const cells = options.model.cells.find((cell) => cell.id === row.id);

  return cells?.values[column.key] ?? "";
};

const textOf = (
  options: Readonly<{
    column: ProposalColumn;
    model: ProposalsFlags;
    row: ProposalRow;
  }>
) =>
  Match.value(options.column.kind).pipe(
    Match.when(
      "text",
      () =>
        options.model.cells.find((cell) => cell.id === options.row.id)?.values[
          options.column.key
        ] ?? ""
    ),
    Match.when("created", () => options.row.createdLabel),
    Match.orElse(() => "")
  );

const deletedSection = (
  event: PanelCurrentEvent,
  model: ProposalsFlags,
  translator: Translator,
  h: PanelH
) => {
  const { t } = translator;

  return model.deleted.length === 0
    ? []
    : [
        h.h2(
          [
            h.Id("deleted-proposals"),
            h.Class(
              "mt-8 mb-3 text-sm font-semibold text-foreground-muted uppercase tracking-wider"
            ),
          ],
          [t("Recently deleted")]
        ),
        h.div(
          [h.Class("card overflow-hidden")],
          [
            h.div(
              [h.Class("overflow-x-auto")],
              [
                h.table(
                  [h.Class("min-w-full divide-y divide-border")],
                  [
                    tableHead(
                      [
                        { label: t("Title") },
                        { label: t("Presenter name") },
                        { label: t("Status") },
                        { align: "right", label: t("Actions") },
                      ],
                      h
                    ),
                    h.tbody(
                      [h.Class("bg-bg-secondary divide-y divide-border")],
                      model.deleted.map((row) =>
                        h.tr(
                          [h.Key(String(row.id))],
                          [
                            h.td(
                              [
                                h.Class(
                                  "px-6 py-4 text-sm font-medium text-foreground max-w-xs truncate"
                                ),
                              ],
                              [row.title]
                            ),
                            h.td(
                              [
                                h.Class(
                                  "px-6 py-4 max-w-xs truncate text-sm text-foreground-muted"
                                ),
                                h.Title(row.facilitatorName),
                              ],
                              [row.facilitatorName]
                            ),
                            h.td(
                              [h.Class("px-6 py-4 whitespace-nowrap text-sm")],
                              [
                                statusBadge(
                                  {
                                    isScheduled: row.isScheduled,
                                    status: row.status,
                                    translator,
                                  },
                                  h
                                ),
                              ]
                            ),
                            h.td(
                              [
                                h.Class(
                                  "px-6 py-4 whitespace-nowrap text-sm text-right"
                                ),
                              ],
                              [
                                h.button(
                                  [
                                    h.Type("button"),
                                    h.Class(
                                      "btn btn-secondary px-4 py-2 text-sm max-md:w-full"
                                    ),
                                    h.OnClick(
                                      PanelMessage.RequestedAction({
                                        action: PanelAction.RestoreProposal({
                                          eventSlug: event.slug,
                                          proposalId: row.id,
                                        }),
                                      })
                                    ),
                                  ],
                                  [
                                    h.span(
                                      [h.Class("btn-label")],
                                      [t("Restore")]
                                    ),
                                  ]
                                ),
                              ]
                            ),
                          ]
                        )
                      )
                    ),
                  ]
                ),
              ]
            ),
          ]
        ),
      ];
};

const trackForm = (
  model: ProposalsFlags,
  translator: Translator,
  h: PanelH
) => {
  const { t } = translator;

  return model.tracks.length === 0
    ? h.empty
    : h.form(
        [
          h.Method("get"),
          h.Class("flex min-w-0 max-w-full items-center gap-2"),
        ],
        [
          h.label(
            [
              h.For("track-scope"),
              h.Class(
                "text-xs text-foreground-muted whitespace-nowrap hidden sm:inline"
              ),
            ],
            [t("Track")]
          ),
          h.select(
            [
              h.Id("track-scope"),
              h.Name("track"),
              h.Class(
                "min-w-0 max-w-full sm:max-w-xs px-3 py-1.5 border border-border rounded-lg text-sm bg-bg-secondary text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              ),
              h.OnChange((value) =>
                toList(ProposalListMessage.ChangedTrack({ value }))
              ),
            ],
            [
              option("", t("All tracks"), model.filters.track, h),
              option("multi", t("Multiple tracks"), model.filters.track, h),
              ...model.tracks.map((track) =>
                h.option(
                  [
                    h.Value(String(track.id)),
                    ...(model.filters.track === String(track.id)
                      ? [h.Selected(true)]
                      : []),
                    ...(track.isManaged ? [h.Class("font-semibold")] : []),
                  ],
                  [track.isManaged ? `★ ${track.name}` : track.name]
                )
              ),
            ]
          ),
        ]
      );
};

export const proposalsView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    model: ProposalsFlags;
    translator: Translator;
  }>,
  h: PanelH
): PanelPageView => {
  const { event, model, translator } = options;
  const { t } = translator;
  const query = model.fullPath.split("?")[1] ?? "";

  const createButton = linkButton(
    {
      href: eventPath(event.slug, "proposals/create/"),
      icon: plusOutline,
      text: t("New Proposal"),
    },
    h
  );

  const allStatusesHref = () => {
    const params = new URLSearchParams(query);

    params.set("status", "all");

    return `${model.listPath}?${params.toString()}`;
  };

  const results =
    model.rows.length > 0
      ? h.div(
          [h.Class("card overflow-hidden")],
          [
            h.div(
              [h.Class("overflow-x-auto")],
              [
                h.table(
                  [h.Class("min-w-full divide-y divide-border")],
                  [
                    h.thead(
                      [h.Class("bg-bg-tertiary")],
                      [
                        h.tr(
                          [],
                          model.columns.map((column) =>
                            sortHeader(column, model, h)
                          )
                        ),
                      ]
                    ),
                    h.tbody(
                      [h.Class("bg-bg-secondary divide-y divide-border")],
                      model.rows.map((row) =>
                        h.tr(
                          [
                            h.Key(String(row.id)),
                            h.Class("hover:bg-bg-tertiary"),
                          ],
                          model.columns.map((column, index) => {
                            const cell = cellOf(
                              { column, model, row, translator },
                              h
                            );

                            return h.td(
                              [
                                h.Class(
                                  `px-6 py-4 max-w-xs truncate text-sm ${index === 0 ? "font-medium text-foreground" : "text-foreground-muted"}`
                                ),
                                h.Title(textOf({ column, model, row })),
                              ],
                              [
                                index === 0
                                  ? h.a(
                                      [
                                        h.Href(
                                          `${eventPath(event.slug, `proposals/${row.id}/`)}?${new URLSearchParams({ next: model.fullPath }).toString()}`
                                        ),
                                        h.DataAttribute("row-action", ""),
                                        h.AriaLabel(row.title),
                                        h.Class(
                                          "text-primary hover:text-primary/80"
                                        ),
                                      ],
                                      [cell]
                                    )
                                  : cell,
                              ]
                            );
                          })
                        )
                      )
                    ),
                  ]
                ),
              ]
            ),
          ]
        )
      : h.div(
          [h.Class("card p-8 text-center")],
          model.hasProposals
            ? [
                h.p(
                  [h.Class("text-foreground-muted mb-4")],
                  [t("No proposals match the current filters.")]
                ),
                model.filterStatus === ""
                  ? h.empty
                  : linkButton(
                      {
                        href: allStatusesHref(),
                        text: t("Show all statuses"),
                        variant: "secondary",
                      },
                      h
                    ),
              ]
            : [
                h.p(
                  [h.Class("text-foreground-muted mb-4")],
                  [t("No proposals submitted yet.")]
                ),
                createButton,
              ]
        );

  return {
    content: [
      panelTabs(
        {
          active: "list",
          body: [
            filterCard(model, translator, h),
            h.div([h.Id("proposals-results")], [results]),
            ...deletedSection(event, model, translator, h),
          ],
          tabs: proposalTabs(event.slug, query, translator),
        },
        h
      ),
    ],
    header: header({
      actions: h.div(
        [h.Class("contents")],
        [
          createButton,
          linkButton(
            {
              href: eventPath(event.slug, "proposals/log/"),
              icon: clockOutline,
              text: t("Activity Log"),
              variant: "secondary",
            },
            h
          ),
          trackForm(model, translator, h),
        ]
      ),
      subtitle: [`${event.name} · ${t("Submitted Proposals")}`],
      title: t("Proposals"),
    }),
    title: t("Proposals"),
  };
};
