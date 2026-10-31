import { Schema } from "effect";

import { AnnouncementId } from "./ids.js";
import { SphereId } from "./sphere.js";

export const Announcement = Schema.Struct({
  content: Schema.String,
  creationTime: Schema.DateTimeUtc,
  id: AnnouncementId,
  isPublished: Schema.Boolean,
  modificationTime: Schema.DateTimeUtc,
  notifiedAt: Schema.NullOr(Schema.DateTimeUtc),
  sphereId: SphereId,
  title: Schema.String,
});

export type Announcement = typeof Announcement.Type;
