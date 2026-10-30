import { Command } from "foldkit";
import type { Runtime, Update } from "foldkit";

import { initEventsFeed } from "./events-feed/model.js";
import { ReadLocationHash, WaitForChoreography } from "./landing/command.js";
import type { LandingMessage } from "./landing/message.js";
import { initLanding } from "./landing/model.js";
import { Message } from "./message.js";
import { PageFlags, PageModel } from "./model.js";
import type { Flags, Model } from "./model.js";
import { ReadStoredConsent, ReadStoredTheme } from "./shell/command.js";
import type { ShellMessage } from "./shell/message.js";
import { initShell } from "./shell/model.js";

const toLanding = (message: LandingMessage) =>
  Message.GotLandingMessage({ message });

const toShell = (message: ShellMessage) => Message.GotShellMessage({ message });

type PageInit = Readonly<{
  commands: Update.Commands<Message>;
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
  });

export const init: Runtime.RoutingApplicationInit<Model, Message, Flags> = (
  flags
) => {
  const page = initPage(flags.page);

  return {
    commands: [
      Command.mapMessage(ReadStoredTheme(), toShell),
      Command.mapMessage(ReadStoredConsent(), toShell),
      ...page.commands,
    ],
    model: { page: page.page, shell: initShell(flags.shell) },
  };
};
