// Live seat-vs-waitlist projection on the enroll page. As the viewer ticks
// people, each newly included row shows whether that person gets a confirmed
// seat or joins the waiting list, mirroring the server's routing: newcomers are
// seated in row order against the seats left, cancels in the same submit free
// their seats first. Unticking someone currently in shows they will leave.
//
// Config rides on the [data-enroll-preview] root: data-seats-left (a number, or
// absent for an unlimited session) and the translated hint strings. Rows carry
// data-current-in (person is enrolled/waiting/holding) and data-occupies-seat
// (their departure frees a confirmed seat — waiting list spots don't).

const root = document.querySelector<HTMLElement>("[data-enroll-preview]");

type HintTone = "leave" | "seat" | "wait";

const HINT_TONES: Record<HintTone, string[]> = {
  leave: ["text-foreground-muted"],
  seat: ["text-success-text"],
  wait: ["text-warning-text"],
};

const paint = (hint: HTMLElement, kind: HintTone | null, text = ""): void => {
  for (const classes of Object.values(HINT_TONES)) hint.classList.remove(...classes);
  if (kind === null) {
    hint.hidden = true;
    return;
  }
  hint.textContent = text;
  hint.classList.add(...HINT_TONES[kind]);
  hint.hidden = false;
};

if (root) {
  const unlimited = root.dataset.seatsLeft === undefined;
  const seatsLeft = Number(root.dataset.seatsLeft ?? 0);
  const rows = [...root.querySelectorAll<HTMLElement>("[data-enroll-row]")];
  // The footer tally aggregates the row hints into one glanceable instrument:
  // how many of this submit's newcomers take seats, how many join the waiting
  // list. Icon + number only — the words live on the rows.
  const tally = root.querySelector<HTMLElement>("[data-enroll-tally]");
  const tallySeats = root.querySelector<HTMLElement>("[data-enroll-tally-seats]");
  const tallyWait = root.querySelector<HTMLElement>("[data-enroll-tally-wait]");

  const update = (): void => {
    let free = seatsLeft;
    let seated = 0;
    let waiting = 0;
    // Cancels first, exactly like the server: a freed seat is available to a
    // newcomer in the same submit.
    for (const row of rows) {
      const box = row.querySelector<HTMLInputElement>('input[type="checkbox"]');
      if (box && !box.checked && row.dataset.occupiesSeat === "1") free += 1;
    }
    for (const row of rows) {
      const box = row.querySelector<HTMLInputElement>('input[type="checkbox"]');
      const hint = row.querySelector<HTMLElement>("[data-seat-hint]");
      if (!box || !hint) continue;
      const currentIn = row.dataset.currentIn === "1";
      if (box.checked && !currentIn) {
        if (unlimited || free > 0) {
          paint(hint, "seat", root.dataset.msgSeat ?? "");
          if (!unlimited) free -= 1;
          seated += 1;
        } else {
          paint(hint, "wait", root.dataset.msgWait ?? "");
          waiting += 1;
        }
      } else if (!box.checked && currentIn) {
        paint(hint, "leave", root.dataset.msgLeave ?? "");
      } else {
        paint(hint, null);
      }
    }
    if (tally && tallySeats && tallyWait) {
      tallySeats.textContent = String(seated);
      tallyWait.textContent = String(waiting);
      tally.hidden = seated + waiting === 0;
    }
  };

  root.addEventListener("change", update);
  update();
}
