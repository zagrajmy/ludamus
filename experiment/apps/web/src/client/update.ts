import { Option } from "effect";
import { Update } from "foldkit";
import { UrlRequest } from "foldkit/navigation";
import { modifyFields } from "foldkit/struct";
import { toString as urlToString } from "foldkit/url";

import { LoadPage } from "./command.js";
import type { EventsFeedMessage } from "./events-feed/message.js";
import type { EventsFeedModel } from "./events-feed/model.js";
import { updateEventsFeed } from "./events-feed/update.js";
import { LandingMessage } from "./landing/message.js";
import type { LandingModel } from "./landing/model.js";
import { updateLanding } from "./landing/update.js";
import { Message } from "./message.js";
import { PageModel } from "./model.js";
import type { Model } from "./model.js";
import type { ShellMessage } from "./shell/message.js";
import type { ShellModel } from "./shell/model.js";
import { updateShell } from "./shell/update.js";

type Return = Update.Return<Model, Message>;

const foldShell = Update.foldChild({
  read: (model: Model) => Option.some(model.shell),
  toParentMessage: (message: ShellMessage) =>
    Message.GotShellMessage({ message }),
  update: updateShell,
  write: (model: Model, shell: ShellModel): Model =>
    modifyFields(model, { shell: () => shell }),
});

const foldEventsFeed = Update.foldChild({
  read: (model: Model) =>
    model.page._tag === "EventsFeed"
      ? Option.some(model.page.model)
      : Option.none(),
  toParentMessage: (message: EventsFeedMessage) =>
    Message.GotEventsFeedMessage({ message }),
  update: updateEventsFeed,
  write: (model: Model, feed: EventsFeedModel): Model => ({
    ...model,
    page: PageModel.EventsFeed({ model: feed }),
  }),
});

const foldLanding = Update.foldChild({
  read: (model: Model) =>
    model.page._tag === "Landing"
      ? Option.some(model.page.model)
      : Option.none(),
  toParentMessage: (message: LandingMessage) =>
    Message.GotLandingMessage({ message }),
  update: updateLanding,
  write: (model: Model, landing: LandingModel): Model => ({
    ...model,
    page: PageModel.Landing({ model: landing }),
  }),
});

export const update = (model: Model, message: Message): Return =>
  Message.match<Return>(message, {
    ChangedUrl: ({ url }) =>
      foldLanding(
        model,
        LandingMessage.GotLocationHash({
          hash: Option.getOrElse(url.hash, () => ""),
        })
      ),
    ClickedLink: ({ request }) =>
      UrlRequest.match<Return>(request, {
        External: ({ href }) => ({ commands: [LoadPage({ href })], model }),
        Internal: ({ url }) => ({
          commands: [LoadPage({ href: urlToString(url) })],
          model,
        }),
      }),
    GotEventsFeedMessage: ({ message: feedMessage }) =>
      foldEventsFeed(model, feedMessage),
    GotLandingMessage: ({ message: landingMessage }) =>
      foldLanding(model, landingMessage),
    GotShellMessage: ({ message: shellMessage }) =>
      foldShell(model, shellMessage),
    LeftPage: () => ({ model }),
  });
