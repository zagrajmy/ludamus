import { Schema } from "effect";

import { EnrollPageFlags } from "./flags.js";
import type { EnrollPageFlags as Flags } from "./flags.js";

export const EnrollPageModel = Schema.Struct({
  ...EnrollPageFlags.fields,
  guests: Schema.String,
  included: Schema.Array(Schema.Int),
  submitting: Schema.Boolean,
});

export type EnrollPageModel = typeof EnrollPageModel.Type;

export const initEnrollPage = (flags: Flags): EnrollPageModel => ({
  ...flags,
  guests: flags.form.guests === null ? "" : String(flags.form.guests.count),
  included: flags.form.rows
    .filter((row) => row.boxChecked)
    .map((row) => row.userId),
  submitting: false,
});

export type SeatHint = "leave" | "seat" | "wait" | null;

export interface EnrollPreview {
  readonly hints: ReadonlyMap<number, SeatHint>;
  readonly seated: number;
  readonly waiting: number;
  readonly ctaLabel: string;
}

const CTA_FOR: Readonly<Record<Exclude<SeatHint, null>, string>> = {
  leave: "Confirm",
  seat: "Join this session",
  wait: "Join the waiting list",
};

export const enrollPreview = (model: EnrollPageModel): EnrollPreview => {
  const { rows } = model.form;
  const isIn = (userId: number) => model.included.includes(userId);

  let free =
    model.form.seats.seatsLeft +
    rows.filter((row) => !isIn(row.userId) && row.occupiesSeat).length;

  let seated = 0;
  let waiting = 0;
  let viewerJoins: SeatHint = null;
  const hints = new Map<number, SeatHint>();

  for (const [index, row] of rows.entries()) {
    const included = isIn(row.userId);

    if (included && !row.checked) {
      const takesSeat = free > 0;

      if (takesSeat) {
        free -= 1;
        seated += 1;
      } else {
        waiting += 1;
      }

      hints.set(row.userId, takesSeat ? "seat" : "wait");

      if (index === 0 && !row.disabled) {
        viewerJoins = takesSeat ? "seat" : "wait";
      }
    } else {
      hints.set(row.userId, !included && row.checked ? "leave" : null);
    }
  }

  const initialGuests = model.form.guests?.count ?? 0;

  const addedGuests =
    Number(model.guests === "" ? 0 : model.guests) - initialGuests;

  if (Number.isFinite(addedGuests) && addedGuests > 0) {
    seated += addedGuests;
  }

  return {
    ctaLabel: viewerJoins === null ? "Confirm" : CTA_FOR[viewerJoins],
    hints,
    seated,
    waiting,
  };
};
