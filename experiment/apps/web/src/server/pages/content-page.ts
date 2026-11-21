import { Effect } from "effect";

import privacyPolicy from "../../../../../../src/ludamus/content/privacy-policy.md?raw";
import termsOfService from "../../../../../../src/ludamus/content/terms-of-service.md?raw";
import type {
  ContentPageFlags,
  ContentSlug,
} from "../../client/content-page/flags.js";
import { renderMarkdown } from "../markdown.js";

const documents: Readonly<Record<ContentSlug, string>> = {
  "privacy-policy": privacyPolicy,
  "terms-of-service": termsOfService,
};

export const loadContentPage = Effect.fn("ContentPage.load")(
  function* loadContentPage(slug: ContentSlug) {
    const flags: ContentPageFlags = {
      documentHtml: yield* Effect.sync(() => renderMarkdown(documents[slug])),
      slug,
    };

    return flags;
  }
);
