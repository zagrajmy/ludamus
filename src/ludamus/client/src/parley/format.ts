import type { Copy } from "./protocol";

const locale = (): string => document.documentElement.lang || "pl";

type Counted = "presence" | "unreadCount";

export function counted(copy: Copy, key: Counted, count: number): string {
  const rule = new Intl.PluralRules(locale()).select(count);
  const form = rule === "one" ? "One" : rule === "few" ? "Few" : "Many";
  return copy[`${key}${form}`].replace("%(count)s", String(count));
}

const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;

const startOfDay = (time: number): number => new Date(time).setHours(0, 0, 0, 0);

export function clock(time: number): string {
  return new Intl.DateTimeFormat(locale(), { hour: "2-digit", minute: "2-digit" }).format(time);
}

// A run separator: the time alone today, the weekday within a week, the date
// beyond it, the way a chat thread reads back.
export function separator(time: number, now = Date.now()): string {
  const days = Math.round((startOfDay(now) - startOfDay(time)) / DAY);
  if (days === 0) return clock(time);
  const options: Intl.DateTimeFormatOptions =
    days < 7 ? { weekday: "long" } : { day: "numeric", month: "long" };
  return `${new Intl.DateTimeFormat(locale(), options).format(time)}, ${clock(time)}`;
}

// The room list's timestamp: how long ago in minutes and hours, then a
// weekday or date once it is no longer today.
export function ago(time: number, now = Date.now()): string {
  const minutes = Math.round((now - time) / MINUTE);
  const relative = new Intl.RelativeTimeFormat(locale(), { numeric: "auto", style: "short" });
  if (minutes < 60) return relative.format(-Math.max(0, minutes), "minute");
  if (startOfDay(time) === startOfDay(now))
    return relative.format(-Math.round(minutes / 60), "hour");
  const days = Math.round((startOfDay(now) - startOfDay(time)) / DAY);
  const options: Intl.DateTimeFormatOptions =
    days < 7 ? { weekday: "short" } : { day: "numeric", month: "short" };
  return new Intl.DateTimeFormat(locale(), options).format(time);
}

export const fullTime = (time: number): string =>
  new Intl.DateTimeFormat(locale(), { dateStyle: "long", timeStyle: "short" }).format(time);
