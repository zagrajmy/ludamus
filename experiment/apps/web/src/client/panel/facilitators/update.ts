import { Option } from "effect";
import type { Update } from "foldkit";
import { modifyFields } from "foldkit/struct";

import type { Translator } from "../../../ui/i18n.js";
import { BROKEN_SAVE, PanelFailure, refusalText } from "../failure.js";
import { PanelOut } from "../out.js";
import { SaveFacilitator } from "./command.js";
import { FacilitatorFormMessage, FacilitatorListMessage } from "./message.js";
import type {
  FacilitatorBinModel,
  FacilitatorFormModel,
  FacilitatorsModel,
} from "./model.js";
import { facilitatorsQuery } from "./model.js";

type ListModel = FacilitatorBinModel | FacilitatorsModel;

type ListReturn<Model extends ListModel> = Update.ReturnWithOutMessage<
  Model,
  FacilitatorListMessage,
  PanelOut
>;

const isList = (model: ListModel): model is FacilitatorsModel =>
  "filters" in model;

export const updateFacilitatorList = <Model extends ListModel>(
  model: Model,
  message: FacilitatorListMessage
): ListReturn<Model> =>
  FacilitatorListMessage.match<ListReturn<Model>>(message, {
    ChangedFilter: ({ name, value }) => {
      if (!isList(model)) {
        return { model };
      }

      const filters = { ...model.filters, [name]: value };
      const next = { ...model, filters };

      return name === "search"
        ? { model: next }
        : {
            model: next,
            outMessage: PanelOut.RequestedNavigation({
              href: `${model.listPath}?${facilitatorsQuery(filters)}`,
              notes: [],
            }),
          };
    },
    SubmittedFilters: () =>
      isList(model)
        ? {
            model,
            outMessage: PanelOut.RequestedNavigation({
              href: `${model.listPath}?${facilitatorsQuery(model.filters)}`,
              notes: [],
            }),
          }
        : { model },
    ToggledAll: ({ checked }) => ({
      model: {
        ...model,
        selected: checked ? model.rows.map((row) => row.slug) : [],
      },
    }),
    ToggledRow: ({ checked, slug }) => ({
      model: {
        ...model,
        selected: checked
          ? [...model.selected.filter((known) => known !== slug), slug]
          : model.selected.filter((known) => known !== slug),
      },
    }),
  });

type FormReturn = Update.ReturnWithOutMessage<
  FacilitatorFormModel,
  FacilitatorFormMessage,
  PanelOut
>;

const editValues = (
  model: FacilitatorFormModel,
  change: Partial<FacilitatorFormModel["values"]>
): FormReturn => ({
  model: { ...model, values: { ...model.values, ...change } },
});

const listHref = (model: FacilitatorFormModel) =>
  `/panel/event/${model.eventSlug}/facilitators/`;

export const updateFacilitatorForm = (
  model: FacilitatorFormModel,
  message: FacilitatorFormMessage,
  translator: Translator
): FormReturn =>
  FacilitatorFormMessage.match<FormReturn>(message, {
    ChangedAccreditation: ({ value }) =>
      editValues(model, { accreditationType: value }),
    ChangedComment: ({ value }) =>
      editValues(model, { internalComment: value }),
    ChangedDisplayName: ({ value }) =>
      editValues(model, { displayName: value }),
    FailedSaveFacilitator: ({ failure }) => {
      const settled = modifyFields(model, { isSaving: () => false });

      const leave = (text: string): FormReturn => ({
        model: settled,
        outMessage: PanelOut.RequestedNavigation({
          href: listHref(model),
          notes: [{ level: "error", text }],
        }),
      });

      return PanelFailure.match<FormReturn>(failure, {
        Broken: () => ({
          model: modifyFields(settled, {
            errors: () => [{ field: "", msgid: BROKEN_SAVE, vars: {} }],
          }),
        }),
        Conflict: () => ({ model: settled }),
        Invalid: ({ errors }) => ({
          model: modifyFields(settled, { errors: () => errors }),
        }),
        Missing: () => leave(translator.t("Facilitator not found.")),
        Refused: ({ reason }) => leave(refusalText(reason, translator)),
        Scheduled: () => ({ model: settled }),
      });
    },
    SubmittedFacilitatorForm: () =>
      model.isSaving
        ? { model }
        : {
            commands: [
              SaveFacilitator({
                ...model.values,
                eventSlug: model.eventSlug,
                facilitatorSlug: model.facilitatorSlug,
              }),
            ],
            model: modifyFields(model, { isSaving: () => true }),
          },
    SucceededSaveFacilitator: ({ slug }) => ({
      model,
      outMessage: Option.isSome(model.facilitatorSlug)
        ? PanelOut.RequestedNavigation({
            href: `${listHref(model)}${slug}/`,
            notes: [
              {
                level: "success",
                text: translator.t("Facilitator updated successfully."),
              },
            ],
          })
        : PanelOut.RequestedNavigation({
            href: listHref(model),
            notes: [
              {
                level: "success",
                text: translator.t("Facilitator created successfully."),
              },
            ],
          }),
    }),
    ToggledAssignMe: ({ checked }) => editValues(model, { assignMe: checked }),
    ToggledCollective: ({ checked }) =>
      editValues(model, { isCollective: checked }),
  });
