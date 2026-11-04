import { Option, Predicate } from "effect";
import { Update } from "foldkit";
import { UrlRequest } from "foldkit/navigation";
import { modifyFields } from "foldkit/struct";
import { toString as urlToString } from "foldkit/url";

import type { ProposalAcceptMessage } from "./accept/message.js";
import type { ProposalAcceptModel } from "./accept/model.js";
import { updateProposalAccept } from "./accept/update.js";
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
import { Message } from "./message.js";
import { PageModel } from "./model.js";
import type { Model } from "./model.js";
import type { OfferPageMessage } from "./offer-page/message.js";
import type { OfferPageModel } from "./offer-page/model.js";
import { updateOfferPage } from "./offer-page/update.js";
import type { PanelMessage } from "./panel/message.js";
import type { PanelModel } from "./panel/model.js";
import { updatePanel } from "./panel/update.js";
import type { ProposeMessage } from "./propose/message.js";
import type { ProposeModel } from "./propose/model.js";
import { updatePropose } from "./propose/update.js";
import type { ShellMessage } from "./shell/message.js";
import type { ShellModel } from "./shell/model.js";
import { updateShell } from "./shell/update.js";

type Return = Update.Return<Model, Message>;

const foldEnrollPage = Update.foldChild({
  read: (model: Model) =>
    Predicate.isTagged("EnrollPage")(model.page)
      ? Option.some(model.page.model)
      : Option.none(),
  toParentMessage: (message: EnrollPageMessage) =>
    Message.GotEnrollPageMessage({ message }),
  update: updateEnrollPage,
  write: (model: Model, enroll: EnrollPageModel): Model => ({
    ...model,
    page: PageModel.EnrollPage({ model: enroll }),
  }),
});

const foldOfferPage = Update.foldChild({
  read: (model: Model) =>
    Predicate.isTagged("OfferPage")(model.page)
      ? Option.some(model.page.model)
      : Option.none(),
  toParentMessage: (message: OfferPageMessage) =>
    Message.GotOfferPageMessage({ message }),
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
    Predicate.isTagged("EventsFeed")(model.page)
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
    Predicate.isTagged("EventPage")(model.page)
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
  Predicate.isTagged("EventPage")(model.page) &&
  pathname === `/event/${model.page.model.hero.slug}/`;

const foldLanding = Update.foldChild({
  read: (model: Model) =>
    Predicate.isTagged("Landing")(model.page)
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
    Predicate.isTagged("Panel")(model.page)
      ? Option.some(model.page.model)
      : Option.none(),
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
    Predicate.isTagged("Propose")(model.page)
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

const foldProposalAccept = Update.foldChild({
  read: (model: Model) =>
    Predicate.isTagged("ProposalAccept")(model.page)
      ? Option.some(model.page.model)
      : Option.none(),
  toParentMessage: (message: ProposalAcceptMessage) =>
    Message.GotProposalAcceptMessage({ message }),
  update: updateProposalAccept,
  write: (model: Model, accept: ProposalAcceptModel): Model => ({
    ...model,
    page: PageModel.ProposalAccept({ model: accept }),
  }),
});

export const update = (model: Model, message: Message): Return =>
  Message.match<Return>(message, {
    ChangedUrl: ({ url }) =>
      Predicate.isTagged("EventPage")(model.page)
        ? foldEventPage(
            model,
            EventPageMessage.ChangedUrl({ search: searchOf(url) })
          )
        : foldLanding(
            model,
            LandingMessage.ReadLocationHash({
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
    GotEventPageMessage: ({ message: eventPageMessage }) =>
      foldEventPage(model, eventPageMessage),
    GotEventsFeedMessage: ({ message: feedMessage }) =>
      foldEventsFeed(model, feedMessage),
    GotLandingMessage: ({ message: landingMessage }) =>
      foldLanding(model, landingMessage),
    GotOfferPageMessage: ({ message: offerMessage }) =>
      foldOfferPage(model, offerMessage),
    GotPanelMessage: ({ message: panelMessage }) =>
      foldPanel(model, panelMessage),
    GotProposalAcceptMessage: ({ message: acceptMessage }) =>
      foldProposalAccept(model, acceptMessage),
    GotProposeMessage: ({ message: proposeMessage }) =>
      foldPropose(model, proposeMessage),
    GotShellMessage: ({ message: shellMessage }) =>
      foldShell(model, shellMessage),
    LeftPage: () => ({ model }),
  });
