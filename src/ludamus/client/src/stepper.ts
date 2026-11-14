// The − / + stepper (`components/stepper-field.html`) is UI SDK's Number
// Input: the custom elements wrap the server-rendered input and buttons, so
// the field still types and submits without JS. Elements swapped in by htmx
// upgrade on their own.
import "@ui-sdk/web/number-input";

// NOTE: the inner <input> keeps its `name` and submits its text, so the text
// must stay a bare number — Polish grouping would post "12 345".
const plain = (root: ParentNode): void => {
  for (const stepper of root.querySelectorAll("ui-number-input")) {
    stepper.format = { useGrouping: false };
  }
};

plain(document);
document.addEventListener("htmx:load", (event) => {
  if (event.target instanceof Element) plain(event.target.parentNode ?? event.target);
});
