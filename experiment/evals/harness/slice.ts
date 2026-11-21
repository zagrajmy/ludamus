export interface SliceArea {
  readonly area: string;
  readonly specs: readonly string[];
}

export const sliceAreas: readonly SliceArea[] = [
  {
    area: "Shell, feed, static pages",
    specs: [
      "feed-cards",
      "unlisted-events",
      "page-title",
      "footer-license",
      "content-pages",
      "theme-color",
      "sphere-logo",
      "about",
      "landing",
    ],
  },
  {
    area: "Event page",
    specs: [
      "event-details",
      "event-hero",
      "event-time",
      "event-description",
      "event-filters",
      "event-multiselect",
      "event-schedule-views",
      "event-schedule-folding",
      "event-schedule-rail",
      "event-slot-headers",
      "session-tags-cloud",
      "seat-label",
      "event-location-crumbs",
      "event-propose-entry",
      "link-preview",
      "proposal-status-badge",
      "markdown-sanitising",
      "worst-case",
    ],
  },
  {
    area: "Enrollment",
    specs: [
      "enroll-states.auth",
      "waiting-list.auth",
      "promotion.auth",
      "enrollment-banner.auth",
      "resign-after-close.auth",
      "session-bookmark-signed-out.auth",
      "signup-age.auth",
      "party-refusals.auth",
      "party-companion.auth",
    ],
  },
  {
    area: "Proposal wizard",
    specs: [
      "anonymous-proposal",
      "dynamic-fields",
      "write-in-fields",
      "proposal-duration",
      "proposal-form-layout",
      "uncategorized-proposal",
      "propose-reuse.auth",
      "discord-proposal.auth",
    ],
  },
  {
    area: "Panel core",
    specs: [
      "panel",
      "panel-crud",
      "panel-tracks",
      "proposal-cards",
      "proposal-status-filter",
      "proposal-delete-restore",
      "proposal-accept",
      "cover-images",
    ],
  },
];

export const specFileOf = (spec: string) => `${spec}.spec.ts`;

const areaBySpecFile = new Map(
  sliceAreas.flatMap(({ area, specs }) =>
    specs.map((spec) => [specFileOf(spec), area] as const)
  )
);

export const sliceAreaOf = (specFile: string) => areaBySpecFile.get(specFile);
