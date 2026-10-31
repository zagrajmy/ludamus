import { Option } from "effect";

import type { PanelCurrentEvent } from "../../../client/panel/chrome.js";
import { errorsFor } from "../../../client/panel/failure.js";
import { PanelMessage } from "../../../client/panel/message.js";
import { ProposalFormMessage } from "../../../client/panel/proposals/message.js";
import type { ProposalFormModel } from "../../../client/panel/proposals/model.js";
import { button, linkButton } from "../../../ui/button.js";
import { cx } from "../../../ui/cx.js";
import {
  field,
  formErrors,
  label,
  textInput,
  textareaInput,
} from "../../../ui/form.js";
import type { Described } from "../../../ui/form.js";
import type { Translator } from "../../../ui/i18n.js";
import { icon } from "../../../ui/icon.js";
import {
  arrowUpTrayOutline,
  checkOutline,
  plusOutline,
  xMarkOutline,
} from "../../../ui/icons.js";
import { header } from "../page.js";
import type { PanelH, PanelPageView } from "../page.js";

const toForm = (message: ProposalFormMessage) =>
  PanelMessage.RelayedProposalForm({ message });

export const IMAGE_ACCEPT = "image/jpeg,image/png,image/webp,image/avif";

const textField = (
  options: Readonly<{
    help?: string;
    label: string;
    model: ProposalFormModel;
    name: string;
    required?: boolean;
    translator: Translator;
    type?: string;
    value: string;
    valueKey: string;
  }>,
  h: PanelH
) => {
  const errors = errorsFor(
    options.model.errors,
    options.name,
    options.translator
  );

  const id = `id_${options.name}`;
  const described: Described = Option.match(
    Option.fromNullishOr(options.help),
    {
      onNone: () => ({ errors, id }),
      onSome: (help) => ({ errors, help, id }),
    }
  );

  return field(
    {
      control: textInput(
        {
          ...described,
          attributes: [
            h.OnInput((value) =>
              toForm(
                ProposalFormMessage.ChangedText({
                  name: options.valueKey,
                  value,
                })
              )
            ),
          ],
          name: options.name,
          type: options.type ?? "text",
          value: options.value,
        },
        h
      ),
      described,
      label: options.label,
      required: options.required ?? false,
      translator: options.translator,
    },
    h
  );
};

const coverDropzone = (
  model: ProposalFormModel,
  translator: Translator,
  h: PanelH
) => {
  const { t } = translator;

  const shown = Option.match(model.cover, {
    onNone: () =>
      model.coverCleared || model.coverUrl === ""
        ? Option.none()
        : Option.some({ name: model.coverName, url: model.coverUrl }),
    onSome: (cover) => Option.some({ name: cover.name, url: cover.dataUrl }),
  });

  const state = Option.isSome(shown) ? "image" : "empty";
  const errors = errorsFor(model.errors, "cover_image", translator);

  const help = t(
    "1920×1080 (16:9) works best. We crop the top and bottom, so keep the subject in the middle and leave text out. Max 8 MB. JPG, PNG, WebP, or AVIF."
  );

  return h.div(
    [h.Class("flex flex-col gap-y-0.5 not-last:mb-4")],
    [
      label({ forId: "id_cover_image", text: t("Cover image"), translator }, h),
      h.label(
        [
          h.For("id_cover_image"),
          h.DataAttribute("dropzone", ""),
          h.DataAttribute("state", state),
          h.Class(
            "group relative flex flex-col w-full items-center justify-center cursor-pointer overflow-hidden has-[input[aria-invalid=true]]:border-danger min-h-44 sm:min-h-48 px-4 py-6 bg-bg-tertiary border border-border rounded-lg transition-colors hover:bg-bg-secondary hover:border-primary/40 data-[state=image]:min-h-0 data-[state=image]:aspect-video"
          ),
        ],
        [
          h.input([
            h.Type("file"),
            h.Id("id_cover_image"),
            h.Name("cover_image"),
            h.DataAttribute("dropzone-input", ""),
            h.AriaLabel(t("Cover image")),
            h.AriaInvalid(errors.length > 0),
            h.Accept(IMAGE_ACCEPT),
            h.Class("absolute inset-0 w-full h-full opacity-0 cursor-pointer"),
            h.OnFileChange((files) =>
              toForm(ProposalFormMessage.PickedCover({ files }))
            ),
          ]),
          h.div(
            [
              h.DataAttribute("dropzone-empty", ""),
              h.Class(
                cx(
                  "pointer-events-none flex-col items-center text-center",
                  state === "empty" ? "flex" : "hidden"
                )
              ),
            ],
            [
              h.span(
                [
                  h.Class(
                    "mb-3 inline-flex items-center justify-center w-11 h-11 rounded-full bg-bg-secondary text-foreground-secondary border border-border"
                  ),
                ],
                [icon(arrowUpTrayOutline, { class: "w-5 h-5" }, h)]
              ),
              h.p(
                [h.Class("text-sm text-foreground")],
                [
                  h.span(
                    [h.Class("font-semibold text-primary")],
                    [t("Click to upload")]
                  ),
                  " ",
                  h.span(
                    [h.Class("text-foreground-secondary")],
                    [t("or drag and drop")]
                  ),
                ]
              ),
              ...errors
                .slice(0, 1)
                .map((error) =>
                  h.p(
                    [
                      h.DataAttribute("dropzone-error", ""),
                      h.Class("mt-2 text-sm font-medium text-danger"),
                    ],
                    [error]
                  )
                ),
            ]
          ),
          ...Option.match(shown, {
            onNone: () => [],
            onSome: (image) => [
              h.div(
                [
                  h.DataAttribute("dropzone-selected", ""),
                  h.Class(
                    "pointer-events-none absolute -inset-px z-10 block rounded-[inherit] overflow-hidden"
                  ),
                ],
                [
                  h.img([
                    h.DataAttribute("dropzone-preview", ""),
                    h.Src(image.url),
                    h.Alt(""),
                    h.Width("800"),
                    h.Height("400"),
                    h.Class("absolute inset-0 w-full h-full object-cover"),
                  ]),
                  h.div(
                    [
                      h.Class(
                        "absolute inset-x-0 bottom-0 flex items-baseline justify-between gap-3 pt-28 pb-2 px-3 scrim-t"
                      ),
                    ],
                    [
                      h.p(
                        [
                          h.DataAttribute("dropzone-name", ""),
                          h.Class(
                            "min-w-0 truncate text-sm font-medium text-white"
                          ),
                        ],
                        [image.name]
                      ),
                    ]
                  ),
                  h.div(
                    [
                      h.DataAttribute("dropzone-safe-zone", ""),
                      h.AriaHidden(true),
                      h.Class(
                        "pointer-events-none absolute inset-y-[36%] rounded-sm border border-dashed border-white/70 drop-shadow-[0_0_1px_rgba(0,0,0,0.7)] inset-x-[2%]"
                      ),
                    ],
                    []
                  ),
                  h.button(
                    [
                      h.Type("button"),
                      h.DataAttribute("dropzone-clear", ""),
                      h.Class(
                        "pointer-events-auto absolute top-2 right-2 p-1.5 rounded-md text-white hover:bg-white/15 transition-colors shrink-0"
                      ),
                      h.AriaLabel(t("Remove image")),
                      h.OnClick(toForm(ProposalFormMessage.ClearedCover())),
                    ],
                    [icon(xMarkOutline, { class: "w-4 h-4" }, h)]
                  ),
                ]
              ),
            ],
          }),
        ]
      ),
      h.p(
        [
          h.Id("id_cover_image_help"),
          h.Class("text-xs mt-1 text-foreground-muted"),
        ],
        [help]
      ),
    ]
  );
};

const checkboxRow = (
  options: Readonly<{
    checked: boolean;
    hidden?: boolean;
    label: string;
    name: string;
    onToggle: PanelMessage;
    value: number;
  }>,
  h: PanelH
) =>
  h.label(
    [
      h.Key(`${options.name}-${options.value}`),
      h.Class(
        cx(
          "flex items-center gap-2 text-sm py-3 rounded-md hover:bg-foreground/5",
          options.hidden === true && "hidden"
        )
      ),
    ],
    [
      h.input([
        h.Type("checkbox"),
        h.Name(options.name),
        h.Value(String(options.value)),
        h.Checked(options.checked),
        h.Class(
          "w-4 h-4 rounded border border-border accent-primary shrink-0 cursor-pointer"
        ),
        h.OnClick(options.onToggle),
      ]),
      options.label,
    ]
  );

const facilitatorCard = (
  model: ProposalFormModel,
  translator: Translator,
  h: PanelH
) => {
  const { t } = translator;
  const query = model.facilitatorSearch.toLowerCase().trim();

  const matches = model.facilitators.filter(
    (facilitator) =>
      query !== "" && facilitator.name.toLowerCase().includes(query)
  );

  const isNew = Option.isNone(model.proposalId);

  if (model.facilitators.length === 0) {
    return isNew
      ? h.div(
          [h.Class("card")],
          [
            h.div(
              [h.Class("card-body")],
              [
                h.h3(
                  [h.Class("text-lg font-semibold text-foreground mb-2")],
                  [
                    t("Facilitators"),
                    h.span([h.Class("text-danger ml-0.5")], ["*"]),
                  ]
                ),
                h.p(
                  [h.Class("text-sm text-foreground-muted")],
                  [
                    t("This event has no facilitators yet."),
                    h.a(
                      [
                        h.Href(
                          `/panel/event/${model.eventSlug}/facilitators/create/`
                        ),
                        h.Target("_blank"),
                        h.Rel("noopener"),
                        h.Class(
                          "text-primary underline hover:no-underline ml-1"
                        ),
                      ],
                      [t("Create one first")]
                    ),
                  ]
                ),
              ]
            ),
          ]
        )
      : h.empty;
  }

  return h.div(
    [h.Class("card")],
    [
      h.div(
        [h.Class("card-body")],
        [
          h.h3(
            [h.Class("text-lg font-semibold text-foreground mb-2")],
            [
              t("Facilitators"),
              ...(isNew
                ? [h.span([h.Class("text-danger ml-0.5")], ["*"])]
                : []),
            ]
          ),
          h.div(
            [h.Class("mb-4")],
            [
              textInput(
                {
                  attributes: [
                    h.AriaLabel(t("Search facilitators by name")),
                    h.OnInput((value) =>
                      toForm(
                        ProposalFormMessage.ChangedFacilitatorSearch({ value })
                      )
                    ),
                  ],
                  autocomplete: "off",
                  id: "facilitator-search",
                  name: "",
                  placeholder: t("Search by name…"),
                  value: model.facilitatorSearch,
                },
                h
              ),
            ]
          ),
          h.div(
            [h.Class("space-y-2"), h.Id("facilitator-list")],
            model.facilitators.map((facilitator) => {
              const checked = model.values.facilitatorIds.includes(
                facilitator.id
              );

              return checkboxRow(
                {
                  checked,
                  hidden:
                    !checked &&
                    !matches.some((match) => match.id === facilitator.id),
                  label: facilitator.name,
                  name: "facilitator_ids",
                  onToggle: toForm(
                    ProposalFormMessage.ToggledFacilitator({
                      checked: !checked,
                      id: facilitator.id,
                    })
                  ),
                  value: facilitator.id,
                },
                h
              );
            })
          ),
          query !== "" && matches.length === 0
            ? h.p(
                [
                  h.Id("no-facilitators-found"),
                  h.Class("text-sm text-foreground-muted mt-2"),
                ],
                [t("No facilitators match your search.")]
              )
            : h.empty,
        ]
      ),
    ]
  );
};

export const proposalFormView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    model: ProposalFormModel;
    translator: Translator;
  }>,
  h: PanelH
): PanelPageView => {
  const { event, model, translator } = options;
  const { t } = translator;
  const isEdit = Option.isSome(model.proposalId);
  const categoryErrors = errorsFor(model.errors, "category_id", translator);
  const nonField = errorsFor(model.errors, "", translator);

  const text = (
    name: string,
    valueKey: keyof ProposalFormModel["values"],
    labelText: string,
    extra: Readonly<{ help?: string; required?: boolean; type?: string }> = {}
  ) =>
    textField(
      {
        ...extra,
        label: labelText,
        model,
        name,
        translator,
        value: String(model.values[valueKey]),
        valueKey,
      },
      h
    );

  const details = h.div(
    [h.Class("card")],
    [
      h.div(
        [h.Class("card-body")],
        [
          h.h3(
            [h.Class("text-lg font-semibold text-foreground mb-2")],
            [t("Proposal Details")]
          ),
          h.div(
            [h.Class("space-y-6")],
            [
              h.div(
                [],
                [text("title", "title", t("Title"), { required: true })]
              ),
              h.div(
                [],
                [
                  h.div(
                    [h.Class("flex items-center gap-1 mb-1")],
                    [
                      label(
                        {
                          forId: "id_category_id",
                          required: true,
                          text: t("Category"),
                          translator,
                        },
                        h
                      ),
                    ]
                  ),
                  h.select(
                    [
                      h.Name("category_id"),
                      h.Id("id_category_id"),
                      h.Class(
                        "w-full px-3 py-2 text-base sm:text-sm rounded-lg border border-border aria-invalid:border-danger bg-bg-secondary text-foreground"
                      ),
                      ...(categoryErrors.length > 0
                        ? [
                            h.AriaInvalid(true),
                            h.AriaDescribedBy("id_category_id_errors"),
                          ]
                        : []),
                      h.OnChange((value) =>
                        toForm(
                          ProposalFormMessage.ChangedText({
                            name: "categoryId",
                            value,
                          })
                        )
                      ),
                    ],
                    [
                      h.option(
                        [
                          h.Value(""),
                          ...(model.values.categoryId === ""
                            ? [h.Selected(true)]
                            : []),
                        ],
                        [t("— Select category —")]
                      ),
                      ...model.categories.map((category) =>
                        h.option(
                          [
                            h.Value(String(category.id)),
                            ...(model.values.categoryId === String(category.id)
                              ? [h.Selected(true)]
                              : []),
                          ],
                          [category.name]
                        )
                      ),
                    ]
                  ),
                  ...categoryErrors
                    .slice(0, 1)
                    .map((error) =>
                      h.p(
                        [
                          h.Id("id_category_id_errors"),
                          h.Class("text-xs mt-1 text-danger"),
                        ],
                        [error]
                      )
                    ),
                ]
              ),
              h.div([], [coverDropzone(model, translator, h)]),
              h.div(
                [h.Class("grid grid-cols-1 md:grid-cols-2 gap-4")],
                [
                  h.div(
                    [],
                    [
                      text(
                        "facilitator_name",
                        "facilitatorName",
                        t("Presenter name"),
                        { required: true }
                      ),
                    ]
                  ),
                  h.div(
                    [],
                    [
                      text(
                        "contact_email",
                        "contactEmail",
                        t("Contact Email"),
                        { type: "email" }
                      ),
                    ]
                  ),
                ]
              ),
              h.div(
                [],
                [
                  field(
                    {
                      control: textareaInput(
                        {
                          attributes: [
                            h.OnInput((value) =>
                              toForm(
                                ProposalFormMessage.ChangedText({
                                  name: "description",
                                  value,
                                })
                              )
                            ),
                          ],
                          help: t("Supports Markdown formatting."),
                          id: "id_description",
                          name: "description",
                          rows: 5,
                          value: model.values.description,
                        },
                        h
                      ),
                      described: {
                        help: t("Supports Markdown formatting."),
                        id: "id_description",
                      },
                      label: t("Description"),
                      translator,
                    },
                    h
                  ),
                ]
              ),
              h.div(
                [],
                [
                  text("min_age", "minAge", t("Minimum Age"), {
                    type: "number",
                  }),
                ]
              ),
            ]
          ),
        ]
      ),
    ]
  );

  const session = h.div(
    [
      h.Key(`proposal-session-fields-${model.values.categoryId}`),
      h.Class("card"),
      h.Id("proposal-session-fields"),
    ],
    [
      h.div(
        [h.Class("card-body space-y-6")],
        [
          text(
            "participants_limit",
            "participantsLimit",
            t("Participants Limit"),
            { help: t("Empty or 0 = no enrollment"), type: "number" }
          ),
          h.div(
            [h.Class("grid grid-cols-2 gap-4")],
            [
              text("duration_hours", "durationHours", t("Hours"), {
                type: "number",
              }),
              text("duration_minutes", "durationMinutes", t("Minutes"), {
                type: "number",
              }),
            ]
          ),
        ]
      ),
    ]
  );

  const tracks =
    model.tracks.length === 0
      ? h.empty
      : h.div(
          [h.Class("card")],
          [
            h.div(
              [h.Class("card-body")],
              [
                h.h3(
                  [h.Class("text-lg font-semibold text-foreground mb-2")],
                  [t("Tracks")]
                ),
                h.p(
                  [h.Class("text-sm text-foreground-muted mb-4")],
                  [t("Assign this proposal to one or more programme tracks.")]
                ),
                h.div(
                  [h.Class("space-y-2")],
                  model.tracks.map((track) => {
                    const checked = model.values.trackIds.includes(track.id);

                    return checkboxRow(
                      {
                        checked,
                        label: track.name,
                        name: "track_ids",
                        onToggle: toForm(
                          ProposalFormMessage.ToggledTrack({
                            checked: !checked,
                            id: track.id,
                          })
                        ),
                        value: track.id,
                      },
                      h
                    );
                  })
                ),
              ]
            ),
          ]
        );

  return {
    content: [
      nonField.length === 0
        ? h.empty
        : h.div(
            [h.Class("px-4 pt-4 lg:px-6 lg:pt-6")],
            formErrors(nonField, h)
          ),
      h.form(
        [
          h.Id("proposal-form"),
          h.Method("post"),
          h.Class(
            "p-4 lg:p-6 grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6 items-start"
          ),
          h.OnSubmit(toForm(ProposalFormMessage.SubmittedProposalForm())),
        ],
        [details, session, facilitatorCard(model, translator, h), tracks]
      ),
    ],
    header: header({
      actions: h.div(
        [h.Class("flex items-center space-x-3")],
        [
          linkButton(
            { href: model.cancelUrl, text: t("Cancel"), variant: "secondary" },
            h
          ),
          button(
            {
              attributes: [h.Attribute("form", "proposal-form")],
              disabled: model.isSaving,
              icon: isEdit ? checkOutline : plusOutline,
              text: isEdit ? t("Save") : t("Create Proposal"),
            },
            h
          ),
        ]
      ),
      subtitle: [`${event.name} · ${t("Proposals")}`],
      title: isEdit ? model.savedTitle : t("New Proposal"),
    }),
    title: isEdit ? t("Edit Proposal") : t("New Proposal"),
  };
};
