import { Option, Predicate } from "effect";
import { Command } from "foldkit";
import type { Update } from "foldkit";
import { modifyFields } from "foldkit/struct";

import { translator } from "../../ui/i18n.js";
import { Dialog } from "../../ui/modal.js";
import {
  NavigateWithFlash,
  RunAction,
  StoreCategory,
  ToggleFold,
} from "./command.js";
import type {
  FacilitatorFormMessage,
  FacilitatorListMessage,
} from "./facilitators/message.js";
import {
  updateFacilitatorForm,
  updateFacilitatorList,
} from "./facilitators/update.js";
import { PanelMessage } from "./message.js";
import type { PanelModel } from "./model.js";
import { PanelPageModel } from "./model.js";
import { PanelOut } from "./out.js";
import { failureOutcome, successOutcome } from "./outcome.js";
import type {
  ProposalDetailMessage,
  ProposalFormMessage,
  ProposalListMessage,
} from "./proposals/message.js";
import {
  updateProposalDetail,
  updateProposalForm,
  updateProposalList,
} from "./proposals/update.js";
import { updateTrackForm } from "./tracks/form-update.js";
import type { TrackFormMessage } from "./tracks/message.js";

type Return = Update.Return<PanelModel, PanelMessage>;

const toDialog = (message: Dialog.Message) =>
  PanelMessage.GotConfirmDialogMessage({ message });

const withDialog = (
  model: PanelModel,
  result: ReturnType<typeof Dialog.open>
): Return => ({
  commands: (result.commands ?? []).map((command) =>
    Command.mapMessage(command, toDialog)
  ),
  model: modifyFields(model, { confirmDialog: () => result.model }),
});

const handleOut = (model: PanelModel, out: PanelOut | undefined): Return => {
  if (out === undefined) {
    return { model };
  }

  return PanelOut.match<Return>(out, {
    RequestedAction: ({ action }) => ({
      commands: [RunAction({ action })],
      model: modifyFields(model, { isActing: () => true }),
    }),
    RequestedConfirm: ({ action, prompt }) =>
      withDialog(
        modifyFields(model, {
          pendingConfirm: () => Option.some({ action, prompt }),
        }),
        Dialog.open(model.confirmDialog)
      ),
    RequestedNavigation: ({ href, notes }) => ({
      commands: [NavigateWithFlash({ href, notes })],
      model,
    }),
  });
};

type PageResult<Model, Message> = Readonly<{
  commands?: Update.Commands<Message>;
  model: Model;
  outMessage?: PanelOut;
}>;

const foldPage = <Model, Message>(
  model: PanelModel,
  options: Readonly<{
    lift: (message: Message) => PanelMessage;
    result: PageResult<Model, Message>;
    wrap: (page: Model) => PanelModel["page"];
  }>
): Return => {
  const next = handleOut(
    modifyFields(model, { page: () => options.wrap(options.result.model) }),
    options.result.outMessage
  );

  return {
    commands: [
      ...(options.result.commands ?? []).map((command) =>
        Command.mapMessage(command, options.lift)
      ),
      ...(next.commands ?? []),
    ],
    model: next.model,
  };
};

const foldTrackForm = (model: PanelModel, message: TrackFormMessage): Return =>
  Predicate.isTagged(model.page, "TrackForm")
    ? foldPage(model, {
        lift: (inner: TrackFormMessage) =>
          PanelMessage.RelayedTrackForm({ message: inner }),
        result: updateTrackForm(
          model.page.model,
          message,
          translator(model.chrome.locale)
        ),
        wrap: (page) => PanelPageModel.TrackForm({ model: page }),
      })
    : { model };

const foldFacilitatorForm = (
  model: PanelModel,
  message: FacilitatorFormMessage
): Return =>
  Predicate.isTagged(model.page, "FacilitatorForm")
    ? foldPage(model, {
        lift: (inner: FacilitatorFormMessage) =>
          PanelMessage.RelayedFacilitatorForm({ message: inner }),
        result: updateFacilitatorForm(
          model.page.model,
          message,
          translator(model.chrome.locale)
        ),
        wrap: (page) => PanelPageModel.FacilitatorForm({ model: page }),
      })
    : { model };

const liftList = (inner: FacilitatorListMessage) =>
  PanelMessage.RelayedFacilitatorList({ message: inner });

const foldFacilitatorList = (
  model: PanelModel,
  message: FacilitatorListMessage
): Return => {
  if (Predicate.isTagged(model.page, "Facilitators")) {
    return foldPage(model, {
      lift: liftList,
      result: updateFacilitatorList(model.page.model, message),
      wrap: (page) => PanelPageModel.Facilitators({ model: page }),
    });
  }

  if (Predicate.isTagged(model.page, "FacilitatorBin")) {
    return foldPage(model, {
      lift: liftList,
      result: updateFacilitatorList(model.page.model, message),
      wrap: (page) => PanelPageModel.FacilitatorBin({ model: page }),
    });
  }

  return { model };
};

const foldProposals = (model: PanelModel, message: PanelMessage): Return => {
  const words = translator(model.chrome.locale);

  if (
    Predicate.isTagged(message, "RelayedProposalList") &&
    Predicate.isTagged(model.page, "Proposals")
  ) {
    return foldPage(model, {
      lift: (inner: ProposalListMessage) =>
        PanelMessage.RelayedProposalList({ message: inner }),
      result: updateProposalList(model.page.model, message.message),
      wrap: (page) => PanelPageModel.Proposals({ model: page }),
    });
  }

  if (
    Predicate.isTagged(message, "RelayedProposalDetail") &&
    Predicate.isTagged(model.page, "ProposalDetail")
  ) {
    return foldPage(model, {
      lift: (inner: ProposalDetailMessage) =>
        PanelMessage.RelayedProposalDetail({ message: inner }),
      result: updateProposalDetail(model.page.model, message.message),
      wrap: (page) => PanelPageModel.ProposalDetail({ model: page }),
    });
  }

  if (
    Predicate.isTagged(message, "RelayedProposalForm") &&
    Predicate.isTagged(model.page, "ProposalForm")
  ) {
    return foldPage(model, {
      lift: (inner: ProposalFormMessage) =>
        PanelMessage.RelayedProposalForm({ message: inner }),
      result: updateProposalForm(model.page.model, message.message, words),
      wrap: (page) => PanelPageModel.ProposalForm({ model: page }),
    });
  }

  return { model };
};

const toggledCategory = (
  collapsed: PanelModel["chrome"]["collapsed"],
  category: PanelModel["chrome"]["collapsed"][number]
) =>
  collapsed.includes(category)
    ? collapsed.filter((known) => known !== category)
    : [...collapsed, category];

export const updatePanel = (model: PanelModel, message: PanelMessage): Return =>
  PanelMessage.match<Return>(message, {
    ChangedEvent: ({ href }) => ({
      commands: [NavigateWithFlash({ href, notes: [] })],
      model,
    }),
    ClickedCategory: ({ category }) => {
      const collapsed = toggledCategory(model.chrome.collapsed, category);

      return {
        commands: [
          StoreCategory({ category, collapsed: collapsed.includes(category) }),
        ],
        model: modifyFields(model, {
          chrome: (chrome) => modifyFields(chrome, { collapsed: () => collapsed }),
        }),
      };
    },
    ClickedFold: () => ({ commands: [ToggleFold()], model }),
    CompletedAction: ({ action, failure }) => {
      const words = translator(model.chrome.locale);

      const outcome = Option.match(failure, {
        onNone: () => successOutcome(action, words),
        onSome: (found) => failureOutcome(action, found, words),
      });

      return {
        commands: [
          NavigateWithFlash({ href: outcome.href, notes: outcome.notes }),
        ],
        model,
      };
    },
    ConfirmedAction: () =>
      Option.match(model.pendingConfirm, {
        onNone: () => ({ model }),
        onSome: ({ action }) => {
          const closed = withDialog(model, Dialog.close(model.confirmDialog));

          return {
            commands: [...(closed.commands ?? []), RunAction({ action })],
            model: modifyFields(closed.model, { isActing: () => true }),
          };
        },
      }),
    DismissedFlash: ({ id }) => ({
      model: modifyFields(model, {
        chrome: (chrome) =>
          modifyFields(chrome, { dismissedFlashIds: (ids) => [...ids, id] }),
      }),
    }),
    GotConfirmDialogMessage: ({ message: dialogMessage }) =>
      withDialog(model, Dialog.update(model.confirmDialog, dialogMessage)),
    RelayedFacilitatorForm: ({ message: formMessage }) =>
      foldFacilitatorForm(model, formMessage),
    RelayedFacilitatorList: ({ message: listMessage }) =>
      foldFacilitatorList(model, listMessage),
    RelayedProposalDetail: () => foldProposals(model, message),
    RelayedProposalForm: () => foldProposals(model, message),
    RelayedProposalList: () => foldProposals(model, message),
    LoadedStoredCategories: ({ collapsed }) => ({
      model: modifyFields(model, {
        chrome: (chrome) => modifyFields(chrome, { collapsed: () => collapsed }),
      }),
    }),
    RelayedTrackForm: ({ message: formMessage }) =>
      foldTrackForm(model, formMessage),
    LeftPanel: () => ({ model }),
    PressedEscape: () => ({
      model: modifyFields(model, {
        chrome: (chrome) => modifyFields(chrome, { isSidebarOpen: () => false }),
      }),
    }),
    RequestedAction: ({ action }) =>
      handleOut(model, PanelOut.RequestedAction({ action })),
    RequestedConfirm: ({ action, prompt }) =>
      handleOut(model, PanelOut.RequestedConfirm({ action, prompt })),
    SelectedTimetableSession: ({ id }) =>
      PanelPageModel.match<Return>(model.page, {
        Cfp: () => ({ model }),
        Dashboard: () => ({ model }),
        FacilitatorBin: () => ({ model }),
        FacilitatorDetail: () => ({ model }),
        FacilitatorForm: () => ({ model }),
        Facilitators: () => ({ model }),
        ProposalDetail: () => ({ model }),
        ProposalForm: () => ({ model }),
        Proposals: () => ({ model }),
        Timetable: ({ model: timetable }) => ({
          model: modifyFields(model, {
            page: () =>
              PanelPageModel.Timetable({
                model: modifyFields(timetable, { selected: () => Option.some(id) }),
              }),
          }),
        }),
        TrackForm: () => ({ model }),
        Tracks: () => ({ model }),
      }),
    StoredChrome: () => ({ model }),
    ToggledSidebar: ({ isOpen }) => ({
      model: modifyFields(model, {
        chrome: (chrome) => modifyFields(chrome, { isSidebarOpen: () => isOpen }),
      }),
    }),
  });
