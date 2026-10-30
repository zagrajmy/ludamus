import type { Document, Html, HtmlBuilder } from "foldkit/html";

import { Message } from "../client/message.js";
import { PageModel } from "../client/model.js";
import type { Model } from "../client/model.js";
import { translator } from "../ui/i18n.js";
import { aboutTitle, aboutView } from "./about/view.js";
import { contentPageTitle, contentPageView } from "./content-page/view.js";
import { eventsFeedTitle, eventsFeedView } from "./events-feed/view.js";
import { landingTitle, landingView } from "./landing/view.js";
import {
  notFoundTitle,
  notFoundView,
  notPortedTitle,
  notPortedView,
} from "./not-found/view.js";
import type { PageContext } from "./page-context.js";
import { documentTitle } from "./shell/title.js";
import type { PageTitle } from "./shell/title.js";
import { shellView } from "./shell/view.js";
import type { PageLayout } from "./shell/view.js";

type RenderedPage = Readonly<{
  content: Html;
  layout: PageLayout;
  title: PageTitle;
}>;

const renderPage = (
  model: Model,
  context: PageContext,
  h: HtmlBuilder<Message>
): RenderedPage =>
  PageModel.match<RenderedPage>(model.page, {
    About: ({ model: about }) => ({
      content: aboutView(about, context, h),
      layout: "contained",
      title: aboutTitle(context),
    }),
    ContentPage: ({ model: content }) => ({
      content: contentPageView(content, context, h),
      layout: "contained",
      title: contentPageTitle(content, context),
    }),
    EventsFeed: ({ model: feed }) => ({
      content: h.submodel({
        model: feed,
        slotId: "events-feed",
        toParentMessage: (message) => Message.GotEventsFeedMessage({ message }),
        view: eventsFeedView,
        viewInputs: { shell: model.shell },
      }),
      layout: "contained",
      title: eventsFeedTitle(context),
    }),
    Landing: ({ model: landing }) => ({
      content: h.submodel({
        model: landing,
        slotId: "landing",
        toParentMessage: (message) => Message.GotLandingMessage({ message }),
        view: landingView,
        viewInputs: { shell: model.shell },
      }),
      layout: "bleed",
      title: landingTitle(context),
    }),
    NotFound: () => ({
      content: notFoundView(context, h),
      layout: "contained",
      title: notFoundTitle(context),
    }),
    NotPorted: ({ model: notPorted }) => ({
      content: notPortedView(notPorted, context, h),
      layout: "contained",
      title: notPortedTitle(notPorted),
    }),
  });

export const pageContext = (model: Model): PageContext => ({
  shell: model.shell,
  translator: translator(model.shell.locale),
});

export const view = (model: Model, h: HtmlBuilder<Message>): Document => {
  const context = pageContext(model);
  const page = renderPage(model, context, h);

  return {
    body: shellView(
      {
        body: { content: [page.content], layout: page.layout },
        shell: model.shell,
        toMessage: (message) => Message.GotShellMessage({ message }),
        translator: context.translator,
      },
      h
    ),
    lang: model.shell.locale,
    title: documentTitle({
      isRootSphere: model.shell.isRootSphere,
      page: page.title,
      sphereName: model.shell.sphere.name,
    }),
  };
};
