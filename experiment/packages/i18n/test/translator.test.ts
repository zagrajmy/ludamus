import { describe, expect, it } from "vitest";

import { translator } from "../src/translator.js";

const english = translator("en");

const polish = translator("pl");

describe("t", () => {
  it("returns the Polish msgstr for a catalog msgid", () => {
    expect(polish.t("That event isn't available.")).toBe(
      "To wydarzenie jest niedostępne."
    );
    expect(polish.t("Enrollment Open")).toBe("Zapisy otwarte");
  });

  it("returns the msgid itself in English", () => {
    expect(english.t("Enrollment Open")).toBe("Enrollment Open");
  });

  it("falls back to the msgid when Polish has no entry", () => {
    expect(polish.t("A sentence nobody translated")).toBe(
      "A sentence nobody translated"
    );
  });

  it("substitutes %(name)s placeholders in the translation", () => {
    expect(
      polish.t("Invalid choice for %(user)s: %(value)s", {
        user: "Ala",
        value: "7",
      })
    ).toBe("Nieprawidłowy wybór dla Ala: 7");
    expect(
      english.t("Invalid choice for %(user)s: %(value)s", {
        user: "Ala",
        value: 7,
      })
    ).toBe("Invalid choice for Ala: 7");
  });

  it("finds msgids that carry escaped quotes", () => {
    expect(
      polish.t('More in the <a href="%(privacy_url)s">Privacy Policy</a>.', {
        privacy_url: "/privacy/",
      })
    ).toBe('Więcej w <a href="/privacy/">Polityce prywatności</a>.');
  });

  it("turns %% into a percent sign once the message is formatted", () => {
    expect(polish.t("%(percentage)s%% of capacity", { percentage: 40 })).toBe(
      "40% pojemności"
    );
    expect(english.t("%(percentage)s%% of capacity", { percentage: 40 })).toBe(
      "40% of capacity"
    );
  });

  it("truncates numbers rendered through %(name)d like Python", () => {
    expect(english.t("%(count)d left", { count: 3.7 })).toBe("3 left");
  });

  it("substitutes {{ name }} and {name} placeholders", () => {
    expect(
      english.t("Jump to {{ day }} {{time}}", { day: "Friday", time: "16:00" })
    ).toBe("Jump to Friday 16:00");
    expect(english.t("Seen {count} times", { count: 2 })).toBe("Seen 2 times");
  });

  it("leaves a placeholder without a value as written", () => {
    expect(english.t("Hello %(name)s and {other}")).toBe(
      "Hello %(name)s and {other}"
    );
  });
});

describe("tc", () => {
  it("keeps entries with the same msgid apart by context", () => {
    expect(polish.tc("listing", "Seats")).toBe("Miejsca przy stole");
    expect(polish.tc("session capacity", "Seats")).toBe("Miejsca");
    expect(polish.tc("listing seeking", "GM")).toBe("MG");
    expect(polish.tc("date range", "to")).toBe("do");
  });

  it("does not answer a context-free lookup with a context entry", () => {
    expect(polish.t("Players")).toBe("Players");
    expect(polish.tc("listing seeking", "Players")).toBe("Graczy");
  });

  it("falls back to the msgid for an unknown context", () => {
    expect(polish.tc("no such context", "Seats")).toBe("Seats");
    expect(english.tc("listing", "Seats")).toBe("Seats");
  });
});

describe("n", () => {
  const seats = (locale: typeof polish, count: number) =>
    locale.n("%(counter)s seat", "%(counter)s seats", count, {
      counter: count,
    });

  it("picks the Polish plural form by the catalog's rule", () => {
    expect(seats(polish, 1)).toBe("1 miejsce");
    expect(seats(polish, 2)).toBe("2 miejsca");
    expect(seats(polish, 5)).toBe("5 miejsc");
    expect(seats(polish, 12)).toBe("12 miejsc");
    expect(seats(polish, 22)).toBe("22 miejsca");
    expect(seats(polish, 25)).toBe("25 miejsc");
    expect(seats(polish, 0)).toBe("0 miejsc");
  });

  it("uses one/other in English", () => {
    expect(seats(english, 1)).toBe("1 seat");
    expect(seats(english, 2)).toBe("2 seats");
    expect(seats(english, 0)).toBe("0 seats");
  });

  it("joins msgids the .po file splits across lines", () => {
    expect(
      polish.n(
        "This facilitator is named on {count} session. Remove them from it before deleting.",
        "This facilitator is named on {count} sessions. Remove them from those before deleting.",
        3,
        { count: 3 }
      )
    ).toBe(
      "Ten twórca programu jest przypisany do 3 punktów programu. Najpierw usuń go z nich."
    );
  });

  it("falls back to the English rule when Polish has no entry", () => {
    expect(polish.n("%(n)s apple", "%(n)s apples", 1, { n: 1 })).toBe(
      "1 apple"
    );
    expect(polish.n("%(n)s apple", "%(n)s apples", 4, { n: 4 })).toBe(
      "4 apples"
    );
  });
});

describe("nc", () => {
  it("looks plural entries up by context", () => {
    expect(polish.nc("landing stats", "event", "events", 1)).toBe("Wydarzenie");
    expect(polish.nc("landing stats", "event", "events", 3)).toBe("Wydarzenia");
    expect(polish.nc("landing stats", "event", "events", 7)).toBe("Wydarzeń");
    expect(polish.n("event", "events", 7)).toBe("events");
  });
});
