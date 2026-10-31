import { Option } from "effect";

import type {
  EventPageFlags,
  SessionView,
} from "../src/client/event-page/flags.js";

const startsAt = Date.parse("2031-05-02T09:00:00Z");

const HOUR = 3_600_000;

export const sessionView = (
  overrides: Partial<SessionView> & Pick<SessionView, "id" | "title">
): SessionView => ({
  availability: "available",
  bookmarkCount: 0,
  categoryName: "",
  coverUrl: "",
  crumbs: [
    { name: "Hall", spaceFilter: "venue:1" },
    { name: "Room A", spaceFilter: "2" },
  ],
  description: "",
  descriptionHtml: "",
  durationLabel: "2h",
  effectiveLimit: 6,
  enrolledCount: 0,
  fieldAnswers: [],
  host: "Alex Morgan",
  isFull: false,
  locationLabel: "Hall > Room A",
  minAge: 0,
  overflowPills: [],
  participants: [],
  pills: [],
  presenter: { avatarUrl: Option.none(), name: "Alex Morgan" },
  roster: Option.some([]),
  seatsLabel: "6 seats",
  spaceId: "2",
  spaceName: "Room A",
  spaceOrder: "[]",
  spotsLeft: 6,
  spotsScarce: false,
  tagCategories: "",
  tags: "",
  takesEnrollment: true,
  timing: Option.some({
    day: "2031-05-02",
    dayLabel: "Friday, 2 May",
    endClock: "13:00",
    endIso: "2031-05-02T13:00:00+02:00",
    endsAt: startsAt + 2 * HOUR,
    hour: "11:00",
    sessionEndIso: "2031-05-02T13:00:00+02:00",
    startClock: "11:00",
    startIso: "2031-05-02T11:00:00+02:00",
    startsAt,
    when: "Friday, 2 May · 11:00–13:00",
  }),
  tracks: [],
  userBookmarked: false,
  userEnrolled: false,
  userWaiting: false,
  venueId: "1",
  venueName: "Hall",
  waitingCount: 0,
  ...overrides,
});

export const strategyLab = sessionView({ id: 1, title: "Strategy Lab" });

export const dropIn = sessionView({
  effectiveLimit: 0,
  host: "Priya Chen",
  id: 2,
  presenter: { avatarUrl: Option.none(), name: "Priya Chen" },
  takesEnrollment: false,
  title: "Story Circle",
});

export const eventPageFlags = (
  overrides: Partial<EventPageFlags> = {}
): EventPageFlags => ({
  choices: {
    categories: [],
    days: [],
    hosts: ["Alex Morgan", "Priya Chen"],
    hours: [],
    minAges: [],
    minAgesDistinct: 1,
    spaces: [],
    tagFields: [],
    tracks: [],
  },
  enrolledSessions: [],
  enrollmentNotices: [],
  hasEnrollableSessions: true,
  hero: {
    addressLines: [],
    addressQuery: "",
    coverUrl: "",
    dates: {
      endIso: "2031-05-02T18:00:00+02:00",
      endShort: "Fri May 2",
      endTime: "18:00",
      isSameDay: true,
      startDay: "Friday, 2 May",
      startIso: "2031-05-02T10:00:00+02:00",
      startShort: "Fri May 2",
      startTime: "10:00",
    },
    descriptionHtml: "",
    googleCalendarUrl: "https://calendar.google.com/calendar/render",
    icsUrl: "/event/spring-meet/calendar.ics",
    isEnded: false,
    isLive: false,
    isProposalActive: false,
    isUnlisted: false,
    mapsUrl: "",
    name: "Spring Meet",
    printUrl: "/event/spring-meet/print/",
    proposeUrl: "/event/spring-meet/propose/",
    scheduledCount: 2,
    slug: "spring-meet",
    statusPills: [],
  },
  layout: {
    _tag: "Cards",
    days: [
      {
        day: {
          date: "2031-05-02",
          dateLabel: "2 May",
          name: "Friday",
          panelId: "schedule-day-2031-05-02",
          shortName: "Fri",
        },
        slots: [
          {
            dateLabel: "Friday, 2 May –",
            hour: "11:00",
            sessionIds: [1, 2],
            startsAt,
          },
        ],
      },
    ],
    slotCount: 1,
  },
  linkPreview: { description: "", title: "" },
  locale: "en",
  loginUrl: "/crowd/auth0/do/login",
  now: startsAt - 24 * HOUR,
  ownProposals: [],
  query: "",
  sessions: [strategyLab, dropIn],
  signedIn: false,
  view: "list",
  ...overrides,
});
