import { Command } from "foldkit";
import type { Runtime, Update } from "foldkit";

import { initEnrollPage } from "./enroll-page/model.js";
import type { EventPageMessage } from "./event-page/message.js";
import { initEventPage } from "./event-page/model.js";
import { initEventPageCommands } from "./event-page/update.js";
import { initEventsFeed } from "./events-feed/model.js";
import { ReadLocationHash, WaitForChoreography } from "./landing/command.js";
import type { LandingMessage } from "./landing/message.js";
import { initLanding } from "./landing/model.js";
import { ReadStoredCategories } from "./panel/command.js";
import type { PanelMessage } from "./panel/message.js";
import { initPanel } from "./panel/model.js";
import { initPropose } from "./propose/model.js";
import { Message } from "./message.js";
import { initOfferPage } from "./offer-page/model.js";
import { PageFlags, PageModel } from "./model.js";
import type { Flags, Model } from "./model.js";
import { ReadStoredConsent, ReadStoredTheme } from "./shell/command.js";
import type { ShellMessage } from "./shell/message.js";
import { initShell } from "./shell/model.js";

const toLanding = (message: LandingMessage) =>
  Message.GotLandingMessage({ message });

const toShell = (message: ShellMessage) => Message.GotShellMessage({ message });

type PageInit = Readonly<{
  commands?: Update.Commands<Message>;
  page: PageModel;
}>;

const initPage = (flags: PageFlags): PageInit =>
  PageFlags.match<PageInit>(flags, {
    About: ({ flags: about }) => ({
      page: PageModel.About({ model: about }),
    }),
    ContentPage: ({ flags: content }) => ({
      page: PageModel.ContentPage({ model: content }),
    }),
    EnrollPage: ({ flags: enroll }) => ({
      page: PageModel.EnrollPage({ model: initEnrollPage(enroll) }),
    }),
    OfferPage: ({ flags: offer }) => ({
      page: PageModel.OfferPage({ model: initOfferPage(offer) }),
    }),
    EventPage: ({ flags: eventPage }) => {
      const model = initEventPage(eventPage);

      const commands: Update.Commands<Message> = initEventPageCommands(
        model
      ).map((command) =>
        Command.mapMessage(command, (message: EventPageMessage) =>
          Message.GotEventPageMessage({ message })
        )
      );

      return {
        commands,
        page: PageModel.EventPage({ model }),
      };
    },
    EventsFeed: ({ flags: feed }) => ({
      page: PageModel.EventsFeed({ model: initEventsFeed(feed) }),
    }),
    Landing: ({ flags: landing }) => ({
      commands: [
        Command.mapMessage(ReadLocationHash(), toLanding),
        Command.mapMessage(WaitForChoreography(), toLanding),
      ],
      page: PageModel.Landing({ model: initLanding(landing) }),
    }),
    NotFound: ({ flags: notFound }) => ({
      page: PageModel.NotFound({ model: notFound }),
    }),
    NotPorted: ({ flags: notPorted }) => ({
      page: PageModel.NotPorted({ model: notPorted }),
    }),
    Panel: ({ flags: panel }) => ({
      commands: [
        Command.mapMessage(ReadStoredCategories(), (message: PanelMessage) =>
          Message.GotPanelMessage({ message })
        ),
      ],
      page: PageModel.Panel({ model: initPanel(panel) }),
    }),
    Propose: ({ flags: propose }) => ({
      page: PageModel.Propose({ model: initPropose(propose) }),
    }),
  });

export const init: Runtime.RoutingApplicationInit<Model, Message, Flags> = (
  flags
) => {
  const page = initPage(flags.page);

  return {
    commands: [
      Command.mapMessage(ReadStoredTheme(), toShell),
      Command.mapMessage(ReadStoredConsent(), toShell),
      ...(page.commands ?? []),
    ],
    model: { page: page.page, shell: initShell(flags.shell) },
  };
};
