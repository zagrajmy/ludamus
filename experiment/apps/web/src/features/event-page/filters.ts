import { Option } from "effect";
import type { Html, HtmlBuilder } from "foldkit/html";

import {
  comboboxBaseId,
  comboboxInputId,
  openFor,
  selectedLabel,
  shownOptions,
} from "../../client/event-page/combobox.js";
import {
  activeChips,
  statusLabel,
  statusValues,
} from "../../client/event-page/filters.js";
import type {
  ComboboxId,
  FlagId,
  SelectId,
} from "../../client/event-page/filters.js";
import { EventPageMessage } from "../../client/event-page/message.js";
import { showsBookmarked } from "../../client/event-page/model.js";
import type { EventPageModel } from "../../client/event-page/model.js";
import { cx } from "../../ui/cx.js";
import { icon } from "../../ui/icon.js";
import {
  adjustmentsHorizontalMini,
  checkMini,
  chevronUpDownMini,
  funnelOutline,
  magnifyingGlassMini,
  xMarkMini,
} from "../../ui/icons.js";
import type { PageContext } from "../page-context.js";

type H = HtmlBuilder<EventPageMessage>;

const LABEL_CLASS =
  "text-xs font-bold uppercase tracking-widest text-foreground-muted";

const SELECT_CLASS =
  "filter-input transition-[border-color,box-shadow] duration-150 w-full px-3 py-2 text-base sm:text-sm rounded-lg border border-border bg-bg-secondary text-foreground";

const group = (
  options: Readonly<{
    children: readonly Html[];
    extraClass?: string;
    hidden?: boolean;
    id?: string;
  }>,
  h: H
) =>
  h.div(
    [
      ...(options.id === undefined ? [] : [h.Id(options.id)]),
      h.Class(
        cx(
          "flex flex-col gap-1.5",
          options.extraClass,
          options.hidden === true && "hidden"
        )
      ),
    ],
    options.children
  );

const fieldLabel = (forId: string, text: string, h: H, id?: string) =>
  h.label(
    [
      ...(id === undefined ? [] : [h.Id(id)]),
      h.Class(LABEL_CLASS),
      h.For(forId),
    ],
    [text]
  );

const selectControl = (
  options: Readonly<{
    id: string;
    name?: string;
    onChange: (value: string) => EventPageMessage;
    options: readonly Readonly<{ label: string; value: string }>[];
    value: string;
  }>,
  h: H
) =>
  h.select(
    [
      h.Id(options.id),
      ...(options.name === undefined ? [] : [h.Name(options.name)]),
      h.Class(SELECT_CLASS),
      h.Value(options.value),
      h.OnChange(options.onChange),
    ],
    options.options.map((option) =>
      h.option(
        [
          h.Key(option.value),
          h.Value(option.value),
          h.Selected(option.value === options.value),
        ],
        [option.label]
      )
    )
  );

const flagToggle = (
  options: Readonly<{
    checked: boolean;
    id: FlagId;
    label: string;
    domId: string;
  }>,
  h: H
) =>
  h.label(
    [
      h.Class(
        "inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-bg-tertiary text-sm font-medium text-foreground whitespace-nowrap cursor-pointer select-none transition-colors duration-150 hover:bg-border has-checked:bg-primary-light has-checked:text-primary"
      ),
    ],
    [
      h.input([
        h.Type("checkbox"),
        h.Id(options.domId),
        h.Class(
          "w-4 h-4 rounded border border-border accent-primary shrink-0 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2"
        ),
        h.Checked(options.checked),
        h.OnChange(() =>
          EventPageMessage.ToggledFlag({
            checked: !options.checked,
            id: options.id,
          })
        ),
      ]),
      h.span([], [options.label]),
    ]
  );

const keyMessage = (id: ComboboxId, key: string, shiftKey: boolean) =>
  EventPageMessage.PressedComboboxKey({ id, key, shiftKey });

const combobox = (
  options: Readonly<{
    emptyText?: string;
    id: ComboboxId;
    label: string;
    model: EventPageModel;
    placeholder: string;
    toggleLabel?: string;
  }>,
  h: H
) => {
  const { id, model } = options;
  const baseId = comboboxBaseId(id);
  const inputId = comboboxInputId(id);
  const listboxId = `${baseId}-listbox`;
  const open = openFor(model.combobox, id);
  const isOpen = Option.isSome(open);
  const query = Option.flatMap(open, (state) => state.query);
  const shown = shownOptions({ choices: model.choices, id, query });

  const active = Option.match(open, {
    onNone: () => -1,
    onSome: (state) => state.active,
  });

  const selected = model.filters[id];

  const value = Option.getOrElse(query, () =>
    selectedLabel({ choices: model.choices, filters: model.filters, id })
  );

  return h.div(
    [
      h.Class("relative"),
      h.DataAttribute("combobox", ""),
      h.DataAttribute("combobox-multiple", ""),
      h.OnFocusLeave(EventPageMessage.BlurredCombobox({ id })),
    ],
    [
      h.input([
        h.Type("hidden"),
        h.Id(baseId),
        h.Value(JSON.stringify(selected)),
        h.DataAttribute("combobox-value", ""),
      ]),
      h.div(
        [h.DataAttribute("combobox-shell", "")],
        [
          h.input([
            h.Type("text"),
            h.Id(inputId),
            h.Role("combobox"),
            h.AriaAutocomplete("list"),
            h.AriaExpanded(isOpen),
            ...(isOpen ? [h.AriaControls(listboxId)] : []),
            ...(isOpen && active >= 0 && active < shown.length
              ? [h.AriaActiveDescendant(`${baseId}-option-${active}`)]
              : []),
            h.Placeholder(options.placeholder),
            h.Autocomplete("off"),
            h.Spellcheck(false),
            h.Value(value),
            h.DataAttribute("combobox-input", ""),
            h.Class(
              "w-full px-3 py-2 pr-9 text-base sm:text-sm rounded-lg border border-border bg-bg-secondary text-foreground placeholder:text-foreground-muted"
            ),
            h.OnClick(EventPageMessage.ClickedCombobox({ id })),
            h.OnInput((typed) =>
              EventPageMessage.TypedCombobox({ id, value: typed })
            ),
            h.OnKeyDownPreventDefault((key, modifiers) => {
              if (key === "ArrowDown" || key === "ArrowUp") {
                return Option.some(keyMessage(id, key, modifiers.shiftKey));
              }

              if ((key === "Enter" || key === "Escape") && isOpen) {
                return Option.some(keyMessage(id, key, modifiers.shiftKey));
              }

              return Option.none();
            }),
            h.OnKeyDown((key, modifiers) =>
              key === "Tab"
                ? keyMessage(id, key, modifiers.shiftKey)
                : EventPageMessage.CompletedFocus()
            ),
          ]),
          h.button(
            [
              h.Type("button"),
              h.Tabindex(-1),
              ...(options.toggleLabel === undefined
                ? []
                : [h.AriaLabel(options.toggleLabel)]),
              h.AriaExpanded(isOpen),
              h.DataAttribute("combobox-toggle", ""),
              h.Class(
                "absolute inset-y-0 right-0 flex items-center px-2.5 text-foreground-muted"
              ),
              h.OnClick(EventPageMessage.ClickedComboboxToggle({ id })),
            ],
            [icon(chevronUpDownMini, { class: "size-4" }, h)]
          ),
          h.div(
            [
              h.DataAttribute("combobox-popup", ""),
              h.Hidden(!isOpen),
              h.Class(
                "absolute left-0 right-0 top-full z-40 mt-1 overflow-hidden rounded-xl border border-border bg-bg-secondary shadow-xl"
              ),
            ],
            [
              h.div(
                [
                  h.DataAttribute("combobox-scroller", ""),
                  h.Class("max-h-56 overflow-y-auto"),
                ],
                [
                  h.ul(
                    [
                      h.Id(listboxId),
                      h.Role("listbox"),
                      h.AriaMultiSelectable(true),
                      h.AriaLabelledBy(`${baseId}-label`),
                      h.Tabindex(-1),
                      h.DataAttribute("combobox-listbox", ""),
                      h.Class("py-1"),
                    ],
                    isOpen
                      ? shown.map((choice, index) => {
                          const isChosen = selected.includes(choice.value);

                          return h.li(
                            [
                              h.Key(choice.value),
                              h.Id(`${baseId}-option-${index}`),
                              h.Role("option"),
                              h.AriaSelected(isChosen),
                              ...(index === active
                                ? [h.DataAttribute("active", "")]
                                : []),
                              ...(isChosen
                                ? [h.DataAttribute("chosen", "")]
                                : []),
                              h.Class(
                                "group flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-foreground data-[active]:bg-bg-tertiary data-[chosen]:font-semibold"
                              ),
                              h.OnPointerMove(() =>
                                index === active
                                  ? Option.none()
                                  : Option.some(
                                      EventPageMessage.HoveredOption({
                                        id,
                                        index,
                                      })
                                    )
                              ),
                              h.OnPointerUp((_x, _y, pointerType) =>
                                Option.some(
                                  EventPageMessage.PickedOption({
                                    id,
                                    pointerType,
                                    value: choice.value,
                                  })
                                )
                              ),
                            ],
                            [
                              h.span(
                                [
                                  h.DataAttribute("combobox-option-label", ""),
                                  h.Class("grow truncate"),
                                ],
                                [choice.label]
                              ),
                              icon(
                                checkMini,
                                {
                                  class:
                                    "size-4 text-primary opacity-0 group-data-[chosen]:opacity-100",
                                },
                                h
                              ),
                            ]
                          );
                        })
                      : []
                  ),
                ]
              ),
              h.p(
                [
                  h.AriaHidden(true),
                  h.Hidden(shown.length > 0),
                  h.DataAttribute("combobox-empty", ""),
                  h.Class("px-3 py-2 text-sm text-foreground-muted"),
                ],
                [options.emptyText ?? ""]
              ),
            ]
          ),
        ]
      ),
    ]
  );
};

const comboGroup = (
  options: Readonly<{
    emptyText?: string;
    groupId?: string;
    hidden?: boolean;
    id: ComboboxId;
    label: string;
    model: EventPageModel;
    placeholder: string;
    toggleLabel?: string;
  }>,
  h: H
) =>
  group(
    {
      children: [
        fieldLabel(
          comboboxInputId(options.id),
          options.label,
          h,
          `${comboboxBaseId(options.id)}-label`
        ),
        combobox(options, h),
      ],
      extraClass: "grow",
      ...(options.groupId === undefined ? {} : { id: options.groupId }),
      ...(options.hidden === undefined ? {} : { hidden: options.hidden }),
    },
    h
  );

const panelBody = (model: EventPageModel, context: PageContext, h: H) => {
  const { translator } = context;
  const { choices, filters } = model;

  const selectChange = (id: SelectId) => (value: string) =>
    EventPageMessage.ChangedSelect({ id, value });

  return h.div(
    [
      h.Class(
        "filter-panel-body flex flex-wrap gap-3 grow pt-3.5 max-[30rem]:flex-auto max-[30rem]:min-h-0 max-[30rem]:overflow-y-auto max-[30rem]:overscroll-contain max-[30rem]:px-6 max-[30rem]:py-4"
      ),
    ],
    [
      h.div(
        [h.Class("w-full flex flex-wrap gap-2")],
        [
          model.hasEnrollableSessions
            ? flagToggle(
                {
                  checked: filters.enrollment,
                  domId: "enrollment-filter",
                  id: "enrollment",
                  label: translator.t("Only with enrollment"),
                },
                h
              )
            : h.empty,
          flagToggle(
            {
              checked: filters.hideEnded,
              domId: "hide-ended-filter",
              id: "hideEnded",
              label: translator.t("Hide ended"),
            },
            h
          ),
        ]
      ),
      group(
        {
          children: [
            fieldLabel("status-filter", translator.t("Status"), h),
            selectControl(
              {
                id: "status-filter",
                onChange: selectChange("status"),
                options: [
                  { label: translator.t("All statuses"), value: "" },
                  ...statusValues({
                    showBookmarked: showsBookmarked(model),
                  }).map((value) => ({
                    label: statusLabel(value, translator),
                    value,
                  })),
                ],
                value: filters.status,
              },
              h
            ),
          ],
        },
        h
      ),
      comboGroup(
        {
          groupId: "space-filter-group",
          hidden:
            choices.spaces.filter((space) => !space.value.startsWith("venue:"))
              .length < 2,
          id: "space",
          label: translator.t("Location"),
          model,
          placeholder: translator.t("Search locations…"),
        },
        h
      ),
      h.div(
        [h.Class("flex gap-3")],
        [
          group(
            {
              children: [
                fieldLabel("age-filter", translator.t("Participant age"), h),
                h.input([
                  h.Type("number"),
                  h.Name("age"),
                  h.Id("age-filter"),
                  h.Min("0"),
                  h.Max("99"),
                  h.Value(filters.age),
                  h.Class(SELECT_CLASS),
                  h.OnInput((value) => EventPageMessage.ChangedAge({ value })),
                ]),
              ],
              extraClass: "grow",
            },
            h
          ),
          group(
            {
              children: [
                fieldLabel("min-age-filter", translator.t("Age from"), h),
                selectControl(
                  {
                    id: "min-age-filter",
                    name: "age-min",
                    onChange: selectChange("ageMin"),
                    options: [
                      { label: translator.t("Any age"), value: "" },
                      ...choices.minAges.map((age) => ({
                        label: `${age}+`,
                        value: String(age),
                      })),
                    ],
                    value: filters.ageMin,
                  },
                  h
                ),
              ],
              extraClass: "grow",
              hidden: choices.minAgesDistinct < 2,
              id: "min-age-filter-group",
            },
            h
          ),
        ]
      ),
      h.div(
        [
          h.Id("day-hour-filter-group"),
          h.Class(
            cx(
              "flex gap-3 grow",
              choices.days.length < 2 && choices.hours.length < 2 && "hidden"
            )
          ),
        ],
        [
          group(
            {
              children: [
                fieldLabel("day-filter", translator.t("Day"), h),
                selectControl(
                  {
                    id: "day-filter",
                    onChange: selectChange("day"),
                    options: [
                      { label: translator.t("All days"), value: "" },
                      ...choices.days,
                    ],
                    value: filters.day,
                  },
                  h
                ),
              ],
              extraClass: "grow",
              hidden: choices.days.length < 2,
              id: "day-filter-group",
            },
            h
          ),
          group(
            {
              children: [
                fieldLabel("hour-filter", translator.t("Hour"), h),
                selectControl(
                  {
                    id: "hour-filter",
                    onChange: selectChange("hour"),
                    options: [
                      { label: translator.t("All hours"), value: "" },
                      ...choices.hours.map((hour) => ({
                        label: hour,
                        value: hour,
                      })),
                    ],
                    value: filters.hour,
                  },
                  h
                ),
              ],
              extraClass: "grow",
              hidden: choices.hours.length < 2,
              id: "hour-filter-group",
            },
            h
          ),
        ]
      ),
      choices.tracks.length === 0
        ? h.empty
        : comboGroup(
            {
              id: "track",
              label: translator.t("Track"),
              model,
              placeholder: translator.t("Search tracks…"),
            },
            h
          ),
      choices.categories.length === 0
        ? h.empty
        : comboGroup(
            {
              id: "category",
              label: translator.tc("participant filter", "Category"),
              model,
              placeholder: translator.tc(
                "participant filter",
                "Search categories…"
              ),
            },
            h
          ),
      h.div(
        [h.Id("tag-filters"), h.Class("contents")],
        choices.tagFields.map((field) =>
          group(
            {
              children: [
                fieldLabel(`tag-filter-${field.slug}`, field.name, h),
                h.select(
                  [
                    h.Id(`tag-filter-${field.slug}`),
                    h.DataAttribute("category", field.slug),
                    h.Class(cx(SELECT_CLASS, "tag-filter")),
                    h.Value(
                      filters.tags.find((tag) => tag.slug === field.slug)
                        ?.value ?? ""
                    ),
                    h.OnChange((value) =>
                      EventPageMessage.ChangedTag({ slug: field.slug, value })
                    ),
                  ],
                  [
                    h.option(
                      [h.Key(""), h.Value("")],
                      [`${translator.t("All")} ${field.name}`]
                    ),
                    ...field.options.map((option) =>
                      h.option(
                        [
                          h.Key(option),
                          h.Value(option),
                          h.Selected(
                            filters.tags.some(
                              (tag) =>
                                tag.slug === field.slug && tag.value === option
                            )
                          ),
                        ],
                        [option]
                      )
                    ),
                  ]
                ),
              ],
              extraClass: "grow",
            },
            h
          )
        )
      ),
      comboGroup(
        {
          emptyText: translator.t("No host matches your search."),
          groupId: "host-filter-group",
          hidden: choices.hosts.length < 2,
          id: "host",
          label: translator.t("Host"),
          model,
          placeholder: translator.t("Search hosts…"),
          toggleLabel: translator.t("Show hosts"),
        },
        h
      ),
    ]
  );
};

const focusGuard = (selector: string, h: H) =>
  h.span(
    [
      h.Tabindex(0),
      h.Class("sr-only"),
      h.AriaHidden(true),
      h.OnFocus(EventPageMessage.FocusedGuard({ selector })),
    ],
    []
  );

const filterPanel = (model: EventPageModel, context: PageContext, h: H) => {
  const isDialog = model.isNarrow && model.isPanelOpen;

  return h.div(
    [
      h.Id("filter-panel"),
      h.Class(cx("filter-panel", model.isPanelOpen && "is-open")),
      ...(isDialog
        ? [
            h.Role("dialog"),
            h.AriaModal(true),
            h.AriaLabelledBy("filter-sheet-title"),
          ]
        : []),
    ],
    [
      isDialog ? focusGuard("#filter-apply", h) : h.empty,
      h.div(
        [
          h.Class(
            "filter-sheet-header items-center justify-between gap-3 px-6 py-4 border-b border-border"
          ),
        ],
        [
          h.h2(
            [h.Id("filter-sheet-title"), h.Class(LABEL_CLASS)],
            [context.translator.t("Filters")]
          ),
          h.button(
            [
              h.Type("button"),
              h.Id("filter-close"),
              h.Class("icon-btn"),
              h.AriaLabel(context.translator.t("Close filters")),
              h.OnClick(EventPageMessage.ClickedCloseFilters()),
            ],
            [icon(xMarkMini, { class: "w-5 h-5" }, h)]
          ),
        ]
      ),
      panelBody(model, context, h),
      h.div(
        [h.Class("filter-sheet-footer px-6 py-4 border-t border-border")],
        [
          h.button(
            [
              h.Type("button"),
              h.Id("filter-apply"),
              h.Class("btn btn-primary px-4 py-2 text-sm"),
              h.OnClick(EventPageMessage.ClickedApplyFilters()),
            ],
            [
              h.span(
                [h.Class("btn-label")],
                [context.translator.t("Apply filters")]
              ),
            ]
          ),
        ]
      ),
      isDialog ? focusGuard("#filter-close", h) : h.empty,
    ]
  );
};

export const filterToolbar = (
  options: Readonly<{
    context: PageContext;
    model: EventPageModel;
    viewTabs: Html;
  }>,
  h: H
): Html => {
  const { context, model } = options;
  const { translator } = context;

  const chips = activeChips({
    choices: model.choices,
    filters: model.filters,
    translator,
  });

  const placeholder = translator.t("Search by name or text...");

  return h.div(
    [h.Class("mb-3 print:hidden")],
    [
      h.div(
        [h.Class("flex gap-1 sm:gap-2 items-stretch")],
        [
          h.div(
            [h.Class("relative flex-1")],
            [
              h.span(
                [
                  h.Class(
                    "absolute left-3.5 top-1/2 -translate-y-1/2 text-foreground-muted"
                  ),
                ],
                [icon(magnifyingGlassMini, { class: "w-5 h-5" }, h)]
              ),
              h.input([
                h.Type("text"),
                h.Class(
                  "filter-input w-full pl-11 pr-4 py-2.5 sm:py-3 rounded-2xl border border-border text-sm font-medium bg-bg-secondary text-foreground placeholder:text-foreground-muted placeholder:font-normal transition-[border-color,box-shadow] duration-150"
                ),
                h.Id("session-filter"),
                h.Placeholder(placeholder),
                h.AriaLabel(placeholder),
                h.Autocomplete("off"),
                h.Value(model.filters.q),
                h.OnInput((value) => EventPageMessage.ChangedSearch({ value })),
              ]),
            ]
          ),
          h.div(
            [h.Class("filters-popover-wrapper relative overflow-visible")],
            [
              h.button(
                [
                  h.Type("button"),
                  h.Class(
                    "filter-toggle filter-toggle-anchor inline-flex h-full items-center gap-2 p-2.5 sm:p-3 rounded-2xl text-sm font-semibold border border-border whitespace-nowrap cursor-pointer bg-bg-secondary text-foreground-muted transition-[color,background-color,border-color,box-shadow] duration-150"
                  ),
                  h.Id("filter-toggle"),
                  h.AriaExpanded(model.isPanelOpen),
                  h.AriaControls("filter-panel"),
                  h.AriaLabel(translator.t("Filters")),
                  h.OnClick(EventPageMessage.ClickedFiltersToggle()),
                ],
                [
                  h.span(
                    [h.Class("hidden sm:inline")],
                    [translator.t("Filters")]
                  ),
                  icon(adjustmentsHorizontalMini, { class: "w-5 h-5" }, h),
                  h.span(
                    [
                      h.Id("active-filter-count"),
                      h.Class(
                        cx(
                          "filter-badge hidden min-w-5 h-5 px-1.5 rounded-full text-[0.6875rem] font-bold leading-5 text-center bg-primary text-white",
                          chips.length > 0 && "is-visible"
                        )
                      ),
                    ],
                    chips.length > 0 ? [String(chips.length)] : []
                  ),
                ]
              ),
              filterPanel(model, context, h),
              h.div(
                [
                  h.Class("filter-sheet-backdrop"),
                  h.DataAttribute("filter-backdrop", ""),
                  h.OnClick(EventPageMessage.ClickedCloseFilters()),
                ],
                []
              ),
            ]
          ),
          options.viewTabs,
        ]
      ),
      h.div(
        [
          h.Id("active-filter-chips"),
          h.Class(cx("filter-chips-bar", chips.length > 0 && "has-chips")),
        ],
        [
          h.div(
            [h.Class("overflow-hidden")],
            [
              h.div(
                [
                  h.Class("filter-chips-bar-inner"),
                  h.DataAttribute("filter-chips-inner", ""),
                ],
                chips.length === 0
                  ? []
                  : [
                      ...chips.map(({ chip, label }) =>
                        h.span(
                          [
                            h.Key(`${chip._tag}-${label}`),
                            h.Class("filter-chip"),
                          ],
                          [
                            label,
                            h.button(
                              [
                                h.Type("button"),
                                h.AriaLabel(
                                  `${translator.t("Remove filter")}: ${label}`
                                ),
                                h.OnClick(
                                  EventPageMessage.ClickedRemoveChip({ chip })
                                ),
                              ],
                              ["×"]
                            ),
                          ]
                        )
                      ),
                      h.button(
                        [
                          h.Type("button"),
                          h.Key("clear-all"),
                          h.Class("filter-chips-clear"),
                          h.OnClick(EventPageMessage.ClickedClearAll()),
                        ],
                        [translator.t("Clear all")]
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

export const noResults = (
  options: Readonly<{ context: PageContext; isShown: boolean }>,
  h: H
) =>
  h.div(
    [
      h.Id("filter-no-results"),
      h.Class("text-center py-12 px-4 text-foreground-muted"),
      h.Hidden(!options.isShown),
    ],
    [
      icon(funnelOutline, { class: "w-8 h-8 mx-auto mb-2" }, h),
      h.p(
        [h.Class("font-medium")],
        [options.context.translator.t("No sessions match your filters")]
      ),
      h.button(
        [
          h.Type("button"),
          h.Id("clear-filters-from-no-results"),
          h.Class("text-sm mt-2 font-semibold text-primary"),
          h.OnClick(EventPageMessage.ClickedClearAll()),
        ],
        [options.context.translator.t("Clear all filters")]
      ),
    ]
  );
