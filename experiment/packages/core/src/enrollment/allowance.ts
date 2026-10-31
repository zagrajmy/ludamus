import { DateTime, Effect, Option, Predicate } from "effect";

import { EnrollmentConfigId } from "../ids.js";
import { EnrollmentConfigStore } from "../ports/enrollment-config-store.js";
import { TicketApi } from "./ports.js";
import { decideMembershipLookup, membershipOutcome } from "./promotion.js";
import { allowedSlots } from "./rules.js";
import type {
  DatedEnrollmentWindow,
  VirtualEnrollmentConfig,
} from "./schemas.js";

const emailDomain = (email: string): string => {
  const at = email.indexOf("@");

  return at === -1 ? "" : (email.slice(at + 1).split("@")[0] ?? "");
};

const windowSlots = Effect.fn("Allowance.windowSlots")(
  function* windowSlots(options: {
    readonly windowId: number;
    readonly eventId: number;
    readonly email: string;
    readonly now: DateTime.Utc;
  }) {
    const configs = yield* EnrollmentConfigStore;
    const tickets = yield* TicketApi;
    const enrollmentConfigId = EnrollmentConfigId.make(options.windowId);

    const existing = Option.getOrNull(
      yield* configs.readUserConfig({
        enrollmentConfigId,
        userEmail: options.email,
      })
    );

    const lookup = decideMembershipLookup({ existing, now: options.now });

    const membershipCount =
      lookup === "refresh" || lookup === "create"
        ? yield* tickets
            .fetchMembershipCount({
              email: options.email,
              eventId: options.eventId,
            })
            .pipe(
              Effect.map((count): number | null => count),
              Effect.catchTag("MembershipApiError", () => Effect.succeed(null))
            )
        : null;

    const outcome = membershipOutcome({
      existing,
      lookup,
      membershipCount,
      now: options.now,
    });

    const { write } = outcome;

    if (write !== null && Predicate.isTagged(write, "CreateUserConfig")) {
      yield* configs.createUserConfig({
        allowedSlots: write.allowedSlots,
        enrollmentConfigId,
        fetchedFromApi: write.fetchedFromApi,
        lastCheck: write.lastCheck,
        userEmail: options.email,
      });
    }

    if (
      write !== null &&
      Predicate.isTagged(write, "UpdateUserConfig") &&
      existing !== null
    ) {
      yield* configs.updateUserConfig({
        ...existing,
        allowedSlots: write.allowedSlots,
        lastCheck: write.lastCheck,
      });
    }

    const userSlots =
      outcome.allowedSlots ??
      (write?._tag === "UpdateUserConfig"
        ? write.allowedSlots
        : (existing?.allowedSlots ?? 0));

    const domain = emailDomain(options.email);

    const domainSlots =
      domain === ""
        ? 0
        : Option.match(
            yield* configs.readDomainConfig({ domain, enrollmentConfigId }),
            { onNone: () => 0, onSome: (row) => row.allowedSlotsPerUser }
          );

    const slots: VirtualEnrollmentConfig = {
      domain: domainSlots > 0 ? domain : "",
      domainSlots,
      userSlots,
    };

    return slots;
  }
);

export const openWindows = <W extends DatedEnrollmentWindow>(options: {
  readonly windows: readonly W[];
  readonly now: DateTime.Utc;
}): readonly W[] =>
  options.windows.filter(
    (window) =>
      DateTime.isLessThanOrEqualTo(window.startTime, options.now) &&
      DateTime.isGreaterThanOrEqualTo(window.endTime, options.now)
  );

export const slotAllowance = Effect.fn("Allowance.slotAllowance")(
  function* slotAllowance(options: {
    readonly windows: readonly DatedEnrollmentWindow[];
    readonly eventId: number;
    readonly email: string;
    readonly now: DateTime.Utc;
  }) {
    const windows = openWindows(options);

    if (windows.length === 0 || options.email === "") {
      return Option.none<VirtualEnrollmentConfig>();
    }

    let total: VirtualEnrollmentConfig = {
      domain: "",
      domainSlots: 0,
      userSlots: 0,
    };

    for (const window of windows) {
      const slots = yield* windowSlots({
        email: options.email,
        eventId: options.eventId,
        now: options.now,
        windowId: window.pk,
      });

      total = {
        domain: total.domain === "" ? slots.domain : total.domain,
        domainSlots: total.domainSlots + slots.domainSlots,
        userSlots: total.userSlots + slots.userSlots,
      };
    }

    return allowedSlots(total) > 0 || total.domain !== ""
      ? Option.some(total)
      : Option.none<VirtualEnrollmentConfig>();
  }
);

export const hasSlotAccess = (options: {
  readonly windows: readonly DatedEnrollmentWindow[];
  readonly eventId: number;
  readonly email: string;
  readonly now: DateTime.Utc;
}) =>
  slotAllowance(options).pipe(
    Effect.map(Option.exists((config) => allowedSlots(config) > 0))
  );

export const windowsHoldingPasses = Effect.fn("Allowance.windowsHoldingPasses")(
  function* windowsHoldingPasses(options: {
    readonly windows: readonly (DatedEnrollmentWindow & {
      readonly restrictToConfiguredUsers: boolean;
    })[];
    readonly eventId: number;
    readonly email: string;
    readonly now: DateTime.Utc;
  }) {
    const restricted = options.windows.filter(
      (window) => window.restrictToConfiguredUsers
    );

    if (restricted.length === 0 || options.email === "") {
      return [];
    }

    const held: number[] = [];

    for (const window of restricted) {
      const slots = yield* windowSlots({
        email: options.email,
        eventId: options.eventId,
        now: options.now,
        windowId: window.pk,
      });

      if (allowedSlots(slots) > 0) {
        held.push(window.pk);
      }
    }

    return held;
  }
);
