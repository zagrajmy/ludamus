import type { Html, HtmlBuilder } from "foldkit/html";

import type { AboutFlags } from "../../client/about/flags.js";
import type { Child } from "../../ui/html.js";
import type { Translator } from "../../ui/i18n.js";
import { linkedText } from "../../ui/rich-text.js";
import type { PageContext } from "../page-context.js";
import type { PageTitle } from "../shell/title.js";

export const aboutTitle = (context: PageContext): PageTitle => ({
  name: context.translator.t("About Zagrajmy"),
  sphereSuffix: false,
});

const lead =
  "Zagrajmy is an event programme platform that runs proposals, the schedule, enrollment, and print for organizers of conventions, conferences, and meetups.";

export const aboutDescription = (translator: Translator) => translator.t(lead);

type Topic = readonly [heading: string, body: string];

const linkList = <Message>(
  links: ReadonlyArray<readonly [string, string]>,
  h: HtmlBuilder<Message>
) =>
  h.ul(
    [h.Class("flex flex-wrap gap-x-4 list-none ps-0 [&>li]:my-0 [&>li]:ps-0")],
    links.map(([href, label]) =>
      h.li([h.Key(href)], [h.a([h.Href(href)], [label])])
    )
  );

export const aboutView = <Message>(
  flags: AboutFlags,
  context: PageContext,
  h: HtmlBuilder<Message>
) => {
  const { t, tc } = context.translator;
  const topics = (items: ReadonlyArray<Topic>) =>
    items.flatMap(([heading, body]) => [h.h3([], [heading]), h.p([], [body])]);
  const section = (
    id: string,
    heading: string,
    children: ReadonlyArray<Child>
  ) =>
    h.section(
      [h.AriaLabelledBy(id)],
      [h.h2([h.Id(id)], [heading]), ...children]
    );
  const fact = (term: string, definition: ReadonlyArray<Child>) =>
    h.div([h.Key(term)], [h.dt([], [term]), h.dd([], definition)]);
  const factContext = "about key facts";

  return h.article(
    [
      h.Class(
        "prose dark:prose-invert max-w-3xl mx-auto w-full pt-4 prose-headings:text-foreground prose-headings:tracking-tight prose-h1:font-extrabold prose-h2:font-extrabold prose-lead:text-foreground prose-p:text-foreground-secondary prose-li:text-foreground-secondary prose-a:text-primary prose-a:decoration-primary/40 prose-a:hover:decoration-primary"
      ),
    ],
    [
      h.header(
        [],
        [
          h.h1([], [t("About Zagrajmy")]),
          h.p([h.Class("lead")], [t(lead)]),
          h.p(
            [],
            [
              t(
                "Bring the event. We help set up proposals, programme, enrollment, and the public page in Zagrajmy."
              ),
            ]
          ),
        ]
      ),
      section("about-does", t("What Zagrajmy does"), [
        ...topics([
          [
            t("Programme proposals and review"),
            t(
              "Programme creators send proposals through a form with your own questions. Every proposal lands in one inbox, where your team accepts it, puts it on hold, or rejects it."
            ),
          ],
          [
            t("Scheduling"),
            t(
              "You build the grid from tracks, rooms, and time slots. Two programme items in one room at the same time? Zagrajmy highlights the conflict before attendees see it."
            ),
          ],
          [
            t("The event page"),
            t(
              "Attendees get one address with the current programme, descriptions, and free seats. A change made in the organizer panel shows up on the page right away."
            ),
          ],
          [
            t("Enrollment and waiting lists"),
            t(
              "You set seat limits, and Zagrajmy runs enrollment and the waiting list. When a seat frees up, the next person in line gets it without anyone rewriting a list by hand."
            ),
          ],
          [
            tc("landing walkthrough step", "Print"),
            t(
              "The full schedule, day plans, and door cards for every room print straight from the browser. A programme change means a fresh printout instead of an evening of rebuilding files."
            ),
          ],
          [
            t("Encounters"),
            t(
              "Players post a game night, send friends one link, and see who's coming and how many seats are left. It takes less time than setting up the board."
            ),
          ],
        ]),
      ]),
      section("about-different", t("What makes Zagrajmy different"), [
        ...topics([
          [
            t("We set up your event with you"),
            t(
              "Before you ever see an empty form, we get on a call about how your event works. Then we set up the first version of proposals, rooms, and time slots with you."
            ),
          ],
          [
            t("Groups stay together on the waiting list"),
            t(
              "Friends who enroll as a group wait as a group. When enough seats free up, they get them together, and nobody further down the list jumps ahead. Tools that count seats one at a time would split them up the moment one seat opened."
            ),
          ],
          [
            t("Your spreadsheet is a starting point"),
            t(
              "If your programme already lives in Google Sheets or Google Forms, we import it instead of making you retype it. A finished programme can also be exported to Konwencik."
            ),
          ],
        ]),
        h.h3([], [t("Open source, so you can always leave")]),
        h.p(
          [],
          linkedText(
            t(
              'All of Zagrajmy\'s code is <a href="%(source_url)s">public on GitHub</a> under the AGPL-3.0 license. Your programme is never locked in a closed service: you can take it and run Zagrajmy yourself.',
              { source_url: "https://github.com/zagrajmy/ludamus" }
            ),
            h
          )
        ),
        ...topics([
          [
            t("Free for attendees and small meetups"),
            t(
              "Attendees never pay Zagrajmy to enroll, and small meetups and Encounters cost nothing. For conventions and conferences we send a written proposal first, and you decide from there."
            ),
          ],
        ]),
      ]),
      section("about-who", t("Who uses Zagrajmy"), [
        h.ul(
          [],
          [
            t(
              "Organizers of fan conventions (board games, RPGs, fantasy) with a multi-day programme across many rooms"
            ),
            t(
              "Conference organizers who collect talk proposals and build a room grid"
            ),
            t(
              "Organizers of meetups and clubs who need an event page with seat limits"
            ),
            t(
              "Programme creators and game masters who submit programme items to an event"
            ),
            t("Attendees who enroll in programme items, alone or with friends"),
            t("Players who invite others to a game night with an Encounter"),
          ].map((item) => h.li([], [item]))
        ),
      ]),
      section("about-team", t("The team behind Zagrajmy"), [
        h.p(
          [],
          [
            t(
              "We're Radek and Piotrek. Radek is the one with the guitar, and Piotrek is the one with the tattoos. We both play tabletop roleplaying games and write our own, and Zagrajmy (Polish for “let's play”) is the tool we wanted on both sides of the convention table."
            ),
          ]
        ),
        h.p(
          [],
          [
            t(
              "We first tried to build it in 2020, then other things took over. In June 2025 we picked it back up, starting with enrollment for tabletop game conventions, where the programme still lived in spreadsheets and chat threads. By now it covers everything from the first proposal to the printout on the room door."
            ),
          ]
        ),
        h.p(
          [],
          [
            t(
              "It's still the two of us, plus people who send fixes on GitHub. Write to us, and one of us writes back."
            ),
          ]
        ),
        h.h3([], ["Radosław Ganczarek"]),
        h.p(
          [],
          linkedText(
            t(
              'Radek has been running tabletop RPGs and building software in Python for more than 20 years. In his spare time, he designs small roleplaying games <a href="%(moose_url)s">about Moose</a> and <a href="%(island_url)s">Islands</a>, and sings <a href="%(songs_url)s">nerdy songs on YouTube</a>.',
              {
                island_url: "https://radekmg.itch.io/island-of-secrets",
                moose_url: "https://radekmg.itch.io/nienazwana-gra-o-losiu",
                songs_url: "https://www.youtube.com/@radekmgyt",
              }
            ),
            h
          )
        ),
        h.p(
          [],
          linkedText(
            t(
              'As seen on his <a href="%(talk_url)s">EuroPython 2019</a> talk on code quality, he keeps the system from becoming a ball of unmaintainable mess.',
              {
                talk_url:
                  "https://ep2019.europython.eu/conference/talks/TPR8sfu-code-quality-in-python.html",
              }
            ),
            h
          )
        ),
        linkList(
          [
            ["https://www.youtube.com/@radekmgyt", "YouTube"],
            ["https://radekmg.itch.io/", "itch.io"],
            ["https://fancysnake.dev/", "fancysnake.dev"],
            ["https://github.com/fancysnake", "GitHub"],
            ["https://www.linkedin.com/in/radoslawganczarek/", "LinkedIn"],
          ],
          h
        ),
        h.h3([], ["Piotr Monwid-Olechnowicz"]),
        h.p(
          [],
          [
            t(
              "Every story needs a villain, and Piotrek oscillates between asking “Why are we torturing the users?”, “Can we streamline this?”, “Shall we rewrite in Bend?” and shipping large PRs straight to prod during a convention."
            ),
          ]
        ),
        h.p(
          [],
          linkedText(
            t(
              'Piotrek also wrote his own games, but he only released one: <a href="%(game_url)s">Why Would You Fight a Dragon?</a> It\'s about violence, change, and sacrifice, like most of his contributions to the system.',
              { game_url: "https://hasparus.itch.io/why-dragon" }
            ),
            h
          )
        ),
        linkList(
          [
            ["https://haspar.us/", "haspar.us"],
            ["https://lol.haspar.us/", "lol.haspar.us"],
            ["https://hasparus.itch.io/", "itch.io"],
            ["https://bsky.app/profile/haspar.us", "Bluesky"],
            ["https://github.com/hasparus", "GitHub"],
          ],
          h
        ),
      ]),
      section("about-how", t("How Zagrajmy works"), [
        h.p([], [t("You talk directly to us, the people who write the code.")]),
        h.ol(
          [],
          [
            t("We reply and set up a short call about how your event works."),
            t(
              "We set up the first version: proposals, rooms, time slots, the page."
            ),
            t(
              "You click through it with us and we publish when you decide it is ready."
            ),
          ].map((item) => h.li([], [item]))
        ),
        h.p(
          [],
          [
            t(
              "After that, the event is yours to run from the organizer panel, at its own address on zagrajmy.net."
            ),
          ]
        ),
        h.div(
          [h.Class("not-prose mt-6")],
          [
            h.div(
              [h.Class("flex flex-wrap items-stretch gap-3")],
              [
                h.a(
                  [
                    h.Class("btn btn-primary max-sm:grow max-sm:min-h-12"),
                    h.Href(
                      `mailto:${flags.contactEmail}?subject=${encodeURIComponent(t("My event in Zagrajmy"))}`
                    ),
                  ],
                  [
                    h.span(
                      [h.Class("max-sm:hidden")],
                      [t("Run your event with Zagrajmy")]
                    ),
                    h.span([h.Class("sm:hidden")], [t("Run your event")]),
                  ]
                ),
                h.code(
                  [h.Class("self-center text-[0.9375rem]")],
                  [flags.contactEmail]
                ),
              ]
            ),
          ]
        ),
      ]),
      section("about-facts", t("Key facts"), [
        h.dl(
          [
            h.Class(
              "not-prose text-foreground-secondary [&_a]:text-primary [&_a]:underline [&_a]:decoration-primary/40 border-t border-border [&>div]:grid [&>div]:grid-cols-[minmax(0,11rem)_minmax(0,1fr)] max-sm:[&>div]:grid-cols-1 [&>div]:gap-x-6 [&>div]:gap-y-0.5 [&>div]:py-3 [&>div]:border-b [&>div]:border-border [&_dt]:font-semibold [&_dt]:text-foreground"
            ),
          ],
          [
            fact(tc(factContext, "Name"), ["Zagrajmy"]),
            fact(tc(factContext, "Type"), [
              t(
                "Open-source event programme platform, set up together with organizers"
              ),
            ]),
            fact(tc(factContext, "Founded"), [t("2020; relaunched in 2025")]),
            fact(tc(factContext, "Founders"), [
              "Radosław Ganczarek, Piotr Monwid-Olechnowicz",
            ]),
            fact(tc(factContext, "Headquarters"), [t("Wrocław, Poland")]),
            fact(tc(factContext, "Website"), [
              h.a([h.Href("https://zagrajmy.net/")], ["zagrajmy.net"]),
            ]),
            fact(tc(factContext, "Core offering"), [
              t(
                "Running an event's programme: proposals, review, the schedule, the event page, enrollment with waiting lists, and print"
              ),
            ]),
            fact(tc(factContext, "Pricing"), [
              t(
                "Free for attendees, small meetups, and Encounters; conventions and conferences get a written proposal matched to the event's scale"
              ),
            ]),
            fact(tc(factContext, "Contract terms"), [
              t("Agreed per event, in writing, before you commit to anything"),
            ]),
            fact(tc(factContext, "Services"), [
              t(
                "Event setup, import from Google Sheets and Google Forms, proposal forms, scheduling, event pages, enrollment and waiting lists, print materials, export to Konwencik"
              ),
            ]),
            fact(
              tc(factContext, "Communication"),
              linkedText(
                t(
                  'Email at <a href="mailto:%(email)s">%(email)s</a> and a call during setup',
                  {
                    email: flags.contactEmail,
                  }
                ),
                h
              )
            ),
            fact(tc(factContext, "Languages"), [t("Polish, English")]),
            flags.conventions.length === 0
              ? h.empty
              : fact(
                  tc(factContext, "Notable clients"),
                  flags.conventions.flatMap((convention, index) => [
                    h.a(
                      [h.Href(`https://${convention.domain}/`)],
                      [convention.name]
                    ),
                    index < flags.conventions.length - 1 ? ", " : "",
                  ])
                ),
            fact(tc(factContext, "Events in Zagrajmy"), [
              String(flags.eventCount),
            ]),
            fact(tc(factContext, "Programme items"), [
              String(flags.sessionCount),
            ]),
            fact(tc(factContext, "Alternatives"), [
              t("Spreadsheets with Google Forms, Sessionize, pretalx"),
            ]),
            fact(tc(factContext, "License"), [
              h.a(
                [
                  h.Href(
                    "https://github.com/zagrajmy/ludamus/blob/main/LICENSE"
                  ),
                ],
                ["AGPL-3.0"]
              ),
            ]),
            fact(tc(factContext, "Social"), [
              h.a([h.Href("https://github.com/zagrajmy")], ["GitHub"]),
            ]),
          ]
        ),
      ]),
      section("about-faq", t("Frequently asked questions"), [
        ...topics([
          [
            t("Is Zagrajmy only for board games and RPGs?"),
            t(
              "No. It grew out of tabletop game conventions, but talks, workshops, and panels fit the same programme. Rooms, tracks, time slots, and seat limits work the same way for any kind of programme item."
            ),
          ],
          [
            t("Can I set up an event on my own?"),
            t(
              "Not a convention or conference, not yet: we set those up with you, so the first version fits how your event works. A game night, yes: post it as an Encounter, right away and for free."
            ),
          ],
          [
            t("How much does it cost?"),
            t(
              "Small meetups — free. For conventions and conferences we agree on terms matched to the scale of the event; before you decide anything, you get a concrete written proposal."
            ),
          ],
          [
            t("Do I have to retype everything from spreadsheets?"),
            t(
              "Zagrajmy can collect session proposals, but it can also import your existing data from Google Sheets. You come in with what you already have instead of starting from an empty table."
            ),
          ],
          [
            t("Do attendees need an account?"),
            t(
              "Not to browse the programme. To enroll, usually yes: signing in takes a minute, and a nickname is enough as a name. Organizers can also let attendees enroll without an account."
            ),
          ],
          [
            t("Can I run Zagrajmy on my own server?"),
            t(
              "Yes. The code is public on GitHub under the AGPL-3.0 license, so you can run your own copy. If you change it and offer it to others, the license asks you to share those changes too."
            ),
          ],
        ]),
      ]),
    ]
  );
};
