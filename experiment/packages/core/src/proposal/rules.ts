import type { OrganizerField } from "./fields.js";
import { pyLength, pyStrip } from "./python-text.js";

export const PROPOSAL_RATE_LIMIT_SECONDS = 300;

export const REUSABLE_SESSIONS_LIMIT = 5;

export const PROFILE_DISCORD_USERNAME_MAX_LENGTH = 150;

export const carriedAnswers = <V>(options: {
  readonly public: Readonly<Record<string, V>>;
  readonly private: Readonly<Record<string, V>>;
  readonly presented: boolean;
}): Readonly<Record<string, V>> =>
  options.presented
    ? { ...options.public, ...options.private }
    : { ...options.public };

export const proposalRateLimitKey = (options: {
  readonly eventId: number;
  readonly ip: string;
}): string => `proposal_rate:${options.eventId}:${options.ip}`;

export const discordAnswer = (
  answers: readonly { readonly field: OrganizerField; readonly value: string }[]
): string => {
  for (const { field, value } of answers) {
    if (field.fieldType === "discord") {
      const handle = pyStrip(value);

      if (pyLength(handle) <= PROFILE_DISCORD_USERNAME_MAX_LENGTH) {
        return handle;
      }
    }
  }

  return "";
};
