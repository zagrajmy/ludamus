import { Schema } from "effect";

export const NavbarNotification = Schema.Struct({
  body: Schema.String,
  id: Schema.Int,
  isRead: Schema.Boolean,
  title: Schema.String,
  url: Schema.String,
});

export type NavbarNotification = typeof NavbarNotification.Type;

export const NavbarNotifications = Schema.Struct({
  items: Schema.Array(NavbarNotification),
  unreadCount: Schema.Int,
});

export type NavbarNotifications = typeof NavbarNotifications.Type;

export const NAVBAR_NOTIFICATION_LIMIT = 10;
