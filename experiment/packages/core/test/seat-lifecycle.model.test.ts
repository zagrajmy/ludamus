import { describe, expect, it } from "@effect/vitest";
import { DateTime, Duration, Predicate, Result, Schema } from "effect";
import * as Arbitrary from "effect/Arbitrary";

import { processEnrollments } from "../src/enrollment/enroll.js";
import { decideClaim, decideDecline, decideExpiry, planFillFreedSeats, promotionEffects } from "../src/enrollment/promotion.js";
import { UNLIMITED_SLOTS } from "../src/enrollment/schemas.js";
import type { EnrollmentWrite } from "../src/enrollment/enroll.js";
import type { PromotionWrite } from "../src/enrollment/promotion.js";
import type { Offer } from "../src/enrollment/schemas.js";
import type { ParticipationStatus } from "../src/participation.js";
import type { PromotionMode } from "../src/proposal-category.js";
import { BASE, between } from "./support/arbitraries.js";
import { Model } from "./support/waiting-list-model.js";
import type { View } from "./support/waiting-list-model.js";

const CLAIM_WINDOW = Duration.minutes(60);

const START = DateTime.add(BASE, { days: 10 });

const WINDOW = {
  allowAnonymousEnrollment: false,
  maxWaitlistSessions: 10,
  percentageSlots: 100,
  restrictToConfiguredUsers: false,
};

const Command = Schema.Struct({
  kind: Schema.Literals([
    "enroll",
    "waitlist",
    "cancel",
    "claim",
    "decline",
    "lapse",
  ]),
  user: between(1, 3),
});

type Command = typeof Command.Type;

const Scenario = Schema.Struct({
  commands: Schema.Array(Command).check(
    Schema.isMinLength(8),
    Schema.isMaxLength(40)
  ),
  limit: between(1, 2),
  mode: Schema.Literals(["auto", "offer_claim"]),
});

interface Row {
  readonly participationId: number;
  readonly userId: number;
  status: ParticipationStatus;
  expiresAt: DateTime.Utc | null;
  token: string | null;
}

class Store {
  rows: Row[] = [];
  now = BASE;
  private nextId = 1;
  private nextToken = 1;

  private readonly limit: number;
  private readonly mode: PromotionMode;

  constructor(limit: number, mode: PromotionMode) {
    this.limit = limit;
    this.mode = mode;
  }

  row(user: number): Row | undefined {
    return this.rows.find((row) => row.userId === user);
  }

  occupied(): number {
    return this.rows.filter((row) => row.status !== "waiting").length;
  }

  view(): View {
    const users = (status: ParticipationStatus): readonly number[] =>
      this.rows.filter((row) => row.status === status).map((row) => row.userId);

    return {
      offered: users("offered").toSorted((a, b) => a - b),
      queue: users("waiting"),
      seated: users("confirmed").toSorted((a, b) => a - b),
    };
  }

  submit(user: number, choice: "enroll" | "waitlist" | "cancel"): void {
    const outcome = processEnrollments({
      guestsTarget: null,
      partyId: null,
      requests: [
        {
          choice,
          isPartyMember: false,
          name: `u${user}`,
          needsAccept: false,
          userId: user,
        },
      ],
      session: {
        conflictedUserIds: [],
        eligibleWindows: [WINDOW],
        enrolledCount: this.occupied(),
        guestParticipationIds: [],
        participantsLimit: this.limit,
        participations: this.rows.map((row) => ({
          status: row.status,
          userId: row.userId,
        })),
        presenterId: null,
        shadowbannedUserIds: [],
        viewerIsConfigured: true,
      },
    });

    if (Result.isFailure(outcome)) {
      return;
    }

    for (const write of outcome.success.writes) {
      this.applyEnrollment(write);
    }

    if (outcome.success.freedSeat) {
      this.fill();
    }
  }

  private takeId(): number {
    const id = this.nextId;
    this.nextId += 1;

    return id;
  }

  private takeToken(): number {
    const token = this.nextToken;
    this.nextToken += 1;

    return token;
  }

  private applyEnrollment(write: EnrollmentWrite): void {
    if (Predicate.isTagged(write, "Delete")) {
      this.rows = this.rows.filter((row) => row.userId !== write.userId);
    } else if (Predicate.isTagged(write, "Save")) {
      const existing = this.row(write.userId);

      if (existing === undefined) {
        this.rows.push({
          expiresAt: null,
          participationId: this.takeId(),
          status: write.status,
          token: null,
          userId: write.userId,
        });
      } else {
        existing.status = write.status;
      }
    }
  }

  fill(): void {
    const waiting = this.rows.filter((row) => row.status === "waiting");

    const effects = promotionEffects({
      claimToken: () => `token-${this.takeToken()}`,
      plan: planFillFreedSeats({
        now: this.now,
        state: {
          availableSeats: Math.max(0, this.limit - this.occupied()),
          eventSlug: "ev",
          offerClaimWindow: CLAIM_WINDOW,
          presenterId: null,
          promotionMode: this.mode,
          sessionId: 1,
          sessionTitle: "S",
          shadowbannedUserIds: [],
          startTime: START,
          waiting: waiting.map((row) => ({
            creationTime: BASE,
            email: "",
            fullName: `u${row.userId}`,
            hasConflict: false,
            ownerSlotsRemaining: UNLIMITED_SLOTS,
            participationId: row.participationId,
            partyId: null,
            recipientUserId: row.userId,
            sponsorId: null,
            userId: row.userId,
          })),
        },
      }),
    });

    for (const write of effects.writes) {
      this.applyPromotion(write);
    }
  }

  private applyPromotion(write: PromotionWrite): void {
    for (const row of this.rows.filter((r) =>
      write.participationIds.includes(r.participationId)
    )) {
      if (Predicate.isTagged(write, "Confirm")) {
        row.status = "confirmed";
      } else {
        row.status = "offered";
        row.expiresAt = write.offerExpiresAt;
        row.token = write.claimToken;
      }
    }
  }

  private offerOf(row: Row): Offer | null {
    if (row.status !== "offered" || row.expiresAt === null) {
      return null;
    }

    return {
      eventSlug: "ev",
      offerExpiresAt: row.expiresAt,
      participantIds: this.rows
        .filter((r) => r.token === row.token)
        .map((r) => r.participationId),
      recipients: [row.userId],
      sessionId: 1,
      sessionTitle: "S",
    };
  }

  private drop(ids: readonly number[]): void {
    this.rows = this.rows.filter(
      (row) => !(ids.includes(row.participationId) && row.status === "offered")
    );
  }

  claim(row: Row): void {
    const decision = decideClaim({ now: this.now, offer: this.offerOf(row) });

    for (const claimed of this.rows) {
      if (
        decision.markClaimed?.participationIds.includes(
          claimed.participationId
        ) === true &&
        claimed.status === "offered"
      ) {
        claimed.status = "confirmed";
      }
    }
  }

  decline(row: Row): void {
    const decision = decideDecline(this.offerOf(row));
    this.drop(decision.drop);

    if (decision.refillSessionId !== null) {
      this.fill();
    }
  }

  lapse(): void {
    this.now = DateTime.addDuration(this.now, Duration.minutes(61));

    const lapsed = this.rows.filter(
      (row) =>
        row.expiresAt !== null &&
        row.status === "offered" &&
        DateTime.isLessThan(row.expiresAt, this.now)
    );

    for (const row of lapsed) {
      const expiry = decideExpiry({ now: this.now, offer: this.offerOf(row) });

      if (Predicate.isTagged(expiry, "Lapsed")) {
        this.drop(expiry.drop);
        this.fill();
      }
    }
  }
}

interface Turn {
  readonly store: Store;
  readonly model: Model;
  readonly user: number;
  readonly row: Row | undefined;
}

const STEPS: Readonly<Record<Command["kind"], (turn: Turn) => void>> = {
  cancel: ({ model, store, user }) => {
    if (!model.has(user)) {
      return;
    }

    const freed = !model.queue.includes(user);
    store.submit(user, "cancel");
    model.seated = model.seated.filter((u) => u !== user);
    model.offered = model.offered.filter((u) => u !== user);
    model.queue = model.queue.filter((u) => u !== user);

    if (freed) {
      model.refill();
    }
  },
  claim: ({ model, row, store, user }) => {
    if (row === undefined || !model.offered.includes(user)) {
      return;
    }

    store.claim(row);
    model.offered = model.offered.filter((u) => u !== user);
    model.seated.push(user);
  },
  decline: ({ model, row, store, user }) => {
    if (row === undefined || !model.offered.includes(user)) {
      return;
    }

    store.decline(row);
    model.offered = model.offered.filter((u) => u !== user);
    model.refill();
  },
  enroll: ({ model, store, user }) => {
    if (model.has(user)) {
      return;
    }

    store.submit(user, "enroll");

    if (!model.full()) {
      model.seated.push(user);
    }
  },
  lapse: ({ model, store }) => {
    store.lapse();
    const lapsed = model.offered.length;
    model.offered = [];

    for (let index = 0; index < lapsed; index += 1) {
      model.refill();
    }
  },
  waitlist: ({ model, store, user }) => {
    if (model.has(user) || !model.full()) {
      return;
    }

    store.submit(user, "waitlist");
    model.queue.push(user);
  },
};

const step = (store: Store, model: Model, command: Command): void => {
  const { user } = command;

  STEPS[command.kind]({ model, row: store.row(user), store, user });
};

describe("seat lifecycle: enroll, wait, offer, claim, decline, lapse, cancel", () => {
  it.prop(
    "the decision functions move seats exactly as the waiting-list model does",
    { scenario: Arbitrary.schema(Scenario) },
    ({ scenario }) => {
      const store = new Store(scenario.limit, scenario.mode);
      const model = new Model(scenario.limit, scenario.mode);

      for (const command of scenario.commands) {
        step(store, model, command);
        expect(store.view()).toEqual(model.view());
        expect(store.occupied()).toBeLessThanOrEqual(scenario.limit);
      }
    },
    { arbitrary: { runs: 5000, size: 40 } }
  );

  it("an offer declined passes to the next in line", () => {
    const store = new Store(1, "offer_claim");
    const model = new Model(1, "offer_claim");

    const commands: readonly Command[] = [
      { kind: "enroll", user: 1 },
      { kind: "waitlist", user: 2 },
      { kind: "waitlist", user: 3 },
      { kind: "cancel", user: 1 },
      { kind: "decline", user: 2 },
      { kind: "claim", user: 3 },
    ];

    for (const command of commands) {
      step(store, model, command);
    }

    expect(store.view()).toEqual({ offered: [], queue: [], seated: [3] });
    expect(model.view()).toEqual(store.view());
  });
});
