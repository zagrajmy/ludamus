// The panel's JSON writes (space tree, programme order): one POST with
// Django's CSRF header, and a failure surfaced as the page's error flash
// rather than a blocking alert().

import { pushFlash } from "./flash";

// The token Django rendered into the page: the widget's own data-csrf, else
// a form's hidden csrfmiddlewaretoken.
export const csrfToken = (el?: HTMLElement): string =>
  el?.dataset.csrf ??
  document.querySelector<HTMLInputElement>("[name=csrfmiddlewaretoken]")?.value ??
  "";

export const postJson = async ({
  body,
  csrfFrom,
  failure,
  url,
}: {
  body: unknown;
  csrfFrom: HTMLElement;
  failure: string;
  url: string;
}): Promise<boolean> => {
  try {
    const response = await fetch(url, {
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken(csrfFrom) },
      method: "POST",
    });
    if (response.ok) return true;
  } catch {
    // A transport failure reads the same as a refusal: the change did not land.
  }
  pushFlash("error", failure);
  return false;
};
