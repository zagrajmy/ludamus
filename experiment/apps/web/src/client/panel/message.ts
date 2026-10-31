import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";

import { Dialog } from "../../ui/modal.js";
import { ConfirmPrompt, PanelAction } from "./action.js";
import { PanelCategory } from "./chrome.js";
import {
  FacilitatorFormMessage,
  FacilitatorListMessage,
} from "./facilitators/message.js";
import { PanelFailure } from "./failure.js";
import {
  ProposalDetailMessage,
  ProposalFormMessage,
  ProposalListMessage,
} from "./proposals/message.js";
import { TrackFormMessage } from "./tracks/message.js";

export const PanelMessage = defineMessageUnion({
  ChangedEvent: { href: Schema.String },
  ClickedCategory: { category: PanelCategory },
  ClickedFold: {},
  CompletedAction: {
    action: PanelAction,
    failure: Schema.Option(PanelFailure),
  },
  ConfirmedAction: {},
  DismissedFlash: { id: Schema.String },
  GotConfirmDialogMessage: { message: Dialog.Message },
  RelayedFacilitatorForm: { message: FacilitatorFormMessage },
  RelayedFacilitatorList: { message: FacilitatorListMessage },
  RelayedProposalDetail: { message: ProposalDetailMessage },
  RelayedProposalForm: { message: ProposalFormMessage },
  RelayedProposalList: { message: ProposalListMessage },
  RelayedTrackForm: { message: TrackFormMessage },
  LeftPanel: {},
  LoadedStoredCategories: { collapsed: Schema.Array(PanelCategory) },
  PressedEscape: {},
  RequestedAction: { action: PanelAction },
  RequestedConfirm: { action: PanelAction, prompt: ConfirmPrompt },
  SelectedTimetableSession: { id: Schema.Int },
  StoredChrome: {},
  ToggledSidebar: { isOpen: Schema.Boolean },
});

export type PanelMessage = typeof PanelMessage.Type;
