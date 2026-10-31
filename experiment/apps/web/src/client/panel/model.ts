import { Option, Schema } from "effect";
import { defineTaggedUnion } from "foldkit/schema";

import { Dialog } from "../../ui/modal.js";
import { PendingConfirm } from "./action.js";
import { CfpFlags } from "./cfp/flags.js";
import { PanelChromeModel, initPanelChrome } from "./chrome.js";
import { DashboardFlags } from "./dashboard/flags.js";
import { FacilitatorDetailFlags } from "./facilitators/flags.js";
import {
  FacilitatorBinModel,
  FacilitatorFormModel,
  FacilitatorsModel,
  initFacilitatorForm,
} from "./facilitators/model.js";
import { PanelPageFlags } from "./flags.js";
import type { PanelFlags } from "./flags.js";
import { ProposalsFlags } from "./proposals/flags.js";
import {
  ProposalDetailModel,
  ProposalFormModel,
  initProposalForm,
} from "./proposals/model.js";
import { TimetableModel } from "./timetable/flags.js";
import { TracksFlags } from "./tracks/flags.js";
import { TrackFormModel, initTrackForm } from "./tracks/model.js";

export const PanelPageModel = defineTaggedUnion({
  Cfp: { model: CfpFlags },
  Dashboard: { model: DashboardFlags },
  FacilitatorBin: { model: FacilitatorBinModel },
  FacilitatorDetail: { model: FacilitatorDetailFlags },
  FacilitatorForm: { model: FacilitatorFormModel },
  Facilitators: { model: FacilitatorsModel },
  ProposalDetail: { model: ProposalDetailModel },
  ProposalForm: { model: ProposalFormModel },
  Proposals: { model: ProposalsFlags },
  Timetable: { model: TimetableModel },
  TrackForm: { model: TrackFormModel },
  Tracks: { model: TracksFlags },
});

export type PanelPageModel = typeof PanelPageModel.Type;

export const PanelModel = Schema.Struct({
  chrome: PanelChromeModel,
  confirmDialog: Dialog.Model,
  isActing: Schema.Boolean,
  page: PanelPageModel,
  pendingConfirm: Schema.Option(PendingConfirm),
});

export type PanelModel = typeof PanelModel.Type;

export const CONFIRM_DIALOG_ID = "confirm-dialog";

const initPage = (flags: PanelPageFlags): PanelPageModel =>
  PanelPageFlags.match<PanelPageModel>(flags, {
    Cfp: ({ flags: page }) => PanelPageModel.Cfp({ model: page }),
    Dashboard: ({ flags: page }) => PanelPageModel.Dashboard({ model: page }),
    FacilitatorBin: ({ flags: page }) =>
      PanelPageModel.FacilitatorBin({ model: { ...page, selected: [] } }),
    FacilitatorDetail: ({ flags: page }) =>
      PanelPageModel.FacilitatorDetail({ model: page }),
    FacilitatorForm: ({ flags: page }) =>
      PanelPageModel.FacilitatorForm({ model: initFacilitatorForm(page) }),
    Facilitators: ({ flags: page }) =>
      PanelPageModel.Facilitators({ model: { ...page, selected: [] } }),
    ProposalDetail: ({ flags: page }) =>
      PanelPageModel.ProposalDetail({ model: { ...page, isMenuOpen: false } }),
    ProposalForm: ({ flags: page }) =>
      PanelPageModel.ProposalForm({ model: initProposalForm(page) }),
    Proposals: ({ flags: page }) => PanelPageModel.Proposals({ model: page }),
    Timetable: ({ flags: page }) =>
      PanelPageModel.Timetable({ model: { ...page, selected: Option.none() } }),
    TrackForm: ({ flags: page }) =>
      PanelPageModel.TrackForm({ model: initTrackForm(page) }),
    Tracks: ({ flags: page }) => PanelPageModel.Tracks({ model: page }),
  });

export const initPanel = (flags: PanelFlags): PanelModel => ({
  chrome: initPanelChrome(flags.chrome),
  confirmDialog: Dialog.init({ id: CONFIRM_DIALOG_ID }),
  isActing: false,
  page: initPage(flags.page),
  pendingConfirm: Option.none(),
});
