import { DateTime, Option } from "effect";

import type {
  DatedEnrollmentWindow,
  EnrollmentAccess,
  EnrollmentWindowLike,
} from "./schemas.js";

export interface EnrollmentPolicy<W extends EnrollmentWindowLike> {
  readonly windows: readonly W[];
}

export const admits = (options: {
  readonly window: EnrollmentWindowLike;
  readonly isConfiguredUser: boolean;
}): boolean =>
  options.isConfiguredUser || !options.window.restrictToConfiguredUsers;

export const policyForActor = <W extends EnrollmentWindowLike>(options: {
  readonly windows: readonly W[];
  readonly isConfiguredUser: boolean;
}): EnrollmentPolicy<W> => ({
  windows: options.windows.filter((window) =>
    admits({ isConfiguredUser: options.isConfiguredUser, window })
  ),
});

export const policyForGuest = <W extends EnrollmentWindowLike>(
  windows: readonly W[]
): EnrollmentPolicy<W> => policyForActor({ isConfiguredUser: false, windows });

export const policyForAnonymous = <W extends EnrollmentWindowLike>(
  windows: readonly W[]
): EnrollmentPolicy<W> => ({
  windows: policyForGuest(windows).windows.filter(
    (window) => window.allowAnonymousEnrollment
  ),
});

export const canEnroll = (
  policy: EnrollmentPolicy<EnrollmentWindowLike>
): boolean => policy.windows.length > 0;

const outranks = (
  candidate: EnrollmentWindowLike,
  best: EnrollmentWindowLike
): boolean => {
  if (candidate.percentageSlots !== best.percentageSlots) {
    return candidate.percentageSlots > best.percentageSlots;
  }

  return !candidate.restrictToConfiguredUsers && best.restrictToConfiguredUsers;
};

export const seatingWindow = <W extends EnrollmentWindowLike>(
  policy: EnrollmentPolicy<W>
): Option.Option<W> =>
  policy.windows.reduce<Option.Option<W>>(
    (best, window) =>
      Option.isSome(best) && !outranks(window, best.value)
        ? best
        : Option.some(window),
    Option.none()
  );

export const policyPercentageSlots = (
  policy: EnrollmentPolicy<EnrollmentWindowLike>
): number =>
  Option.match(seatingWindow(policy), {
    onNone: () => 0,
    onSome: (window) => window.percentageSlots,
  });

export const policyMaxWaitlistSessions = (
  policy: EnrollmentPolicy<EnrollmentWindowLike>
): number =>
  policy.windows.reduce(
    (most, window) => Math.max(most, window.maxWaitlistSessions),
    0
  );

export const requiresSlotAllowance = (
  policy: EnrollmentPolicy<EnrollmentWindowLike>
): boolean =>
  Option.match(seatingWindow(policy), {
    onNone: () => false,
    onSome: (window) => window.restrictToConfiguredUsers,
  });

export const policyEffectiveParticipantsLimit = (options: {
  readonly policy: EnrollmentPolicy<EnrollmentWindowLike>;
  readonly participantsLimit: number;
}): number => {
  if (!canEnroll(options.policy)) {
    return 0;
  }

  return Math.ceil(
    (options.participantsLimit * policyPercentageSlots(options.policy)) / 100
  );
};

export const policyIsFull = (options: {
  readonly policy: EnrollmentPolicy<EnrollmentWindowLike>;
  readonly participantsLimit: number;
  readonly enrolledCount: number;
}): boolean => {
  if (!canEnroll(options.policy)) {
    return false;
  }

  return options.enrolledCount >= policyEffectiveParticipantsLimit(options);
};

export const policyAvailableSlots = (options: {
  readonly policy: EnrollmentPolicy<EnrollmentWindowLike>;
  readonly participantsLimit: number;
  readonly enrolledCount: number;
}): number =>
  Math.max(
    0,
    policyEffectiveParticipantsLimit(options) - options.enrolledCount
  );

export const restrictsEveryone = (
  windows: readonly EnrollmentWindowLike[]
): boolean => windows.length > 0 && !canEnroll(policyForGuest(windows));

export const viewerAccess = (options: {
  readonly windows: readonly DatedEnrollmentWindow[];
  readonly configuredWindowIds: readonly number[];
  readonly now: DateTime.DateTime;
}): EnrollmentAccess => {
  const { now } = options;

  const usable = options.windows.filter((window) =>
    admits({
      isConfiguredUser: options.configuredWindowIds.includes(window.pk),
      window,
    })
  );

  const openWindowIds = [
    ...new Set(
      usable
        .filter(
          (window) =>
            DateTime.isLessThanOrEqualTo(window.startTime, now) &&
            DateTime.isLessThan(now, window.endTime)
        )
        .map((window) => window.pk)
    ),
  ].toSorted((a, b) => a - b);

  const upcoming = usable
    .map((window) => window.startTime)
    .filter((start) => DateTime.isGreaterThan(start, now));

  return {
    openWindowIds,
    opensAt: upcoming.reduce<DateTime.Utc | null>(
      (soonest, start) =>
        soonest === null || DateTime.isLessThan(start, soonest)
          ? start
          : soonest,
      null
    ),
  };
};

export const canEnrollNow = (access: EnrollmentAccess): boolean =>
  access.openWindowIds.length > 0;

export const accessSeats = (options: {
  readonly access: EnrollmentAccess;
  readonly windowIds: readonly number[];
}): boolean =>
  options.access.openWindowIds.some((id) => options.windowIds.includes(id));

export const NO_ENROLLMENT_ACCESS: EnrollmentAccess = {
  openWindowIds: [],
  opensAt: null,
};

export interface SchedulableWindow extends DatedEnrollmentWindow {
  readonly limitToEndTime: boolean;
}

export const isWindowActive = (options: {
  readonly window: DatedEnrollmentWindow;
  readonly now: DateTime.DateTime;
}): boolean =>
  DateTime.isLessThan(options.window.startTime, options.now) &&
  DateTime.isLessThan(options.now, options.window.endTime);

export const canSeat = (options: {
  readonly window: SchedulableWindow;
  readonly participantsLimit: number;
  readonly startTime: DateTime.DateTime | null;
}): boolean => {
  if (options.participantsLimit === 0) {
    return false;
  }

  if (options.window.limitToEndTime) {
    return (
      options.startTime !== null &&
      DateTime.isLessThan(options.startTime, options.window.endTime)
    );
  }

  return true;
};

export const activeWindows = <W extends DatedEnrollmentWindow>(options: {
  readonly windows: readonly W[];
  readonly now: DateTime.DateTime;
}): readonly W[] =>
  options.windows.filter((window) =>
    isWindowActive({ now: options.now, window })
  );

export const eligibleWindows = <W extends SchedulableWindow>(options: {
  readonly windows: readonly W[];
  readonly now: DateTime.DateTime;
  readonly participantsLimit: number;
  readonly startTime: DateTime.DateTime | null;
}): readonly W[] =>
  activeWindows(options).filter((window) =>
    canSeat({
      participantsLimit: options.participantsLimit,
      startTime: options.startTime,
      window,
    })
  );

export const allowanceWindows = <W extends DatedEnrollmentWindow>(options: {
  readonly windows: readonly W[];
  readonly now: DateTime.DateTime;
}): readonly W[] => {
  const active = activeWindows(options);

  if (active.length > 0) {
    return active;
  }

  const latest = options.windows
    .filter((window) =>
      DateTime.isLessThanOrEqualTo(window.endTime, options.now)
    )
    .reduce<W | null>((best, window) => {
      if (best === null) {
        return window;
      }

      const order = DateTime.Order(window.endTime, best.endTime);

      return order > 0 || (order === 0 && window.pk > best.pk) ? window : best;
    }, null);

  return latest === null ? [] : [latest];
};

export const sessionEffectiveParticipantsLimit = (options: {
  readonly participantsLimit: number;
  readonly eligibleWindows: readonly EnrollmentWindowLike[];
}): number => {
  if (options.participantsLimit === 0) {
    return 0;
  }

  const percentage = options.eligibleWindows.reduce(
    (most, window) => Math.max(most, window.percentageSlots),
    0
  );

  if (percentage === 0) {
    return options.participantsLimit;
  }

  return Math.ceil((options.participantsLimit * percentage) / 100);
};

export const sessionSeatsLeft = (options: {
  readonly effectiveParticipantsLimit: number;
  readonly enrolledCount: number;
}): number =>
  Math.max(0, options.effectiveParticipantsLimit - options.enrolledCount);

export const sessionIsFull = (options: {
  readonly participantsLimit: number;
  readonly effectiveParticipantsLimit: number;
  readonly enrolledCount: number;
}): boolean => {
  if (options.participantsLimit === 0) {
    return false;
  }

  return options.enrolledCount >= options.effectiveParticipantsLimit;
};
