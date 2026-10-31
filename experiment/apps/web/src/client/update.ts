import { Option } from "effect";
import { Update } from "foldkit";
import { UrlRequest } from "foldkit/navigation";
import { modifyFields } from "foldkit/struct";
import { toString as urlToString } from "foldkit/url";

import { LoadPage } from "./command.js";
import type { EnrollPageMessage } from "./enroll-page/message.js";
import type { EnrollPageModel } from "./enroll-page/model.js";
import { updateEnrollPage } from "./enroll-page/update.js";
import { EventPageMessage } from "./event-page/message.js";
import type { EventPageModel } from "./event-page/model.js";
import { updateEventPage } from "./event-page/update.js";
import type { EventsFeedMessage } from "./events-feed/message.js";
import type { EventsFeedModel } from "./events-feed/model.js";
import { updateEventsFeed } from "./events-feed/update.js";
import { LandingMessage } from "./landing/message.js";
import type { LandingModel } from "./landing/model.js";
import { updateLanding } from "./landing/update.js";
import type { PanelMessage } from "./panel/message.js";
import type { PanelModel } from "./panel/model.js";
import { updatePanel } from "./panel/update.js";
import type { ProposeMessage } from "./propose/message.js";
import type { ProposeModel } from "./propose/model.js";
import { updatePropose } from "./propose/update.js";
import { Message } from "./message.js";
import type { OfferPageMessage } from "./offer-page/message.js";
import type { OfferPageModel } from "./offer-page/model.js";
import { updateOfferPage } from "./offer-page/update.js";
import { PageModel } from "./model.js";
import type { Model } from "./model.js";
import type { ShellMessage } from "./shell/message.js";
import type { ShellModel } from "./shell/model.js";
import { updateShell } from "./shell/update.js";

type Return = Update.Return<Model, Message>;

const foldEnrollPage = Update.foldChild({
  read: (model: Model) =>
    model.page._tag === "EnrollPage" ? Option.some(model.page.model) : Option.none(),
  toParentMessage: (message: EnrollPageMessage) => Message.GotEnrollPageMessage({ message }),
  update: updateEnrollPage,
  write: (model: Model, enroll: EnrollPageModel): Model => ({
    ...model,
    page: PageModel.EnrollPage({ model: enroll }),
  }),
});

const foldOfferPage = Update.foldChild({
  read: (model: Model) =>
    model.page._tag === "OfferPage" ? Option.some(model.page.model) : Option.none(),
  toParentMessage: (message: OfferPageMessage) => Message.GotOfferPageMessage({ message }),
  update: updateOfferPage,
  write: (model: Model, offer: OfferPageModel): Model => ({
    ...model,
    page: PageModel.OfferPage({ model: offer }),
  }),
});

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

const foldEventPage = Update.foldChild({
  read: (model: Model) =>
    model.page._tag === "EventPage"
      ? Option.some(model.page.model)
      : Option.none(),
  toParentMessage: (message: EventPageMessage) =>
    Message.GotEventPageMessage({ message }),
  update: updateEventPage,
  write: (model: Model, eventPage: EventPageModel): Model => ({
    ...model,
    page: PageModel.EventPage({ model: eventPage }),
  }),
});

const searchOf = (url: { readonly search: Option.Option<string> }) => {
  const search = Option.getOrElse(url.search, () => "");

  return search === "" || search.startsWith("?") ? search : `?${search}`;
};

const hashOf = (url: { readonly hash: Option.Option<string> }) => {
  const hash = Option.getOrElse(url.hash, () => "");

  return hash === "" || hash.startsWith("#") ? hash : `#${hash}`;
};

const isOnEventPage = (model: Model, pathname: string) =>
  model.page._tag === "EventPage" &&
  pathname === `/event/${model.page.model.hero.slug}/`;

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

const foldPanel = Update.foldChild({
  read: (model: Model) =>
    model.page._tag === "Panel" ? Option.some(model.page.model) : Option.none(),
  toParentMessage: (message: PanelMessage) =>
    Message.GotPanelMessage({ message }),
  update: updatePanel,
  write: (model: Model, panel: PanelModel): Model => ({
    ...model,
    page: PageModel.Panel({ model: panel }),
  }),
});

const foldPropose = Update.foldChild({
  read: (model: Model) =>
    model.page._tag === "Propose"
      ? Option.some(model.page.model)
      : Option.none(),
  toParentMessage: (message: ProposeMessage) =>
    Message.GotProposeMessage({ message }),
  update: updatePropose,
  write: (model: Model, propose: ProposeModel): Model => ({
    ...model,
    page: PageModel.Propose({ model: propose }),
  }),
});

export const update = (model: Model, message: Message): Return =>
  Message.match<Return>(message, {
    ChangedUrl: ({ url }) =>
      model.page._tag === "EventPage"
        ? foldEventPage(
            model,
            EventPageMessage.ChangedUrl({ search: searchOf(url) })
          )
        : foldLanding(
        model,
        LandingMessage.GotLocationHash({
          hash: Option.getOrElse(url.hash, () => ""),
        })
      ),
    ClickedLink: ({ request }) =>
      UrlRequest.match<Return>(request, {
        External: ({ href }) => ({ commands: [LoadPage({ href })], model }),
        Internal: ({ url }) =>
          isOnEventPage(model, url.pathname)
            ? foldEventPage(
                model,
                EventPageMessage.ClickedSamePageLink({
                  hash: hashOf(url),
                  search: searchOf(url),
                })
              )
            : {
                commands: [LoadPage({ href: urlToString(url) })],
                model,
              },
      }),
    GotEnrollPageMessage: ({ message: enrollMessage }) =>
      foldEnrollPage(model, enrollMessage),
    GotOfferPageMessage: ({ message: offerMessage }) =>
      foldOfferPage(model, offerMessage),
    GotEventPageMessage: ({ message: eventPageMessage }) =>
      foldEventPage(model, eventPageMessage),
    GotEventsFeedMessage: ({ message: feedMessage }) =>
      foldEventsFeed(model, feedMessage),
    GotLandingMessage: ({ message: landingMessage }) =>
      foldLanding(model, landingMessage),
    GotPanelMessage: ({ message: panelMessage }) =>
      foldPanel(model, panelMessage),
    GotProposeMessage: ({ message: proposeMessage }) =>
      foldPropose(model, proposeMessage),
    GotShellMessage: ({ message: shellMessage }) =>
      foldShell(model, shellMessage),
    LeftPage: () => ({ model }),
  });
