import type { HtmlBuilder } from "foldkit/html";
import { defineView } from "foldkit/submodel";

import { OfferPageMessage } from "../../client/offer-page/message.js";
import type { OfferPageModel } from "../../client/offer-page/model.js";
import { button } from "../../ui/button.js";
import type { Translator } from "../../ui/i18n.js";
import { pageContextOf } from "../page-context.js";
import type { PageInputs } from "../page-context.js";
import type { PageTitle } from "../shell/title.js";

export const offerPageTitle = (
  model: OfferPageModel,
  translator: Translator
): PageTitle => ({
  name: `${translator.t("Claim your spot")} • ${model.offer.sessionTitle}`,
  sphereSuffix: true,
});

export const offerPageView = defineView<
  OfferPageModel,
  OfferPageMessage,
  PageInputs
>((model, inputs, h: HtmlBuilder<OfferPageMessage>) => {
  const { t } = pageContextOf(inputs.shell).translator;

  return h.div(
    [h.Class("max-w-2xl mx-auto")],
    [
      h.h1(
        [h.Class("text-2xl sm:text-3xl font-bold text-foreground mb-2")],
        [t("Claim your spot")]
      ),
      h.p(
        [h.Class("text-foreground-secondary mb-6")],
        [t("A seat is waiting for you")]
      ),
      h.div(
        [h.Class("card mb-4")],
        [
          h.div(
            [h.Class("card-header bg-primary text-white")],
            [h.h2([h.Class("font-semibold mb-0")], [model.offer.sessionTitle])]
          ),
          h.div(
            [h.Class("card-body")],
            [
              h.p(
                [],
                [
                  t(
                    "A seat is being held for you. Claim it before the deadline below or it will be released."
                  ),
                ]
              ),
              h.p(
                [],
                [h.strong([], [t("Claim by:")]), ` ${model.deadlineLabel}`]
              ),
              h.div(
                [h.Class("flex flex-wrap gap-2")],
                [
                  button(
                    {
                      attributes: [h.OnClick(OfferPageMessage.ClickedClaim())],
                      disabled: model.busy,
                      text: t("Claim my spot"),
                      type: "button",
                    },
                    h
                  ),
                  button(
                    {
                      attributes: [
                        h.DataAttribute("ph-no-capture", ""),
                        h.OnClick(OfferPageMessage.ClickedDecline()),
                      ],
                      disabled: model.busy,
                      text: t("Decline offer"),
                      type: "button",
                      variant: "secondary",
                    },
                    h
                  ),
                ]
              ),
            ]
          ),
        ]
      ),
    ]
  );
});
