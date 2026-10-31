import { Option } from "effect";
import { defineView } from "foldkit/submodel";

import { PanelMessage } from "../../client/panel/message.js";
import { PanelPageModel } from "../../client/panel/model.js";
import type { PanelModel } from "../../client/panel/model.js";
import type { Translator } from "../../ui/i18n.js";
import type { Dialog } from "../../ui/modal.js";
import { confirmDialog } from "../../ui/modal.js";
import { pageContextOf } from "../page-context.js";
import type { PageContext, PageInputs } from "../page-context.js";
import type { PageTitle } from "../shell/title.js";
import { cfpView } from "./cfp/view.js";
import { panelLayout } from "./chrome.js";
import { dashboardView } from "./dashboard/view.js";
import {
  facilitatorBinView,
  facilitatorDetailView,
  facilitatorFormView,
  facilitatorsView,
} from "./facilitators/view.js";
import type { PanelH, PanelPageView } from "./page.js";
import { header } from "./page.js";
import { proposalDetailView } from "./proposals/detail.js";
import { proposalFormView } from "./proposals/form.js";
import { proposalsView } from "./proposals/list.js";
import { timetableView } from "./timetable/view.js";
import { trackFormView, tracksView } from "./tracks/view.js";

const noEvent = (translator: Translator, h: PanelH): PanelPageView => ({
  content: [
    h.div(
      [h.Class("panel-bleed")],
      [
        h.div(
          [h.Class("card p-8 text-center")],
          [
            h.p(
              [h.Class("text-foreground-muted")],
              [
                translator.t(
                  "No events available. Create an event to get started."
                ),
              ]
            ),
          ]
        ),
      ]
    ),
  ],
  header: header({ subtitle: [], title: translator.t("Dashboard") }),
  title: translator.t("Dashboard"),
});

export const renderPanelPage = (
  model: PanelModel,
  translator: Translator,
  h: PanelH
): PanelPageView =>
  Option.match(model.chrome.currentEvent, {
    onNone: () => noEvent(translator, h),
    onSome: (event) =>
      PanelPageModel.match<PanelPageView>(model.page, {
        Cfp: ({ model: page }) => cfpView({ event, page, translator }, h),
        Dashboard: ({ model: stats }) =>
          dashboardView({ event, stats, translator }, h),
        FacilitatorBin: ({ model: bin }) =>
          facilitatorBinView({ event, model: bin, translator }, h),
        FacilitatorDetail: ({ model: page }) =>
          facilitatorDetailView({ event, page, translator }, h),
        FacilitatorForm: ({ model: form }) =>
          facilitatorFormView({ event, model: form, translator }, h),
        Facilitators: ({ model: list }) =>
          facilitatorsView({ event, model: list, translator }, h),
        ProposalDetail: ({ model: detail }) =>
          proposalDetailView({ event, model: detail, translator }, h),
        ProposalForm: ({ model: form }) =>
          proposalFormView({ event, model: form, translator }, h),
        Proposals: ({ model: list }) =>
          proposalsView({ event, model: list, translator }, h),
        Timetable: ({ model: timetable }) =>
          timetableView({ event, model: timetable, translator }, h),
        TrackForm: ({ model: form }) =>
          trackFormView({ event, model: form, translator }, h),
        Tracks: ({ model: page }) => tracksView({ event, page, translator }, h),
      }),
  });

const pageTitleOf = (model: PanelModel, translator: Translator) =>
  PanelPageModel.match<string>(model.page, {
    Cfp: () => translator.t("Call for Proposals"),
    Dashboard: () => translator.t("Dashboard"),
    FacilitatorBin: () =>
      `${translator.t("Bin")} • ${translator.t("Facilitators")}`,
    FacilitatorDetail: ({ model: page }) =>
      `${page.displayName} • ${translator.t("Facilitators")}`,
    FacilitatorForm: ({ model: form }) =>
      Option.isSome(form.facilitatorSlug)
        ? translator.t("Edit Facilitator")
        : translator.t("New Facilitator"),
    Facilitators: () => translator.t("Facilitators"),
    ProposalDetail: ({ model: detail }) =>
      `${detail.title} • ${translator.t("Proposals")}`,
    ProposalForm: ({ model: form }) =>
      Option.isSome(form.proposalId)
        ? translator.t("Edit Proposal")
        : translator.t("New Proposal"),
    Proposals: () => translator.t("Proposals"),
    Timetable: () => translator.t("Schedule"),
    TrackForm: ({ model: form }) =>
      Option.isSome(form.trackSlug)
        ? translator.t("Edit Track")
        : translator.t("New Track"),
    Tracks: () => translator.t("Tracks"),
  });

export const panelTitle = (
  model: PanelModel,
  context: PageContext
): PageTitle => {
  const pageTitle = pageTitleOf(model, context.translator);

  return {
    name: Option.match(model.chrome.currentEvent, {
      onNone: () => `${pageTitle} • ${context.shell.sphere.name}`,
      onSome: (event) => `${pageTitle} • ${event.name}`,
    }),
    sphereSuffix: false,
  };
};

export const panelView = defineView<PanelModel, PanelMessage, PageInputs>(
  (model, inputs, h) => {
    const context = pageContextOf(inputs.shell);
    const page = renderPanelPage(model, context.translator, h);

    const overlay = Option.match(model.pendingConfirm, {
      onNone: () =>
        confirmDialog(
          {
            message: "",
            model: model.confirmDialog,
            onConfirm: PanelMessage.ConfirmedAction(),
            toParentMessage: (message: Dialog.Message) =>
              PanelMessage.GotConfirmDialogMessage({ message }),
            translator: context.translator,
          },
          h
        ),
      onSome: ({ prompt }) =>
        confirmDialog(
          {
            confirmLabel: prompt.confirmLabel,
            icon: prompt.icon,
            message: prompt.message,
            model: model.confirmDialog,
            onConfirm: PanelMessage.ConfirmedAction(),
            toParentMessage: (message: Dialog.Message) =>
              PanelMessage.GotConfirmDialogMessage({ message }),
            translator: context.translator,
          },
          h
        ),
    });

    return panelLayout(
      {
        chrome: model.chrome,
        content: page.content,
        header: page.header,
        overlays: [overlay],
        shell: inputs.shell,
        translator: context.translator,
      },
      h
    );
  }
);
