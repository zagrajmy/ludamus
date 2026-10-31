import { Option } from "effect";

import { PanelAction } from "../../../client/panel/action.js";
import type { PanelCurrentEvent } from "../../../client/panel/chrome.js";
import { eventPath } from "../../../client/panel/chrome.js";
import type {
  AccreditationValue,
  FacilitatorColumn,
  FacilitatorDetailFlags,
  FacilitatorRow,
} from "../../../client/panel/facilitators/flags.js";
import {
  FacilitatorFormMessage,
  FacilitatorListMessage,
} from "../../../client/panel/facilitators/message.js";
import type {
  FacilitatorBinModel,
  FacilitatorFormModel,
  FacilitatorsModel,
} from "../../../client/panel/facilitators/model.js";
import { errorsFor } from "../../../client/panel/failure.js";
import { PanelMessage } from "../../../client/panel/message.js";
import { button, linkButton } from "../../../ui/button.js";
import {
  checkboxInput,
  field,
  formErrors,
  helpAndErrors,
  label,
  selectInput,
  textInput,
  textareaInput,
} from "../../../ui/form.js";
import type { Child } from "../../../ui/html.js";
import type { Translator } from "../../../ui/i18n.js";
import { icon } from "../../../ui/icon.js";
import {
  arrowUturnLeftOutline,
  checkOutline,
  pencilSquareOutline,
  plusOutline,
  trashOutline,
} from "../../../ui/icons.js";
import { crumbs } from "../chrome.js";
import { header } from "../page.js";
import type { PanelH, PanelPageView } from "../page.js";
import { statusBadge } from "../status.js";
import { panelTabs } from "../tabs.js";

export const accreditationLabel = (
  value: AccreditationValue,
  translator: Translator
) => {
  const labels: Readonly<Record<AccreditationValue, string>> = {
    creator: translator.t("Program creator"),
    guest: translator.t("Guest"),
    honorary: translator.t("Honorary"),
    none: translator.t("None"),
    standard: translator.t("Standard"),
  };

  return labels[value];
};

export const accreditationChoices = (translator: Translator) =>
  (["none", "standard", "guest", "honorary", "creator"] as const).map(
    (value) => ({
      label: accreditationLabel(value, translator),
      value,
    })
  );

const columnLabel = (column: FacilitatorColumn, translator: Translator) => {
  const labels: Readonly<Record<FacilitatorColumn, string>> = {
    accreditation: translator.t("Accreditation"),
    guild: translator.t("Guild"),
    linked: translator.t("Linked User"),
    name: translator.t("Display Name"),
    organizer: translator.t("Organizer"),
    sessions: translator.t("Sessions"),
  };

  return labels[column];
};

const truncate = (value: string, size: number) =>
  value.length > size ? `${value.slice(0, size - 1)}…` : value;

const cellValue = (
  row: FacilitatorRow,
  column: FacilitatorColumn,
  translator: Translator
) => {
  const cells: Readonly<Record<FacilitatorColumn, () => string>> = {
    accreditation: () => accreditationLabel(row.accreditationType, translator),
    guild: () => "—",
    linked: () =>
      row.isLinked ? translator.t("Linked") : translator.t("None"),
    name: () => row.displayName,
    organizer: () => (row.organizerName === "" ? "—" : row.organizerName),
    sessions: () => String(row.sessionCount),
  };

  return cells[column]();
};

export const facilitatorTabs = (slug: string, translator: Translator) => [
  {
    href: eventPath(slug, "facilitators/"),
    key: "list",
    label: translator.t("List"),
  },
  {
    href: eventPath(slug, "facilitators/merge/"),
    key: "merge",
    label: translator.t("Merge"),
  },
  {
    href: eventPath(slug, "facilitators/columns/"),
    key: "columns",
    label: translator.t("Columns"),
  },
  {
    href: eventPath(slug, "facilitators/export/?"),
    key: "export",
    label: translator.t("Export"),
  },
  {
    href: eventPath(slug, "facilitators/bin/"),
    key: "bin",
    label: translator.t("Bin"),
  },
];

const toList = (message: FacilitatorListMessage) =>
  PanelMessage.RelayedFacilitatorList({ message });

const bulkCheckbox = (
  options: Readonly<{
    ariaLabel: string;
    checked: boolean;
    id: Option.Option<string>;
    onToggle: PanelMessage;
  }>,
  h: PanelH
) =>
  checkboxInput(
    {
      ariaLabel: options.ariaLabel,
      attributes: [
        h.OnClick(options.onToggle),
        ...Option.toArray(Option.map(options.id, (id) => h.Id(id))),
      ],
      checked: options.checked,
    },
    h
  );

const bulkToolbar = (
  options: Readonly<{
    actions: readonly Readonly<{
      label: string;
      variant: "danger" | "secondary";
    }>[];
    count: number;
  }>,
  translator: Translator,
  h: PanelH
) =>
  h.div(
    [h.Id("bulk-status-form")],
    [
      h.div(
        [h.Class("flex flex-wrap items-center gap-2 mb-3")],
        [
          h.span(
            [h.Class("text-sm text-foreground-muted mr-1")],
            [
              `${translator.t("Selected:")} `,
              h.span([h.Id("bulk-selected-count")], [String(options.count)]),
            ]
          ),
          ...options.actions.map((action) =>
            h.button(
              [
                h.Type("button"),
                h.DataAttribute("bulk-action", ""),
                h.Class(`btn btn-${action.variant} text-sm`),
                h.Disabled(true),
                h.Title(translator.t("Not available in this version yet.")),
              ],
              [action.label]
            )
          ),
        ]
      ),
    ]
  );

const filterBar = (
  model: FacilitatorsModel,
  translator: Translator,
  h: PanelH
) => {
  const { t } = translator;

  return h.div(
    [h.Class("card p-4 mb-6")],
    [
      h.form(
        [
          h.Id("facilitators-filter-form"),
          h.Method("get"),
          h.Class("flex flex-wrap gap-4 items-end"),
          h.OnSubmit(toList(FacilitatorListMessage.SubmittedFilters())),
        ],
        [
          h.div(
            [h.Class("w-full sm:w-64 min-w-0")],
            [
              label(
                { forId: "filter-search", text: t("Search"), translator },
                h
              ),
              textInput(
                {
                  attributes: [
                    h.OnInput((value) =>
                      toList(
                        FacilitatorListMessage.ChangedFilter({
                          name: "search",
                          value,
                        })
                      )
                    ),
                  ],
                  id: "filter-search",
                  name: "search",
                  placeholder: t("Name, linked user or field values"),
                  value: model.filters.search,
                },
                h
              ),
            ]
          ),
          h.div(
            [h.Class("w-full sm:w-48 min-w-0")],
            [
              label(
                {
                  forId: "filter-accreditation",
                  text: t("Accreditation"),
                  translator,
                },
                h
              ),
              selectInput(
                {
                  attributes: [
                    h.Class("truncate"),
                    h.OnChange((value) =>
                      toList(
                        FacilitatorListMessage.ChangedFilter({
                          name: "accreditation",
                          value,
                        })
                      )
                    ),
                  ],
                  id: "filter-accreditation",
                  name: "accreditation",
                  options: [
                    { label: t("All accreditations"), value: "" },
                    ...accreditationChoices(translator),
                  ],
                  selected: model.filters.accreditation,
                },
                h
              ),
            ]
          ),
          h.div(
            [h.Class("w-full sm:w-48 min-w-0")],
            [
              label(
                { forId: "filter-organizer", text: t("Organizer"), translator },
                h
              ),
              selectInput(
                {
                  attributes: [
                    h.Class("truncate"),
                    h.OnChange((value) =>
                      toList(
                        FacilitatorListMessage.ChangedFilter({
                          name: "organizer",
                          value,
                        })
                      )
                    ),
                  ],
                  id: "filter-organizer",
                  name: "organizer",
                  options: [
                    { label: t("All organizers"), value: "" },
                    { label: t("Mine"), value: "mine" },
                    { label: t("Nobody"), value: "unassigned" },
                  ],
                  selected: model.filters.organizer,
                },
                h
              ),
            ]
          ),
          h.div(
            [h.Class("flex items-center gap-2")],
            [
              h.button([h.Type("submit"), h.Class("sr-only")], [t("Filter")]),
              linkButton(
                {
                  href: model.listPath,
                  text: t("Clear"),
                  variant: "secondary",
                },
                h
              ),
            ]
          ),
        ]
      ),
    ]
  );
};

const sortHeader = (
  options: Readonly<{
    column: FacilitatorColumn;
    label: string;
    model: FacilitatorsModel;
  }>,
  h: PanelH
) => {
  const { column, model } = options;
  const sort = model.filters.sort === "" ? "name" : model.filters.sort;

  const query = (value: string) => {
    const params = new URLSearchParams({ ...model.filters, sort: value });

    return `${model.listPath}?${params.toString()}`;
  };

  const base =
    "text-left text-xs font-medium text-foreground-muted uppercase tracking-wider";

  if (sort === column) {
    return h.th(
      [h.Scope("col"), h.AriaSort("ascending"), h.Class(base)],
      [
        h.a(
          [
            h.Href(query(`-${column}`)),
            h.Class("flex items-center px-6 py-3 hover:text-foreground"),
          ],
          [options.label, h.span([h.AriaHidden(true), h.Class("ml-1")], ["▲"])]
        ),
      ]
    );
  }

  if (sort === `-${column}`) {
    return h.th(
      [h.Scope("col"), h.AriaSort("descending"), h.Class(base)],
      [
        h.a(
          [
            h.Href(query(column)),
            h.Class("flex items-center px-6 py-3 hover:text-foreground"),
          ],
          [options.label, h.span([h.AriaHidden(true), h.Class("ml-1")], ["▼"])]
        ),
      ]
    );
  }

  return h.th(
    [h.Scope("col"), h.AriaSort("none"), h.Class(base)],
    [
      h.a(
        [
          h.Href(query(column)),
          h.Class(
            "group flex items-center px-6 py-3 text-foreground-muted hover:text-foreground"
          ),
        ],
        [
          options.label,
          h.span(
            [
              h.AriaHidden(true),
              h.Class("ml-1 opacity-40 group-hover:opacity-70"),
            ],
            ["↕"]
          ),
        ]
      ),
    ]
  );
};

const newFacilitatorButton = (
  slug: string,
  translator: Translator,
  h: PanelH
) =>
  linkButton(
    {
      href: eventPath(slug, "facilitators/create/"),
      icon: plusOutline,
      text: translator.t("New Facilitator"),
    },
    h
  );

const facilitatorRow = (
  options: Readonly<{
    event: PanelCurrentEvent;
    model: FacilitatorsModel;
    row: FacilitatorRow;
    translator: Translator;
  }>,
  h: PanelH
) => {
  const { event, model, row, translator } = options;
  const { t } = translator;
  const checked = model.selected.includes(row.slug);
  const detailHref = eventPath(event.slug, `facilitators/${row.slug}/`);

  return h.tr(
    [h.Key(row.slug), h.Class("group/row hover:bg-bg-tertiary")],
    [
      h.td(
        [h.Class("px-6 py-4")],
        [
          bulkCheckbox(
            {
              ariaLabel: t("Select %(name)s", { name: row.displayName }),
              id: Option.none(),
              checked,
              onToggle: toList(
                FacilitatorListMessage.ToggledRow({
                  checked: !checked,
                  slug: row.slug,
                })
              ),
            },
            h
          ),
        ]
      ),
      ...model.columns.map((column, index) => {
        const value = cellValue(row, column, translator);

        return h.td(
          [
            h.Class(
              `px-6 py-4 whitespace-nowrap text-sm ${index === 0 ? "font-medium text-foreground" : "text-foreground-muted"}`
            ),
            h.Title(value),
          ],
          [
            index === 0
              ? h.a(
                  [
                    h.Href(detailHref),
                    h.DataAttribute("row-action", ""),
                    h.AriaLabel(row.displayName),
                    h.Class("text-primary hover:text-primary/80"),
                  ],
                  [truncate(value, 50)]
                )
              : truncate(value, 40),
          ]
        );
      }),
      h.td(
        [h.Class("px-6 py-4 whitespace-nowrap text-right text-sm font-medium")],
        [
          h.div(
            [h.Class("inline-flex items-center gap-3 justify-end")],
            [
              h.button(
                [
                  h.Type("button"),
                  h.Title(t("Delete")),
                  h.AriaLabel(t("Delete %(name)s", { name: row.displayName })),
                  h.Class(
                    "text-foreground-muted hover:text-danger inline-flex items-center"
                  ),
                  h.OnClick(
                    PanelMessage.RequestedConfirm({
                      action: PanelAction.DeleteFacilitator({
                        eventSlug: event.slug,
                        facilitatorSlug: row.slug,
                        next: model.listPath,
                      }),
                      prompt: {
                        confirmLabel: t("Delete"),
                        icon: "exclamation-triangle",
                        message: t(
                          "Delete %(name)s? They disappear from the program; you can restore them later.",
                          { name: row.displayName }
                        ),
                      },
                    })
                  ),
                ],
                [icon(trashOutline, { class: "w-4 h-4" }, h)]
              ),
              h.a(
                [
                  h.Href(
                    eventPath(event.slug, `facilitators/${row.slug}/edit/`)
                  ),
                  h.Class(
                    "text-primary hover:text-primary/80 inline-flex items-center"
                  ),
                ],
                [
                  icon(pencilSquareOutline, { class: "w-4 h-4 mr-1" }, h),
                  t("Edit"),
                ]
              ),
            ]
          ),
        ]
      ),
    ]
  );
};

const filtersActive = (model: FacilitatorsModel) =>
  model.filters.search !== "" ||
  model.filters.accreditation !== "" ||
  model.filters.organizer !== "";

export const facilitatorsView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    model: FacilitatorsModel;
    translator: Translator;
  }>,
  h: PanelH
): PanelPageView => {
  const { event, model, translator } = options;
  const { t } = translator;
  const active = filtersActive(model);

  const allChecked =
    model.rows.length > 0 && model.selected.length === model.rows.length;

  const noRows = () =>
    active
      ? [
          h.div(
            [h.Class("card p-8 text-center")],
            [
              h.p(
                [h.Class("text-foreground-muted mb-4")],
                [t("No facilitators match your filters.")]
              ),
              h.a(
                [h.Href(model.listPath), h.Class("btn btn-secondary text-sm")],
                [t("Clear filters")]
              ),
            ]
          ),
        ]
      : [
          h.div(
            [h.Class("card p-8 text-center")],
            [
              h.p(
                [h.Class("text-foreground-muted mb-4")],
                [t("No facilitators yet.")]
              ),
              newFacilitatorButton(event.slug, translator, h),
            ]
          ),
        ];

  const results =
    model.rows.length > 0
      ? [
          bulkToolbar(
            {
              actions: [
                { label: t("Delete"), variant: "danger" },
                { label: t("Mark as guest"), variant: "secondary" },
                { label: t("Merge selected"), variant: "secondary" },
              ],
              count: model.selected.length,
            },
            translator,
            h
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
                      h.thead(
                        [h.Class("bg-bg-tertiary")],
                        [
                          h.tr(
                            [],
                            [
                              h.th(
                                [h.Scope("col"), h.Class("px-6 py-3 w-12")],
                                [
                                  bulkCheckbox(
                                    {
                                      ariaLabel: t("Select all facilitators"),
                                      checked: allChecked,
                                      id: Option.some("bulk-select-all"),
                                      onToggle: toList(
                                        FacilitatorListMessage.ToggledAll({
                                          checked: !allChecked,
                                        })
                                      ),
                                    },
                                    h
                                  ),
                                ]
                              ),
                              ...model.columns.map((column) =>
                                sortHeader(
                                  {
                                    column,
                                    label: columnLabel(column, translator),
                                    model,
                                  },
                                  h
                                )
                              ),
                              h.th(
                                [
                                  h.Scope("col"),
                                  h.Class(
                                    "px-6 py-3 text-right text-xs font-medium text-foreground-muted uppercase tracking-wider"
                                  ),
                                ],
                                [t("Actions")]
                              ),
                            ]
                          ),
                        ]
                      ),
                      h.tbody(
                        [h.Class("divide-y divide-border")],
                        model.rows.map((row) =>
                          facilitatorRow({ event, model, row, translator }, h)
                        )
                      ),
                    ]
                  ),
                ]
              ),
            ]
          ),
        ]
      : noRows();

  return {
    content: [
      panelTabs(
        {
          active: "list",
          body: [
            ...(model.rows.length > 0 || active
              ? [filterBar(model, translator, h)]
              : []),
            h.div([h.Id("facilitators-results")], results),
          ],
          tabs: facilitatorTabs(event.slug, translator),
        },
        h
      ),
    ],
    header: header({
      actions: newFacilitatorButton(event.slug, translator, h),
      subtitle: [`${event.name} · ${t("Facilitators")}`],
      title: t("Facilitators"),
    }),
    title: t("Facilitators"),
  };
};

export const facilitatorBinView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    model: FacilitatorBinModel;
    translator: Translator;
  }>,
  h: PanelH
): PanelPageView => {
  const { event, model, translator } = options;
  const { t } = translator;

  const allChecked =
    model.rows.length > 0 && model.selected.length === model.rows.length;

  const th = (text: string, align: "left" | "right") =>
    h.th(
      [
        h.Scope("col"),
        h.Class(
          `px-6 py-3 text-${align} text-xs font-medium text-foreground-muted uppercase tracking-wider`
        ),
      ],
      [text]
    );

  const body =
    model.rows.length === 0
      ? [
          h.div(
            [h.Class("card p-8 text-center")],
            [
              h.p(
                [h.Class("text-foreground-muted")],
                [t("The bin is empty. Deleted facilitators land here.")]
              ),
            ]
          ),
        ]
      : [
          h.p(
            [h.Class("text-sm text-foreground-muted mb-4")],
            [
              t(
                "Deleted facilitators are off the program. Restore one to bring their byline back."
              ),
            ]
          ),
          bulkToolbar(
            {
              actions: [{ label: t("Restore"), variant: "secondary" }],
              count: model.selected.length,
            },
            translator,
            h
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
                      h.thead(
                        [h.Class("bg-bg-tertiary")],
                        [
                          h.tr(
                            [],
                            [
                              h.th(
                                [h.Scope("col"), h.Class("px-6 py-3 w-12")],
                                [
                                  bulkCheckbox(
                                    {
                                      ariaLabel: t("Select all facilitators"),
                                      checked: allChecked,
                                      id: Option.some("bulk-select-all"),
                                      onToggle: toList(
                                        FacilitatorListMessage.ToggledAll({
                                          checked: !allChecked,
                                        })
                                      ),
                                    },
                                    h
                                  ),
                                ]
                              ),
                              th(t("Name"), "left"),
                              th(t("Deleted"), "left"),
                              th(t("Actions"), "right"),
                            ]
                          ),
                        ]
                      ),
                      h.tbody(
                        [h.Class("divide-y divide-border")],
                        model.rows.map((row) => {
                          const checked = model.selected.includes(row.slug);

                          return h.tr(
                            [h.Key(row.slug), h.Class("hover:bg-bg-tertiary")],
                            [
                              h.td(
                                [h.Class("px-6 py-4")],
                                [
                                  bulkCheckbox(
                                    {
                                      ariaLabel: t("Select %(name)s", {
                                        name: row.displayName,
                                      }),
                                      checked,
                                      id: Option.none(),
                                      onToggle: toList(
                                        FacilitatorListMessage.ToggledRow({
                                          checked: !checked,
                                          slug: row.slug,
                                        })
                                      ),
                                    },
                                    h
                                  ),
                                ]
                              ),
                              h.td(
                                [
                                  h.Class(
                                    "px-6 py-4 whitespace-nowrap text-sm font-medium text-foreground"
                                  ),
                                ],
                                [
                                  h.a(
                                    [
                                      h.Href(
                                        eventPath(
                                          event.slug,
                                          `facilitators/${row.slug}/`
                                        )
                                      ),
                                      h.DataAttribute("row-action", ""),
                                      h.Class(
                                        "text-primary hover:text-primary/80"
                                      ),
                                    ],
                                    [row.displayName]
                                  ),
                                ]
                              ),
                              h.td(
                                [
                                  h.Class(
                                    "px-6 py-4 whitespace-nowrap text-sm text-foreground-muted"
                                  ),
                                ],
                                [row.deletedLabel]
                              ),
                              h.td(
                                [
                                  h.Class(
                                    "px-6 py-4 whitespace-nowrap text-right text-sm font-medium"
                                  ),
                                ],
                                [
                                  h.button(
                                    [
                                      h.Type("button"),
                                      h.AriaLabel(
                                        t("Restore %(name)s", {
                                          name: row.displayName,
                                        })
                                      ),
                                      h.Class("btn btn-secondary text-sm"),
                                      h.OnClick(
                                        PanelMessage.RequestedAction({
                                          action:
                                            PanelAction.RestoreFacilitator({
                                              eventSlug: event.slug,
                                              facilitatorSlug: row.slug,
                                              next: model.listPath,
                                            }),
                                        })
                                      ),
                                    ],
                                    [t("Restore")]
                                  ),
                                ]
                              ),
                            ]
                          );
                        })
                      ),
                    ]
                  ),
                ]
              ),
            ]
          ),
        ];

  return {
    content: [
      panelTabs(
        { active: "bin", body, tabs: facilitatorTabs(event.slug, translator) },
        h
      ),
    ],
    header: header({
      subtitle: [`${event.name} · ${t("Bin")}`],
      title: t("Facilitators"),
    }),
    title: `${t("Bin")} • ${t("Facilitators")}`,
  };
};

const detailItem = (
  options: Readonly<{
    hint?: string;
    term: string;
    value: readonly Child[];
    valueClass?: string;
  }>,
  h: PanelH
) =>
  h.div(
    [],
    [
      h.dt([h.Class("text-xs text-foreground-muted")], [options.term]),
      h.dd([h.Class(options.valueClass ?? "text-foreground")], options.value),
      options.hint === undefined
        ? h.empty
        : h.p([h.Class("mt-1 text-xs text-foreground-muted")], [options.hint]),
    ]
  );

const dash = (h: PanelH) => h.span([h.Class("text-foreground-muted")], ["—"]);

export const facilitatorDetailView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    page: FacilitatorDetailFlags;
    translator: Translator;
  }>,
  h: PanelH
): PanelPageView => {
  const { event, page, translator } = options;
  const { t } = translator;

  const detailTabs = [
    {
      href: eventPath(event.slug, `facilitators/${page.slug}/`),
      key: "details",
      label: t("Details"),
    },
    {
      href: eventPath(event.slug, `facilitators/${page.slug}/history/`),
      key: "history",
      label: t("Change history"),
    },
  ];

  const body = [
    page.isDeleted
      ? h.div(
          [
            h.Class(
              "mb-6 flex flex-wrap items-center gap-3 rounded-2xl border border-danger/30 bg-danger/5 p-4 text-sm"
            ),
          ],
          [
            h.span(
              [h.Class("text-danger")],
              [
                t(
                  "This facilitator is deleted — they show up nowhere in the program."
                ),
              ]
            ),
            button(
              {
                attributes: [
                  h.OnClick(
                    PanelMessage.RequestedAction({
                      action: PanelAction.RestoreFacilitator({
                        eventSlug: event.slug,
                        facilitatorSlug: page.slug,
                        next: eventPath(
                          event.slug,
                          `facilitators/${page.slug}/`
                        ),
                      }),
                    })
                  ),
                ],
                icon: arrowUturnLeftOutline,
                text: t("Restore"),
                type: "button",
                variant: "secondary",
              },
              h
            ),
          ]
        )
      : h.empty,
    h.div(
      [h.Class("card mb-6")],
      [
        h.div(
          [h.Class("card-body")],
          [
            h.h3(
              [h.Class("text-sm font-medium text-foreground-muted mb-4")],
              [t("Facilitator Details")]
            ),
            h.dl(
              [h.Class("space-y-3")],
              [
                detailItem(
                  {
                    hint: t(
                      "Cached name from the submission wizard. The canonical byline is the proposal's presenter name."
                    ),
                    term: t("Display Name"),
                    value: [page.displayName],
                  },
                  h
                ),
                detailItem(
                  {
                    term: t("Accreditation type"),
                    value: [
                      accreditationLabel(page.accreditationType, translator),
                    ],
                  },
                  h
                ),
                page.isCollective
                  ? detailItem(
                      {
                        hint: t(
                          "The timetable does not report overlapping program points of this facilitator as a clash."
                        ),
                        term: t("Runs program points in parallel"),
                        value: [t("Yes")],
                      },
                      h
                    )
                  : h.empty,
                detailItem(
                  {
                    term: t("Linked User"),
                    value: [page.linkedUser === "" ? dash(h) : page.linkedUser],
                  },
                  h
                ),
                detailItem({ term: t("Guild"), value: [dash(h)] }, h),
                detailItem(
                  {
                    hint: t(
                      "The organizer handling this facilitator. Take them on from the facilitator list."
                    ),
                    term: t("Organizer"),
                    value: [
                      page.organizerName === "" ? dash(h) : page.organizerName,
                    ],
                  },
                  h
                ),
                detailItem(
                  {
                    term: t("Slug"),
                    value: [page.slug],
                    valueClass:
                      "font-mono text-sm text-foreground-muted select-all",
                  },
                  h
                ),
                page.internalComment === ""
                  ? h.empty
                  : detailItem(
                      {
                        hint: t("Visible to organizers only."),
                        term: t("Internal comment"),
                        value: [page.internalComment],
                        valueClass:
                          "text-foreground whitespace-pre-line break-words",
                      },
                      h
                    ),
              ]
            ),
          ]
        ),
      ]
    ),
    h.div(
      [h.Class("card mb-6")],
      [
        h.div(
          [h.Class("card-body")],
          [
            h.h3(
              [h.Class("text-sm font-medium text-foreground-muted mb-4")],
              [t("Sessions")]
            ),
            page.sessions.length === 0
              ? h.p(
                  [h.Class("text-sm text-foreground-muted")],
                  [t("No sessions attached.")]
                )
              : h.ul(
                  [h.Class("space-y-2")],
                  page.sessions.map((session) =>
                    h.li(
                      [
                        h.Key(String(session.id)),
                        h.Class(
                          "flex items-center justify-between gap-3 text-sm"
                        ),
                      ],
                      [
                        h.a(
                          [
                            h.Href(
                              eventPath(event.slug, `proposals/${session.id}/`)
                            ),
                            h.Class("text-primary hover:underline truncate"),
                            h.Title(session.title),
                          ],
                          [session.title]
                        ),
                        h.span(
                          [h.Class("flex items-center gap-2 shrink-0")],
                          [
                            session.isDeleted
                              ? h.span(
                                  [
                                    h.Class(
                                      "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-danger-bg text-danger-text"
                                    ),
                                  ],
                                  [t("Deleted")]
                                )
                              : h.empty,
                            statusBadge(
                              {
                                isScheduled: session.isScheduled,
                                status: session.status,
                                translator,
                              },
                              h
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
  ];

  return {
    content: [panelTabs({ active: "details", body, tabs: detailTabs }, h)],
    header: header({
      ...(page.isDeleted
        ? { actions: h.div([], []) }
        : {
            actions: linkButton(
              {
                href: eventPath(event.slug, `facilitators/${page.slug}/edit/`),
                icon: pencilSquareOutline,
                text: t("Edit"),
              },
              h
            ),
          }),
      subtitle: crumbs(
        {
          backHref: eventPath(event.slug, "facilitators/"),
          backLabel: t("Facilitators"),
          eventName: event.name,
          eventSlug: event.slug,
        },
        h
      ),
      title: page.displayName,
    }),
    title: `${page.displayName} • ${t("Facilitators")}`,
  };
};

const toForm = (message: FacilitatorFormMessage) =>
  PanelMessage.RelayedFacilitatorForm({ message });

const checkboxFieldRow = (
  options: Readonly<{
    checked: boolean;
    help: string;
    id: string;
    label: string;
    name: string;
    onToggle: PanelMessage;
  }>,
  translator: Translator,
  h: PanelH
) =>
  h.div(
    [h.Class("flex flex-col gap-y-0.5 not-last:mb-4")],
    [
      h.label(
        [h.Class("inline-flex items-center cursor-pointer select-none")],
        [
          checkboxInput(
            {
              attributes: [h.OnClick(options.onToggle)],
              checked: options.checked,
              id: options.id,
              name: options.name,
            },
            h
          ),
          h.span([h.Class("ml-2 text-sm text-foreground")], [options.label]),
        ]
      ),
      ...helpAndErrors({ help: options.help, id: options.id }, h),
    ]
  );

export const facilitatorFormView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    model: FacilitatorFormModel;
    translator: Translator;
  }>,
  h: PanelH
): PanelPageView => {
  const { event, model, translator } = options;
  const { t } = translator;
  const isEdit = Option.isSome(model.facilitatorSlug);
  const formId = isEdit ? "facilitator-edit-form" : "facilitator-create-form";
  const nameErrors = errorsFor(model.errors, "display_name", translator);

  const accreditation = field(
    {
      control: selectInput(
        {
          attributes: [
            h.OnChange((value) =>
              toForm(FacilitatorFormMessage.ChangedAccreditation({ value }))
            ),
          ],
          errors: errorsFor(model.errors, "accreditation_type", translator),
          id: "id_accreditation_type",
          name: "accreditation_type",
          options: accreditationChoices(translator),
          selected: model.values.accreditationType,
        },
        h
      ),
      described: {
        errors: errorsFor(model.errors, "accreditation_type", translator),
        id: "id_accreditation_type",
      },
      label: t("Accreditation type"),
      translator,
    },
    h
  );

  const collective = checkboxFieldRow(
    {
      checked: model.values.isCollective,
      help: t(
        "For a guild or the organizer crew — the timetable stops reporting this facilitator's overlapping program points as a clash."
      ),
      id: "id_is_collective",
      label: t("Runs program points in parallel"),
      name: "is_collective",
      onToggle: toForm(
        FacilitatorFormMessage.ToggledCollective({
          checked: !model.values.isCollective,
        })
      ),
    },
    translator,
    h
  );

  const fields = isEdit
    ? [
        accreditation,
        collective,
        field(
          {
            control: textareaInput(
              {
                attributes: [
                  h.OnInput((value) =>
                    toForm(FacilitatorFormMessage.ChangedComment({ value }))
                  ),
                ],
                help: t("Visible to organizers only."),
                id: "id_internal_comment",
                name: "internal_comment",
                rows: 3,
                value: model.values.internalComment,
              },
              h
            ),
            described: {
              help: t("Visible to organizers only."),
              id: "id_internal_comment",
            },
            label: t("Internal comment"),
            translator,
          },
          h
        ),
      ]
    : [
        h.div(
          [],
          [
            h.label(
              [
                h.Class(
                  "block text-sm font-medium text-foreground-secondary mb-1"
                ),
                h.For("id_display_name"),
              ],
              [t("Display Name")]
            ),
            h.input([
              h.Type("text"),
              h.Name("display_name"),
              h.Id("id_display_name"),
              h.Value(model.values.displayName),
              h.Class(
                `w-full border ${nameErrors.length > 0 ? "border-danger" : "border-border"} rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-primary`
              ),
              h.Placeholder(t("e.g., Jan Kowalski")),
              h.OnInput((value) =>
                toForm(FacilitatorFormMessage.ChangedDisplayName({ value }))
              ),
            ]),
            ...nameErrors
              .slice(0, 1)
              .map((error) =>
                h.p([h.Class("mt-1 text-sm text-danger")], [error])
              ),
          ]
        ),
        accreditation,
        collective,
        checkboxFieldRow(
          {
            checked: model.values.assignMe,
            help: t("You handle this facilitator until you step down."),
            id: "id_assign_me",
            label: t("Assign me as organizer"),
            name: "assign_me",
            onToggle: toForm(
              FacilitatorFormMessage.ToggledAssignMe({
                checked: !model.values.assignMe,
              })
            ),
          },
          translator,
          h
        ),
      ];

  const form = h.form(
    [
      h.Id(formId),
      h.Method("post"),
      h.Class(isEdit ? "space-y-6" : "max-w-2xl"),
      h.OnSubmit(toForm(FacilitatorFormMessage.SubmittedFacilitatorForm())),
    ],
    isEdit
      ? [...formErrors(errorsFor(model.errors, "", translator), h), ...fields]
      : [
          ...formErrors(errorsFor(model.errors, "", translator), h),
          h.div(
            [h.Class("card")],
            [
              h.div(
                [h.Class("card-body")],
                [
                  h.h3(
                    [h.Class("text-lg font-semibold text-foreground mb-6")],
                    [t("Facilitator Details")]
                  ),
                  h.div([h.Class("space-y-6")], fields),
                ]
              ),
            ]
          ),
        ]
  );

  const content = isEdit
    ? h.div(
        [h.Class("card max-w-2xl")],
        [
          h.div(
            [h.Class("card-body")],
            [
              h.h3(
                [h.Class("text-lg font-semibold text-foreground mb-6")],
                [t("Facilitator Details")]
              ),
              h.div(
                [h.Class("space-y-6")],
                [
                  detailItem(
                    {
                      hint: t(
                        "Cached name from the submission wizard — edit the proposal's presenter name to change the byline."
                      ),
                      term: t("Display Name"),
                      value: [model.savedName],
                    },
                    h
                  ),
                  detailItem(
                    {
                      hint: t(
                        "The organizer handling this facilitator. Take them on from the facilitator list."
                      ),
                      term: t("Organizer"),
                      value: [
                        model.organizerName === ""
                          ? dash(h)
                          : model.organizerName,
                      ],
                    },
                    h
                  ),
                  form,
                ]
              ),
            ]
          ),
        ]
      )
    : form;

  const cancelHref = Option.match(model.facilitatorSlug, {
    onNone: () => eventPath(event.slug, "facilitators/"),
    onSome: (slug) => eventPath(event.slug, `facilitators/${slug}/`),
  });

  return {
    content: [h.div([h.Class("panel-bleed")], [content])],
    header: header({
      actions: h.div(
        [h.Class("flex items-center space-x-3")],
        [
          linkButton(
            { href: cancelHref, text: t("Cancel"), variant: "secondary" },
            h
          ),
          button(
            {
              attributes: [h.Attribute("form", formId)],
              disabled: model.isSaving,
              icon: isEdit ? checkOutline : plusOutline,
              text: isEdit ? t("Save") : t("Create Facilitator"),
            },
            h
          ),
        ]
      ),
      subtitle: [`${event.name} · ${t("Facilitators")}`],
      title: isEdit ? model.savedName : t("New Facilitator"),
    }),
    title: isEdit ? t("Edit Facilitator") : t("New Facilitator"),
  };
};
