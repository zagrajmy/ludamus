import type { HtmlBuilder } from "foldkit/html";
import { defineView } from "foldkit/submodel";

import { LandingMessage } from "../../client/landing/message.js";
import type { Audience, LandingModel } from "../../client/landing/model.js";
import { playersConventionsHash } from "../../client/landing/model.js";
import { cx } from "../../ui/cx.js";
import type { Translator } from "../../ui/i18n.js";
import { pageContextOf } from "../page-context.js";
import type { PageContext, PageInputs } from "../page-context.js";
import type { PageTitle } from "../shell/title.js";

export const landingTitle = (context: PageContext): PageTitle => ({
  name: context.translator.t("Zagrajmy • conventions and events"),
  sphereSuffix: false,
});

export const landingDescription = (translator: Translator) =>
  translator.t(
    "Zagrajmy runs your event programme: proposals, review, the schedule, the event page, enrollment with waiting lists, and print. Write to us: kontakt@zagrajmy.net"
  );

type H = HtmlBuilder<LandingMessage>;

const switchLabel = (
  options: Readonly<{ audience: Audience; label: string }>,
  h: H
) => {
  const input = options.audience === "organizers" ? "aud-org" : "aud-gracz";

  return h.label(
    [
      h.For(input),
      h.Class(
        `cursor-pointer select-none text-[0.86rem] font-semibold text-foreground-secondary px-[0.85rem] py-[0.32rem] rounded-full transition-colors hover:text-foreground ${
          options.audience === "organizers"
            ? "group-has-[#aud-org:checked]/aud:bg-bg-secondary group-has-[#aud-org:checked]/aud:text-foreground group-has-[#aud-org:checked]/aud:shadow-sm group-has-[#aud-org:focus-visible]/aud:outline-2 group-has-[#aud-org:focus-visible]/aud:outline-primary group-has-[#aud-org:focus-visible]/aud:outline-offset-2"
            : "group-has-[#aud-gracz:checked]/aud:bg-bg-secondary group-has-[#aud-gracz:checked]/aud:text-foreground group-has-[#aud-gracz:checked]/aud:shadow-sm group-has-[#aud-gracz:focus-visible]/aud:outline-2 group-has-[#aud-gracz:focus-visible]/aud:outline-primary group-has-[#aud-gracz:focus-visible]/aud:outline-offset-2"
        }`
      ),
    ],
    [options.label]
  );
};

const audienceSwitch = (context: PageContext, h: H) =>
  h.div(
    [
      h.Class(
        "ld d1 mb-6 flex justify-end max-[30rem]:justify-center lg:float-right lg:mb-0 lg:ml-8"
      ),
    ],
    [
      h.div(
        [
          h.Class(
            "ld d0 inline-flex gap-[0.2rem] bg-bg-tertiary border border-border rounded-full p-[0.22rem]"
          ),
          h.Role("group"),
          h.AriaLabel(context.translator.t("Choose page view")),
        ],
        [
          switchLabel(
            {
              audience: "organizers",
              label: context.translator.t("For organizers"),
            },
            h
          ),
          switchLabel(
            { audience: "players", label: context.translator.t("For players") },
            h
          ),
        ]
      ),
    ]
  );

const heroHeading =
  "ld d2 text-[clamp(2rem,4.6vw,3.25rem)] font-extrabold tracking-[-0.03em] leading-[1.08] max-w-[52rem] text-balance";

const heroLead =
  "ld d3 mt-[1.4rem] text-[clamp(1.05rem,2vw,1.25rem)] text-foreground-secondary max-w-xl";

const organizerHero = (model: LandingModel, context: PageContext, h: H) => {
  const { translator } = context;

  return h.section(
    [
      h.Class(
        "pt-10 pb-[4.5rem] max-[30rem]:pt-6 group-has-[#aud-gracz:checked]/aud:hidden"
      ),
      h.AriaLabelledBy("landing-hero-heading"),
    ],
    [
      h.div(
        [h.Class("max-w-7xl mx-auto px-4 md:px-6 lg:px-8")],
        [
          audienceSwitch(context, h),
          h.h1(
            [h.Id("landing-hero-heading"), h.Class(heroHeading)],
            [
              translator.t("Event organization"),
              " ",
              h.span(
                [h.Class("strike-phrase relative inline-block")],
                [
                  translator.t("without spreadsheet chaos"),
                  h.svg(
                    [
                      h.ViewBox("0 0 300 24"),
                      h.PreserveAspectRatio("none"),
                      h.AriaHidden(true),
                    ],
                    [
                      h.path([
                        h.D("M6 14 C 80 18, 150 10, 224 14 S 288 12, 295 13"),
                        h.StrokeWidth("5"),
                        h.VectorEffect("non-scaling-stroke"),
                      ]),
                    ]
                  ),
                ]
              ),
            ]
          ),
          h.p(
            [h.Class(heroLead)],
            [
              translator.t(
                "Bring the event. We help set up proposals, programme, enrollment, and the public page in Zagrajmy."
              ),
            ]
          ),
          h.div(
            [
              h.Class(
                "ld d4 mt-[2.2rem] flex flex-wrap items-center gap-4 max-[26rem]:*:w-full"
              ),
            ],
            [
              h.a(
                [
                  h.Class("btn btn-primary"),
                  h.Href(
                    `mailto:${model.contactEmail}?subject=${encodeURIComponent(translator.t("My event in Zagrajmy"))}`
                  ),
                ],
                [
                  h.span(
                    [h.Class("hidden min-[30rem]:inline")],
                    [translator.t("Run your event with Zagrajmy")]
                  ),
                  h.span(
                    [h.Class("min-[30rem]:hidden")],
                    [translator.t("Run your event")]
                  ),
                ]
              ),
              h.a(
                [
                  h.Class("btn btn-secondary"),
                  h.Href(model.showcaseUrl),
                  h.Target("_blank"),
                  h.Rel("noopener"),
                ],
                [translator.t("See a real event's page")]
              ),
            ]
          ),
        ]
      ),
    ]
  );
};

const playerHero = (model: LandingModel, context: PageContext, h: H) => {
  const { translator } = context;

  return h.section(
    [
      h.Class(
        "hidden group-has-[#aud-gracz:checked]/aud:block pt-10 pb-[4.5rem] max-[30rem]:pt-6"
      ),
      h.AriaLabelledBy("g-hero-heading"),
    ],
    [
      h.div(
        [h.Class("max-w-7xl mx-auto px-4 md:px-6 lg:px-8")],
        [
          audienceSwitch(context, h),
          h.h1(
            [h.Id("g-hero-heading"), h.Class(heroHeading)],
            [
              translator.t("Your table, your game,"),
              " ",
              h.span(
                [h.Class("text-primary-hover dark:text-primary")],
                [translator.t("one link")]
              ),
              ".",
            ]
          ),
          h.p(
            [h.Class(heroLead)],
            [
              translator.t(
                'You run an Encounter, send friends the link, and they click "I\'m in". You see right away who is coming and how many seats are left.'
              ),
            ]
          ),
          h.div(
            [
              h.Class(
                "ld d4 mt-[2.2rem] flex flex-wrap items-center gap-4 max-[26rem]:*:w-full"
              ),
            ],
            model.encountersEnabled
              ? [
                  h.a(
                    [h.Class("btn btn-primary"), h.Href("/encounters/create/")],
                    [translator.t("Run an Encounter")]
                  ),
                ]
              : []
          ),
          h.p(
            [h.Class("ld d5 mt-[1.6rem] text-[0.95rem]")],
            [
              h.a(
                [
                  h.Class(
                    "text-foreground-muted font-medium underline underline-offset-[3px] decoration-border hover:text-foreground"
                  ),
                  h.Href(`#${playersConventionsHash}`),
                ],
                [translator.t("Browse events")]
              ),
            ]
          ),
        ]
      ),
    ]
  );
};

const conventions = (model: LandingModel, context: PageContext, h: H) => {
  const { translator } = context;

  return h.section(
    [
      h.Class("hidden group-has-[#aud-gracz:checked]/aud:block pt-12 pb-16"),
      h.AriaLabelledBy(playersConventionsHash),
    ],
    [
      h.div(
        [h.Class("max-w-7xl mx-auto px-4 md:px-6 lg:px-8")],
        [
          h.p(
            [
              h.Class(
                "reveal text-[0.78rem] font-bold tracking-[0.11em] uppercase text-foreground-muted mb-3"
              ),
            ],
            [translator.t("Conventions")]
          ),
          h.h2(
            [
              h.Id(playersConventionsHash),
              h.Class(
                "reveal text-[clamp(1.6rem,3.4vw,2.3rem)] font-extrabold tracking-[-0.02em] leading-[1.12] max-w-[24ch]"
              ),
            ],
            [translator.t("Enrollment and the programme in one place")]
          ),
          h.p(
            [
              h.Class(
                "reveal mt-4 text-[1.05rem] text-foreground-secondary max-w-[38rem]"
              ),
            ],
            [
              translator.t(
                "Zagrajmy runs the programme of real conventions: you browse the schedule, enroll in programme items, and see free seats live."
              ),
            ]
          ),
          h.div(
            [h.Class("reveal mt-6")],
            [
              h.div(
                [
                  h.Class(
                    "grid grid-cols-3 max-[52rem]:grid-cols-1 gap-4 max-w-[58rem]"
                  ),
                ],
                model.conventions.map((convention) =>
                  h.a(
                    [
                      h.Key(convention.domain),
                      h.Class(
                        "relative aspect-[2.7/1] overflow-hidden rounded-2xl border border-border bg-bg-secondary flex items-end p-4 no-underline"
                      ),
                      h.Href(
                        `https://${convention.domain}/event/${convention.eventSlug}/`
                      ),
                      h.Target("_blank"),
                      h.Rel("noopener"),
                    ],
                    [
                      h.img([
                        h.Class("absolute inset-0 w-full h-full object-cover"),
                        h.Src(convention.coverUrl),
                        h.Alt(""),
                        h.Width("800"),
                        h.Height("400"),
                        h.Loading("lazy"),
                      ]),
                      h.span(
                        [
                          h.Class(
                            "absolute inset-0 bg-gradient-to-t from-black/75 via-black/30 to-black/5"
                          ),
                          h.AriaHidden(true),
                        ],
                        []
                      ),
                      h.span(
                        [
                          h.Class(
                            "relative text-white font-bold text-[1.05rem] leading-tight"
                          ),
                        ],
                        [convention.name]
                      ),
                    ]
                  )
                )
              ),
            ]
          ),
        ]
      ),
    ]
  );
};

export const landingView = defineView<LandingModel, LandingMessage, PageInputs>(
  (model, inputs, h) => {
    const context = pageContextOf(inputs.shell);

    return h.div(
      [
        h.Class(
          cx(
            "landing group/aud leading-[1.55]",
            model.isChoreographyDone && "ld-done"
          )
        ),
      ],
      [
        h.input([
          h.Class("sr-only"),
          h.Type("radio"),
          h.Name("landing-aud"),
          h.Id("aud-org"),
          h.Checked(model.audience === "organizers"),
          h.OnChange(() =>
            LandingMessage.ChangedAudience({ audience: "organizers" })
          ),
        ]),
        h.input([
          h.Class("sr-only"),
          h.Type("radio"),
          h.Name("landing-aud"),
          h.Id("aud-gracz"),
          h.Checked(model.audience === "players"),
          h.OnChange(() =>
            LandingMessage.ChangedAudience({ audience: "players" })
          ),
        ]),
        organizerHero(model, context, h),
        playerHero(model, context, h),
        conventions(model, context, h),
      ]
    );
  }
);
