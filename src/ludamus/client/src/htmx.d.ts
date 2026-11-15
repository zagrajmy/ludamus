declare const htmx: {
  ajax: (
    method: string,
    url: string,
    opts: { select?: string; swap: string; target: string },
  ) => void;
};
