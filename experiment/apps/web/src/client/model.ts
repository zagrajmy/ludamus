import { Schema } from "effect";
import { defineTaggedUnion } from "foldkit/schema";

import { AboutFlags } from "./about/flags.js";
import { ContentPageFlags } from "./content-page/flags.js";
import { EnrollPageFlags } from "./enroll-page/flags.js";
import { EnrollPageModel } from "./enroll-page/model.js";
import { EventPageFlags } from "./event-page/flags.js";
import { EventPageModel } from "./event-page/model.js";
import { EventsFeedFlags } from "./events-feed/flags.js";
import { EventsFeedModel } from "./events-feed/model.js";
import { LandingFlags } from "./landing/flags.js";
import { LandingModel } from "./landing/model.js";
import { NotFoundFlags, NotPortedFlags } from "./not-found/flags.js";
import { OfferPageFlags } from "./offer-page/flags.js";
import { OfferPageModel } from "./offer-page/model.js";
import { PanelFlags } from "./panel/flags.js";
import { PanelModel } from "./panel/model.js";
import { ProposeFlags } from "./propose/flags.js";
import { ProposeModel } from "./propose/model.js";
import { ShellFlags } from "./shell/flags.js";
import { ShellModel } from "./shell/model.js";

export const PageFlags = defineTaggedUnion({
  About: { flags: AboutFlags },
  ContentPage: { flags: ContentPageFlags },
  EnrollPage: { flags: EnrollPageFlags },
  EventPage: { flags: EventPageFlags },
  EventsFeed: { flags: EventsFeedFlags },
  Landing: { flags: LandingFlags },
  NotFound: { flags: NotFoundFlags },
  NotPorted: { flags: NotPortedFlags },
  OfferPage: { flags: OfferPageFlags },
  Panel: { flags: PanelFlags },
  Propose: { flags: ProposeFlags },
});

export type PageFlags = typeof PageFlags.Type;

export const Flags = Schema.Struct({ page: PageFlags, shell: ShellFlags });

export type Flags = typeof Flags.Type;

export const PageModel = defineTaggedUnion({
  About: { model: AboutFlags },
  ContentPage: { model: ContentPageFlags },
  EnrollPage: { model: EnrollPageModel },
  EventPage: { model: EventPageModel },
  EventsFeed: { model: EventsFeedModel },
  Landing: { model: LandingModel },
  NotFound: { model: NotFoundFlags },
  NotPorted: { model: NotPortedFlags },
  OfferPage: { model: OfferPageModel },
  Panel: { model: PanelModel },
  Propose: { model: ProposeModel },
});

export type PageModel = typeof PageModel.Type;

export const Model = Schema.Struct({ page: PageModel, shell: ShellModel });

export type Model = typeof Model.Type;
