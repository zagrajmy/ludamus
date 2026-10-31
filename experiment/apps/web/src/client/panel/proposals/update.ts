import { Option } from "effect";
import type { Update } from "foldkit";
import { modifyFields } from "foldkit/struct";

import type { Translator } from "../../../ui/i18n.js";
import { BROKEN_SAVE, PanelFailure, refusalText } from "../failure.js";
import { PanelOut } from "../out.js";
import {
  FocusFirstMenuItem,
  FocusMenuButton,
  ReadCover,
  SaveProposal,
} from "./command.js";
import type { ProposalsFlags } from "./flags.js";
import {
  ProposalDetailMessage,
  ProposalFormMessage,
  ProposalListMessage,
} from "./message.js";
import type { ProposalDetailModel, ProposalFormModel } from "./model.js";
import { proposalsQuery, trackFormQuery } from "./model.js";

type ListReturn = Update.ReturnWithOutMessage<
  ProposalsFlags,
  ProposalListMessage,
  PanelOut
>;

const fieldPrefix = "field_";

const navigate = (model: ProposalsFlags, query: string): ListReturn => ({
  model,
  outMessage: PanelOut.RequestedNavigation({
    href: `${model.listPath}?${query}`,
    notes: [],
  }),
});

export const updateProposalList = (
  model: ProposalsFlags,
  message: ProposalListMessage
): ListReturn =>
  ProposalListMessage.match<ListReturn>(message, {
    ChangedFilter: ({ name, value }) => {
      if (name.startsWith(fieldPrefix)) {
        const id = Number(name.slice(fieldPrefix.length));

        const fields = model.fields.map((field) =>
          field.id === id ? { ...field, value } : field
        );

        return navigate(
          { ...model, fields },
          proposalsQuery(model.filters, fields)
        );
      }

      const filters = { ...model.filters, [name]: value };
      const next = { ...model, filters };

      return name === "search"
        ? { model: next }
        : navigate(next, proposalsQuery(filters, model.fields));
    },
    ChangedTrack: ({ value }) =>
      navigate(
        model,
        trackFormQuery({
          fields: model.fields,
          filters: model.filters,
          statusValue: model.filters.status,
          track: value,
        })
      ),
    SubmittedFilters: () =>
      navigate(model, proposalsQuery(model.filters, model.fields)),
  });

type DetailReturn = Update.ReturnWithOutMessage<
  ProposalDetailModel,
  ProposalDetailMessage,
  PanelOut
>;

export const updateProposalDetail = (
  model: ProposalDetailModel,
  message: ProposalDetailMessage
): DetailReturn =>
  ProposalDetailMessage.match<DetailReturn>(message, {
    ClosedMenu: ({ refocus }) => ({
      commands: refocus ? [FocusMenuButton()] : [],
      model: modifyFields(model, { isMenuOpen: () => false }),
    }),
    CompletedFocus: () => ({ model }),
    OpenedMenu: ({ focusFirst }) => ({
      commands: focusFirst ? [FocusFirstMenuItem()] : [],
      model: modifyFields(model, { isMenuOpen: () => true }),
    }),
  });

type FormReturn = Update.ReturnWithOutMessage<
  ProposalFormModel,
  ProposalFormMessage,
  PanelOut
>;

const toggled = (ids: readonly number[], id: number, checked: boolean) =>
  checked
    ? [...ids.filter((known) => known !== id), id]
    : ids.filter((known) => known !== id);

const detailHref = (model: ProposalFormModel, id: number) => {
  const base = `/panel/event/${model.eventSlug}/proposals/${id}/`;

  return model.next === ""
    ? base
    : `${base}?${new URLSearchParams({ next: model.next }).toString()}`;
};

export const updateProposalForm = (
  model: ProposalFormModel,
  message: ProposalFormMessage,
  translator: Translator
): FormReturn =>
  ProposalFormMessage.match<FormReturn>(message, {
    ChangedFacilitatorSearch: ({ value }) => ({
      model: modifyFields(model, { facilitatorSearch: () => value }),
    }),
    ChangedText: ({ name, value }) => ({
      model: { ...model, values: { ...model.values, [name]: value } },
    }),
    ChosenCover: ({ cover }) => ({
      model: modifyFields(model, {
        cover: () => Option.some(cover),
        coverCleared: () => false,
      }),
    }),
    ClearedCover: () => ({
      model: modifyFields(model, {
        cover: () => Option.none(),
        coverCleared: () => true,
      }),
    }),
    FailedReadCover: () => ({ model }),
    FailedSaveProposal: ({ failure }) => {
      const settled = modifyFields(model, { isSaving: () => false });

      const leave = (text: string): FormReturn => ({
        model: settled,
        outMessage: PanelOut.RequestedNavigation({
          href: `/panel/event/${model.eventSlug}/proposals/`,
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
        Missing: () => leave(translator.t("Proposal not found.")),
        Refused: ({ reason }) => leave(refusalText(reason, translator)),
        Scheduled: () => ({ model: settled }),
      });
    },
    PickedCover: ({ files }) => {
      const [file] = files;

      return file === undefined
        ? { model }
        : { commands: [ReadCover({ file })], model };
    },
    SubmittedProposalForm: () =>
      model.isSaving
        ? { model }
        : {
            commands: [
              SaveProposal({
                ...model.values,
                coverImage: Option.match(model.cover, {
                  onNone: () => null,
                  onSome: (cover) => ({
                    dataUrl: cover.dataUrl,
                    name: cover.name,
                  }),
                }),
                coverImageClear: model.coverCleared,
                eventSlug: model.eventSlug,
                proposalId: Option.getOrNull(model.proposalId),
              }),
            ],
            model: modifyFields(model, { isSaving: () => true }),
          },
    SucceededSaveProposal: ({ id }) => ({
      model,
      outMessage: PanelOut.RequestedNavigation({
        href: Option.isSome(model.proposalId)
          ? detailHref(model, id)
          : `/panel/event/${model.eventSlug}/proposals/${id}/`,
        notes: [
          {
            level: "success",
            text: Option.isSome(model.proposalId)
              ? translator.t("Proposal updated successfully.")
              : translator.t("Proposal created successfully."),
          },
        ],
      }),
    }),
    ToggledFacilitator: ({ checked, id }) => ({
      model: {
        ...model,
        values: {
          ...model.values,
          facilitatorIds: toggled(model.values.facilitatorIds, id, checked),
        },
      },
    }),
    ToggledTrack: ({ checked, id }) => ({
      model: {
        ...model,
        values: {
          ...model.values,
          trackIds: toggled(model.values.trackIds, id, checked),
        },
      },
    }),
  });
