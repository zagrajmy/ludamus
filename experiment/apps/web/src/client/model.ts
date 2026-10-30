import { Schema } from "effect";
import { EventSummary, Sphere } from "@zagrajmy/core";
import { defineTaggedUnion } from "foldkit/schema";

export const Viewer = Schema.Struct({
  displayName: Schema.String,
  id: Schema.Int,
});

export const Shell = Schema.Struct({
  locale: Schema.Literals(["en", "pl"]),
  sphere: Sphere,
  viewer: Schema.OptionFromOptional(Viewer),
});
export type Shell = typeof Shell.Type;

export const Page = defineTaggedUnion({
  EventsFeed: { events: Schema.Array(EventSummary) },
  NotFound: { path: Schema.String },
});
export type Page = typeof Page.Type;

export const Flags = Schema.Struct({
  page: Page,
  shell: Shell,
});
export type Flags = typeof Flags.Type;

export const Model = Schema.Struct({
  ...Flags.fields,
  menuOpen: Schema.Boolean,
});
export type Model = typeof Model.Type;
