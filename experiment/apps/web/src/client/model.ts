import { Schema } from "effect";
import { defineTaggedUnion } from "foldkit/schema";

import { AboutFlags } from "./about/flags.js";
import { ContentPageFlags } from "./content-page/flags.js";
import { EventsFeedFlags } from "./events-feed/flags.js";
import { EventsFeedModel } from "./events-feed/model.js";
import { LandingFlags } from "./landing/flags.js";
import { LandingModel } from "./landing/model.js";
import { NotFoundFlags, NotPortedFlags } from "./not-found/flags.js";
import { ShellFlags } from "./shell/flags.js";
import { ShellModel } from "./shell/model.js";

export const PageFlags = defineTaggedUnion({
  About: { flags: AboutFlags },
  ContentPage: { flags: ContentPageFlags },
  EventsFeed: { flags: EventsFeedFlags },
  Landing: { flags: LandingFlags },
  NotFound: { flags: NotFoundFlags },
  NotPorted: { flags: NotPortedFlags },
});
export type PageFlags = typeof PageFlags.Type;

export const Flags = Schema.Struct({ page: PageFlags, shell: ShellFlags });
export type Flags = typeof Flags.Type;

export const PageModel = defineTaggedUnion({
  About: { model: AboutFlags },
  ContentPage: { model: ContentPageFlags },
  EventsFeed: { model: EventsFeedModel },
  Landing: { model: LandingModel },
  NotFound: { model: NotFoundFlags },
  NotPorted: { model: NotPortedFlags },
});
export type PageModel = typeof PageModel.Type;

export const Model = Schema.Struct({ page: PageModel, shell: ShellModel });
export type Model = typeof Model.Type;
