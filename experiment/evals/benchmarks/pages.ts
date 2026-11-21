export type BenchPage = Readonly<{
  label: string;
  path: string;
  host?: string;
  authState?: string;
}>;

export const benchPages: readonly BenchPage[] = [
  {
    host: "crew.localhost",
    label: "events feed (crew sphere root)",
    path: "/",
  },
  { label: "landing (root sphere, anonymous)", path: "/" },
  { label: "event page (3 sessions)", path: "/event/autumn-open/" },
  {
    label: "event page (dense, 100+ sessions)",
    path: "/event/kapitularz-2025-anonymized/",
  },
  { label: "proposal wizard entry", path: "/event/open-mic/session/propose/" },
  { label: "about", path: "/about/" },
  {
    authState: ".auth-state-manager.json",
    label: "panel facilitators (manager)",
    path: "/panel/event/frostfire-con/facilitators/",
  },
  {
    authState: ".auth-state.json",
    label: "event page (signed in)",
    path: "/event/enroll-states/",
  },
];

export const pageUrl = (origin: string, page: BenchPage): string => {
  const url = new URL(origin);

  if (page.host !== undefined) {
    url.hostname = page.host;
  }

  return `${url.origin}${page.path}`;
};
