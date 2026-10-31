import type { EnrollFooter } from "@zagrajmy/core/contracts";
import { Predicate } from "effect";
import { Command } from "foldkit";
import type { Update } from "foldkit";

import {
  EnrollmentActions,
  EnrollmentSlotMessage,
} from "../enrollment-slot.js";
import { EventPageMessage } from "../message.js";
import type { EventPageModel } from "../model.js";
import {
  ReadEnrollFooter,
  SubmitFooterChoice,
  ToggleBookmark,
} from "./command.js";
import type { FooterSeats, FooterState } from "./model.js";

type Return = Update.Return<EventPageModel, EventPageMessage>;

const lift = (message: EnrollmentSlotMessage) =>
  EventPageMessage.GotEnrollmentMessage({ message });

export const enrollmentCommands = (
  model: EventPageModel,
  sessionId: number
): Update.Commands<EventPageMessage> =>
  model.signedIn
    ? [Command.mapMessage(ReadEnrollFooter({ sessionId }), lift)]
    : [];

const seatState = (
  model: EventPageModel,
  sessionId: number
): FooterState | null =>
  Predicate.isTagged(model.enrollment, "Seat") &&
  model.enrollment.state.sessionId === sessionId
    ? model.enrollment.state
    : null;

const withState = (
  model: EventPageModel,
  state: FooterState
): EventPageModel => ({
  ...model,
  enrollment: EnrollmentActions.Seat({ state }),
});

const holds = (footer: EnrollFooter, label: string) =>
  footer.actions?.badge?.label === label;

const withSeats = (options: {
  readonly model: EventPageModel;
  readonly sessionId: number;
  readonly seats: FooterSeats;
  readonly footer: EnrollFooter;
}): EventPageModel => ({
  ...options.model,
  sessions: options.model.sessions.map((session) =>
    session.id === options.sessionId
      ? {
          ...session,
          enrolledCount: options.seats.enrolledCount,
          isFull: options.seats.isFull,
          spotsLeft: options.seats.seatsLeft,
          userEnrolled: holds(options.footer, "You're enrolled"),
          userWaiting: holds(options.footer, "On the waiting list"),
          waitingCount: options.seats.waitingCount,
        }
      : session
  ),
});

const withBookmark = (
  model: EventPageModel,
  mark: {
    readonly sessionId: number;
    readonly bookmarked: boolean;
    readonly count: number;
  }
): EventPageModel => ({
  ...model,
  sessions: model.sessions.map((session) =>
    session.id === mark.sessionId
      ? {
          ...session,
          bookmarkCount: mark.count,
          userBookmarked: mark.bookmarked,
        }
      : session
  ),
});

export const updateEnrollmentFooter = (
  model: EventPageModel,
  message: EnrollmentSlotMessage
): Return =>
  EnrollmentSlotMessage.match<Return>(message, {
    ClickedBookmark: (event) => {
      const session = model.sessions.find(
        (candidate) => candidate.id === event.sessionId
      );

      if (session === undefined) {
        return { model };
      }

      return {
        commands: [
          Command.mapMessage(
            ToggleBookmark({
              bookmarked: session.userBookmarked,
              count: session.bookmarkCount,
              sessionId: session.id,
            }),
            lift
          ),
        ],
        model: withBookmark(model, {
          bookmarked: !session.userBookmarked,
          count: Math.max(
            0,
            session.bookmarkCount + (session.userBookmarked ? -1 : 1)
          ),
          sessionId: session.id,
        }),
      };
    },

    ClickedEnrollmentAction: () => ({ model }),

    ClickedFooterChoice: (event) => {
      const state = seatState(model, event.sessionId);
      const actions = state?.footer.actions ?? null;

      if (state === null || actions === null || state.busy) {
        return { model };
      }

      return {
        commands: [
          Command.mapMessage(
            SubmitFooterChoice({
              confirm: actions.confirm,
              locale: model.locale,
              sessionId: state.sessionId,
              value: actions.submitValue,
              viewerId: state.viewerId,
            }),
            lift
          ),
        ],
        model: withState(model, { ...state, busy: true, error: "" }),
      };
    },

    FailedReadEnrollFooter: (event) =>
      Predicate.isTagged(model.enrollment, "Loading") &&
      model.enrollment.sessionId === event.sessionId
        ? { model: { ...model, enrollment: EnrollmentActions.NotAvailable() } }
        : { model },

    FailedSubmitEnrollments: (event) => {
      const state = seatState(model, event.sessionId);

      return state === null
        ? { model }
        : {
            model: withState(model, {
              ...state,
              busy: false,
              error: event.error,
              footer: event.footer ?? state.footer,
              notice: "",
            }),
          };
    },

    FailedToggleBookmark: (event) => ({ model: withBookmark(model, event) }),

    GotEnrollFooter: (event) => {
      const waiting =
        Predicate.isTagged(model.enrollment, "Loading") &&
        model.enrollment.sessionId === event.sessionId;

      return waiting
        ? {
            model: withState(model, {
              busy: false,
              error: "",
              eventSlug: event.eventSlug,
              footer: event.footer,
              notice: "",
              sessionId: event.sessionId,
              viewerId: event.viewerId,
            }),
          }
        : { model };
    },

    KeptSeat: (event) => {
      const state = seatState(model, event.sessionId);

      return state === null
        ? { model }
        : { model: withState(model, { ...state, busy: false }) };
    },

    SucceededSubmitEnrollments: (event) => {
      const state = seatState(model, event.sessionId);

      if (state === null) {
        return { model };
      }

      return {
        model: withSeats({
          footer: event.footer,
          model: withState(model, {
            ...state,
            busy: false,
            error: "",
            footer: event.footer,
            notice: event.footer.actions === null ? event.notice : "",
          }),
          seats: event.seats,
          sessionId: event.sessionId,
        }),
      };
    },

    SucceededToggleBookmark: (event) => ({ model: withBookmark(model, event) }),
  });
