import type { EnrollmentNotice, MessageItem } from "./api.js";
import { SKIP_REASON_MSGIDS } from "./enroll.js";
import type { EnrollmentBatch } from "./enroll.js";
import type { NotEnoughSpotsError } from "./errors.js";

const NAME_ONLY = "%(name)s";

const named = (name: string): MessageItem => ({ msgid: NAME_ONLY, name });

const listed = (
  level: EnrollmentNotice["level"],
  msgid: string,
  items: readonly MessageItem[]
): readonly EnrollmentNotice[] =>
  items.length === 0 ? [] : [{ args: [], items, level, msgid, vars: {} }];

export const batchNotices = (
  batch: EnrollmentBatch
): readonly EnrollmentNotice[] => [
  ...listed("success", "Enrolled: {}", batch.confirmedUsers.map(named)),
  ...listed(
    "success",
    "Added to waiting list: {}",
    batch.waitingUsers.map(named)
  ),
  ...listed(
    "success",
    "Seat held (awaiting their approval): {}",
    batch.heldSeats.map((held) => named(held.name))
  ),
  ...listed("success", "Cancelled: {}", batch.cancelledUsers.map(named)),
  ...listed(
    "warning",
    "Skipped (already enrolled or conflicts): {}",
    batch.skippedUsers.map((skipped) => ({
      msgid: SKIP_REASON_MSGIDS[skipped.reason],
      name: skipped.name,
    }))
  ),
  ...(batch.guestTotal === null
    ? []
    : [
        {
          args: [String(batch.guestTotal)],
          items: [],
          level: "success" as const,
          msgid: "Guests you bring: {}",
          vars: {},
        },
      ]),
];

export const overflowNotice = (
  error: NotEnoughSpotsError
): EnrollmentNotice => ({
  args: [String(error.requested), String(error.available)],
  items: [],
  level: "error",
  msgid: error.blameGuests
    ? "Not enough spots available. {} spots requested, {} available. Bring fewer guests or use the waiting list for account holders."
    : "Not enough spots available. {} spots requested, {} available. Please use waiting list for some users.",
  vars: {},
});
