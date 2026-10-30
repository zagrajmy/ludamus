import type { EventSummary } from "@zagrajmy/core";
import type { HtmlBuilder } from "foldkit/html";

export const eventsFeed = <Message>(
  events: ReadonlyArray<EventSummary>,
  h: HtmlBuilder<Message>
) =>
  h.section(
    [h.AriaLabelledBy("events-heading")],
    [
      h.h1([h.Id("events-heading"), h.Class("mb-6 text-3xl font-bold")], ["Events"]),
      events.length === 0
        ? h.p([h.Class("text-slate-600")], ["No upcoming events."])
        : h.ul(
            [h.Class("grid gap-4 sm:grid-cols-2")],
            events.map((event) =>
              h.li(
                [h.Key(event.slug), h.Class("rounded-xl border border-slate-200 bg-white p-4")],
                [
                  h.article(
                    [],
                    [
                      h.h2(
                        [h.Class("text-xl font-semibold")],
                        [h.a([h.Href(`/event/${event.slug}/`)], [event.name])]
                      ),
                      h.p(
                        [h.Class("text-sm text-slate-600")],
                        [
                          h.time([h.Datetime(event.startTime)], [event.startTime]),
                          " – ",
                          h.time([h.Datetime(event.endTime)], [event.endTime]),
                        ]
                      ),
                    ]
                  ),
                ]
              )
            )
          ),
    ]
  );
