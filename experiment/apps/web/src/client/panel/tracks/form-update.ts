import { Option } from "effect";
import type { Update } from "foldkit";
import { modifyFields } from "foldkit/struct";

import type { Translator } from "../../../ui/i18n.js";
import { BROKEN_SAVE, PanelFailure, refusalText } from "../failure.js";
import { PanelOut } from "../out.js";
import { SaveTrack } from "./command.js";
import { TrackFormMessage } from "./message.js";
import type { TrackFormModel } from "./model.js";
import { toggled } from "./model.js";

type Return = Update.ReturnWithOutMessage<
  TrackFormModel,
  TrackFormMessage,
  PanelOut
>;

const tracksHref = (model: TrackFormModel) =>
  `/panel/event/${model.eventSlug}/tracks/`;

export const updateTrackForm = (
  model: TrackFormModel,
  message: TrackFormMessage,
  translator: Translator
): Return =>
  TrackFormMessage.match<Return>(message, {
    ChangedName: ({ value }) => ({
      model: modifyFields(model, {
        values: (values) => modifyFields(values, { name: () => value }),
      }),
    }),
    FailedSaveTrack: ({ failure }) =>
      PanelFailure.match<Return>(failure, {
        Broken: () => ({
          model: modifyFields(model, {
            errors: () => [{ field: "", msgid: BROKEN_SAVE, vars: {} }],
            isSaving: () => false,
          }),
        }),
        Conflict: () => ({
          model: modifyFields(model, { isSaving: () => false }),
        }),
        Invalid: ({ errors }) => ({
          model: modifyFields(model, {
            errors: () => errors,
            isSaving: () => false,
          }),
        }),
        Missing: () => ({
          model,
          outMessage: PanelOut.RequestedNavigation({
            href: tracksHref(model),
            notes: [{ level: "error", text: translator.t("Track not found.") }],
          }),
        }),
        Refused: ({ reason }) => ({
          model,
          outMessage: PanelOut.RequestedNavigation({
            href: tracksHref(model),
            notes: [{ level: "error", text: refusalText(reason, translator) }],
          }),
        }),
        Scheduled: () => ({
          model: modifyFields(model, { isSaving: () => false }),
        }),
      }),
    SubmittedTrackForm: () =>
      model.isSaving
        ? { model }
        : {
            commands: [
              SaveTrack({
                eventSlug: model.eventSlug,
                isPublic: model.values.isPublic,
                managerIds: model.values.managerIds,
                name: model.values.name,
                spaceIds: model.values.spaceIds,
                trackSlug: model.trackSlug,
              }),
            ],
            model: modifyFields(model, { isSaving: () => true }),
          },
    SucceededSaveTrack: () => ({
      model,
      outMessage: PanelOut.RequestedNavigation({
        href: tracksHref(model),
        notes: [
          {
            level: "success",
            text: Option.isSome(model.trackSlug)
              ? translator.t("Track updated successfully.")
              : translator.t("Track created successfully."),
          },
        ],
      }),
    }),
    ToggledManager: ({ checked, id }) => ({
      model: modifyFields(model, {
        values: (values) =>
          modifyFields(values, {
            managerIds: () => toggled(values.managerIds, id, checked),
          }),
      }),
    }),
    ToggledPublic: ({ checked }) => ({
      model: modifyFields(model, {
        values: (values) => modifyFields(values, { isPublic: () => checked }),
      }),
    }),
    ToggledSpace: ({ checked, id }) => ({
      model: modifyFields(model, {
        values: (values) =>
          modifyFields(values, {
            spaceIds: () => toggled(values.spaceIds, id, checked),
          }),
      }),
    }),
  });
