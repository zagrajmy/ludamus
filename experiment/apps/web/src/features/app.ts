import { Option } from "effect";
import type { Document, HtmlBuilder } from "foldkit/html";

import type { Model } from "../client/model.js";
import { Message } from "../client/message.js";
import { eventsFeed } from "./events-feed.js";

const header = (model: Model, h: HtmlBuilder<Message>) =>
  h.header(
    [h.Class("border-b border-slate-200 bg-white")],
    [
      h.nav(
        [
          h.Class("mx-auto flex max-w-5xl items-center justify-between px-4 py-3"),
          h.AriaLabel("Main"),
        ],
        [
          h.a(
            [h.Href("/events/"), h.Class("text-lg font-semibold")],
            [model.shell.sphere.name]
          ),
          Option.match(model.shell.viewer, {
            onNone: () =>
              h.a([h.Href("/crowd/login-required/"), h.Class("underline")], ["Log in"]),
            onSome: (viewer) =>
              h.button(
                [h.OnClick(Message.ToggledMenu()), h.Class("underline")],
                [viewer.displayName]
              ),
          }),
        ]
      ),
    ]
  );

export const view = (model: Model, h: HtmlBuilder<Message>): Document => ({
  body: h.div(
    [h.Class("min-h-screen bg-slate-50 text-slate-900")],
    [
      header(model, h),
      h.main(
        [h.Class("mx-auto max-w-5xl px-4 py-8")],
        [
          Page(model, h),
        ]
      ),
    ]
  ),
  lang: model.shell.locale,
  title: pageTitle(model),
});

const Page = (model: Model, h: HtmlBuilder<Message>) =>
  model.page._tag === "EventsFeed"
    ? eventsFeed(model.page.events, h)
    : h.section([], [h.h1([h.Class("text-2xl font-bold")], ["Not found"])]);

const pageTitle = (model: Model) =>
  model.page._tag === "EventsFeed"
    ? `Events | ${model.shell.sphere.name}`
    : `Not found | ${model.shell.sphere.name}`;
