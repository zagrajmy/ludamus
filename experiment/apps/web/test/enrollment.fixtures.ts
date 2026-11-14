import type { EnrollFooter } from "@zagrajmy/core/contracts";

import type { FooterSeats } from "../src/client/event-page/enrollment/model.js";

export const enrollFooter: EnrollFooter = {
  actions: {
    badge: null,
    confirm: "",
    groupLabel: "Enroll with others…",
    submitIcon: "user-plus",
    submitLabel: "Enroll",
    submitValue: "enroll",
  },
  opensAt: null,
};

export const enrolledFooter: EnrollFooter = {
  actions: {
    badge: { icon: "check-circle", label: "You're enrolled", tone: "success" },
    confirm: "",
    groupLabel: "Enroll with others…",
    submitIcon: "x-mark",
    submitLabel: "Cancel",
    submitValue: "cancel",
  },
  opensAt: null,
};

export const shutFooter: EnrollFooter = { actions: null, opensAt: null };

export const seats = (overrides: Partial<FooterSeats>): FooterSeats => ({
  enrolledCount: 0,
  isFull: false,
  seatsLeft: 6,
  waitingCount: 0,
  ...overrides,
});
