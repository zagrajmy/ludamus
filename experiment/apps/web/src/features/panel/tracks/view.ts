import { Option } from "effect";

import { PanelAction } from "../../../client/panel/action.js";
import type { PanelCurrentEvent } from "../../../client/panel/chrome.js";
import { eventPath } from "../../../client/panel/chrome.js";
import { errorsFor } from "../../../client/panel/failure.js";
import { PanelMessage } from "../../../client/panel/message.js";
import type { TracksFlags } from "../../../client/panel/tracks/flags.js";
import { TrackFormMessage } from "../../../client/panel/tracks/message.js";
import type { TrackFormModel } from "../../../client/panel/tracks/model.js";
import { button, linkButton } from "../../../ui/button.js";
import { formErrors } from "../../../ui/form.js";
import type { Translator } from "../../../ui/i18n.js";
import {
  checkOutline,
  mapPinOutline,
  plusOutline,
  userOutline,
} from "../../../ui/icons.js";
import { pillList } from "../../../ui/pill.js";
import { infoPopover } from "../../../ui/popover.js";
import { emptyCard, header, tableHead, tesseraTable } from "../page.js";
import type { PanelH, PanelPageView } from "../page.js";

const newTrackButton = (slug: string, translator: Translator, h: PanelH) =>
  linkButton(
    {
      href: eventPath(slug, "tracks/create/"),
      icon: plusOutline,
      text: translator.t("New Track"),
    },
    h
  );

export const tracksView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    page: TracksFlags;
    translator: Translator;
  }>,
  h: PanelH
): PanelPageView => {
  const { event, page, translator } = options;
  const { t, tc } = translator;

  const rows = page.tracks.map((track) =>
    h.tr(
      [h.Key(track.slug), h.Class("hover:bg-bg-tertiary")],
      [
        h.td(
          [h.Class("px-6 py-4 text-sm font-medium text-foreground")],
          [track.name]
        ),
        h.td(
          [h.Class("px-6 py-4 whitespace-nowrap text-sm")],
          [
            track.isPublic
              ? h.span(
                  [
                    h.Class(
                      "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-success-bg text-success-text"
                    ),
                  ],
                  [t("Public")]
                )
              : h.span(
                  [
                    h.Class(
                      "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-warning-bg text-warning-text"
                    ),
                  ],
                  [t("Private")]
                ),
          ]
        ),
        h.td(
          [h.Class("px-6 py-4 text-sm")],
          [
            pillList(
              { icon: mapPinOutline, items: track.spaceNames, translator },
              h
            ),
          ]
        ),
        h.td(
          [h.Class("px-6 py-4 text-sm"), h.DataAttribute("ph-mask", "")],
          [
            pillList(
              { icon: userOutline, items: track.managerNames, translator },
              h
            ),
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
                h.Href(eventPath(event.slug, `tracks/${track.slug}/edit/`)),
                h.DataAttribute("row-action", ""),
                h.Class("text-primary hover:text-primary/80 mr-4"),
              ],
              [t("Edit")]
            ),
            h.button(
              [
                h.Type("button"),
                h.Class("text-danger hover:text-danger/80"),
                h.OnClick(
                  PanelMessage.RequestedConfirm({
                    action: PanelAction.DeleteTrack({
                      eventSlug: event.slug,
                      trackSlug: track.slug,
                    }),
                    prompt: {
                      confirmLabel: t("Confirm"),
                      icon: "exclamation-triangle",
                      message: t("Are you sure you want to delete this track?"),
                    },
                  })
                ),
              ],
              [t("Delete")]
            ),
          ]
        ),
      ]
    )
  );

  return {
    content:
      page.tracks.length === 0
        ? [
            emptyCard(
              [
                h.p(
                  [h.Class("text-foreground-muted mb-4")],
                  [
                    t(
                      "No tracks yet. Add a track to organize proposals by thematic area."
                    ),
                  ]
                ),
                newTrackButton(event.slug, translator, h),
              ],
              h
            ),
          ]
        : [
            tesseraTable(
              {
                body: [
                  tableHead(
                    [
                      { label: tc("place", "Name") },
                      { label: t("Visibility") },
                      { label: t("Spaces") },
                      { label: t("Organizers") },
                      { align: "right", label: t("Actions") },
                    ],
                    h
                  ),
                  h.tbody(
                    [h.Class("bg-bg-secondary divide-y divide-border")],
                    rows
                  ),
                ],
                flush: true,
              },
              h
            ),
          ],
    header: header({
      actions: newTrackButton(event.slug, translator, h),
      adornment: infoPopover(
        {
          body: t(
            "Tracks let you group proposals by thematic area. Public tracks are shown to proposers in the submission wizard and their sessions appear on the event schedule; sessions in private tracks stay off it."
          ),
          title: t("What are tracks?"),
        },
        h
      ),
      subtitle: [`${event.name} · ${t("Tracks")}`],
      title: t("Tracks"),
    }),
    title: t("Tracks"),
  };
};

const toForm = (message: TrackFormMessage) =>
  PanelMessage.RelayedTrackForm({ message });

const checkboxRow = (
  options: Readonly<{
    checked: boolean;
    label: string;
    mask?: boolean;
    name: string;
    onToggle: PanelMessage;
    value: number;
  }>,
  h: PanelH
) =>
  h.label(
    [
      h.Key(`${options.name}-${options.value}`),
      h.Class("flex items-center gap-2 py-1 cursor-pointer"),
    ],
    [
      h.input([
        h.Type("checkbox"),
        h.Name(options.name),
        h.Value(String(options.value)),
        h.Checked(options.checked),
        h.Class(
          "w-4 h-4 rounded border-border text-primary focus:ring-primary"
        ),
        h.OnClick(options.onToggle),
      ]),
      h.span(
        [
          h.Class("text-sm text-foreground"),
          ...(options.mask === true ? [h.DataAttribute("ph-mask", "")] : []),
        ],
        [options.label]
      ),
    ]
  );

export const trackFormView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    model: TrackFormModel;
    translator: Translator;
  }>,
  h: PanelH
): PanelPageView => {
  const { event, model, translator } = options;
  const { t, tc } = translator;
  const isEdit = Option.isSome(model.trackSlug);
  const formId = isEdit ? "track-edit-form" : "track-create-form";
  const nameErrors = errorsFor(model.errors, "name", translator);
  const title = isEdit ? t("Edit Track") : t("New Track");

  const form = h.form(
    [
      h.Id(formId),
      h.Method("post"),
      h.Class("max-w-2xl"),
      h.OnSubmit(toForm(TrackFormMessage.SubmittedTrackForm())),
    ],
    [
      ...formErrors(errorsFor(model.errors, "", translator), h),
      h.div(
        [h.Class("card")],
        [
          h.div(
            [h.Class("card-body")],
            [
              h.h3(
                [h.Class("text-lg font-semibold text-foreground mb-6")],
                [t("Track Details")]
              ),
              h.div(
                [h.Class("space-y-6")],
                [
                  h.div(
                    [],
                    [
                      h.label(
                        [
                          h.Class(
                            "block text-sm font-medium text-foreground-secondary mb-1"
                          ),
                          h.For("id_name"),
                        ],
                        [tc("place", "Name")]
                      ),
                      h.input([
                        h.Type("text"),
                        h.Name("name"),
                        h.Id("id_name"),
                        h.Value(model.values.name),
                        h.Class(
                          `w-full border ${nameErrors.length > 0 ? "border-danger" : "border-border"} rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-primary`
                        ),
                        ...(isEdit
                          ? []
                          : [h.Placeholder(t("e.g., RPG, Board Games, LARP"))]),
                        h.OnInput((value) =>
                          toForm(TrackFormMessage.ChangedName({ value }))
                        ),
                      ]),
                      ...nameErrors
                        .slice(0, 1)
                        .map((error) =>
                          h.p([h.Class("mt-1 text-sm text-danger")], [error])
                        ),
                    ]
                  ),
                  h.div(
                    [],
                    [
                      h.label(
                        [h.Class("flex items-center gap-2 cursor-pointer")],
                        [
                          h.input([
                            h.Type("checkbox"),
                            h.Name("is_public"),
                            h.Id("id_is_public"),
                            h.Checked(model.values.isPublic),
                            h.Class(
                              "w-4 h-4 rounded border-border text-primary focus:ring-primary"
                            ),
                            h.OnClick(
                              toForm(
                                TrackFormMessage.ToggledPublic({
                                  checked: !model.values.isPublic,
                                })
                              )
                            ),
                          ]),
                          h.span(
                            [h.Class("text-sm font-medium text-foreground")],
                            [t("Public track")]
                          ),
                        ]
                      ),
                      h.p(
                        [h.Class("mt-1 text-xs text-foreground-muted")],
                        [
                          t(
                            "Public tracks are shown to proposers in the submission wizard, and their sessions appear on the event schedule."
                          ),
                        ]
                      ),
                    ]
                  ),
                  model.spaces.length === 0
                    ? h.empty
                    : h.div(
                        [],
                        [
                          h.label(
                            [
                              h.Class(
                                "block text-sm font-medium text-foreground-secondary mb-1"
                              ),
                            ],
                            [t("Spaces")]
                          ),
                          h.div(
                            [
                              h.Class(
                                "border border-border rounded-lg p-3 max-h-48 overflow-y-auto"
                              ),
                            ],
                            model.spaces.map((space) => {
                              const checked = model.values.spaceIds.includes(
                                space.id
                              );

                              return checkboxRow(
                                {
                                  checked,
                                  label: space.name,
                                  name: "space_pks",
                                  onToggle: toForm(
                                    TrackFormMessage.ToggledSpace({
                                      checked: !checked,
                                      id: space.id,
                                    })
                                  ),
                                  value: space.id,
                                },
                                h
                              );
                            })
                          ),
                        ]
                      ),
                  model.managers.length === 0
                    ? h.empty
                    : h.div(
                        [],
                        [
                          h.label(
                            [
                              h.Class(
                                "block text-sm font-medium text-foreground-secondary mb-1"
                              ),
                            ],
                            [t("Managers")]
                          ),
                          h.div(
                            [
                              h.Class(
                                "border border-border rounded-lg p-3 max-h-48 overflow-y-auto"
                              ),
                            ],
                            model.managers.map((manager) => {
                              const checked = model.values.managerIds.includes(
                                manager.id
                              );

                              return checkboxRow(
                                {
                                  checked,
                                  label: manager.name,
                                  mask: true,
                                  name: "manager_pks",
                                  onToggle: toForm(
                                    TrackFormMessage.ToggledManager({
                                      checked: !checked,
                                      id: manager.id,
                                    })
                                  ),
                                  value: manager.id,
                                },
                                h
                              );
                            })
                          ),
                        ]
                      ),
                ]
              ),
            ]
          ),
        ]
      ),
    ]
  );

  return {
    content: [h.div([h.Class("panel-bleed")], [form])],
    header: header({
      actions: h.div(
        [h.Class("flex items-center gap-3")],
        [
          linkButton(
            {
              href: eventPath(event.slug, "tracks/"),
              text: t("Cancel"),
              variant: "secondary",
            },
            h
          ),
          button(
            {
              attributes: [h.Attribute("form", formId)],
              disabled: model.isSaving,
              icon: isEdit ? checkOutline : plusOutline,
              text: isEdit ? t("Save Changes") : t("Create Track"),
            },
            h
          ),
        ]
      ),
      subtitle: [
        isEdit
          ? `${event.name} · ${t("Tracks")} · ${model.values.name}`
          : `${event.name} · ${t("Tracks")}`,
      ],
      title,
    }),
    title,
  };
};
