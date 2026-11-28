# Translation conventions (Polish)

- **session** → "punkt programu" (except in "RPG session" → "sesja RPG";
  event-hero CTA "Sign up for sessions" → "Zapisz się na sesje")
- **track** → "blok" or "blok programowy"
- **facilitator** → "twórca programu"
- **time slot** → "przedział czasowy" (do **not** use "blok czasowy" — collides
  with the "track" translation)
- **proposal category** (prelekcja, sesja RPG, warsztaty, …) →
  "rodzaj atrakcji" on participant-facing pages (do **not** use "kategoria" —
  counterintuitive there); "kategoria" stays OK in the organizer panel
- **listing** (board) → "ogłoszenie"; a **response** to one → "zgłoszenie"
  ("I'm interested" → "Zgłaszam się"), declining it → "Nie tym razem". Keep
  board copy gender-neutral: nouns ("zgłoszenie") over past-tense verbs
  ("zgłosiłeś się")
- **board** (a Little Table whiteboard framed on `/b/…`) → "tablica"; the
  chat's label for it is `pgettext("the whiteboard a chat belongs to",
  "Board")`, because plain "Board" is the listings board. That one (`/board/`)
  stays "Ogłoszenia", so the two never share a name. "Little Table" is a
  product name and stays in English.
- **Gender in Polish UI copy:** address the reader without gendered forms.
  Prefer status phrases with present tense ("jesteś na liście", "jesteś
  na tym punkcie programu"), imperatives ("zaloguj się"), and impersonal
  result lines ("wypisano Cię"). Avoid awkward noun stock phrases like
  "masz zapis".
  Do **not** default to masculine past tense ("zapisałeś się", "zostałeś
  dodany"). Do **not** use slash/parenthetical endings ("łeś/aś",
  "zapisany/a", "zalogowany(-a)") or marked "inclusive" spellings ("*a",
  "_ka", "·a"). Grammatical agreement with a noun is fine ("gracz
  został…", "osoba dostała…").
- **gracze:** keep plural "graczy" for seeking players and similar board
  copy ("Szuka graczy", filter "Graczy", "znajdź graczy") — do **not**
  swap in "drużyny" there (unclear) and do **not** write "graczy/ek".
- **Activity labels over osobatywy:** when labeling who does what next to
  a name or a list, prefer verb headings — "Prowadzi", "Grają",
  "Udział biorą" — over stiff person-nouns ("osoby grające", "osoby
  uczestniczące"). `use_participants_label` picks the roster pair:
  off → "Grają", on → "Udział biorą". Presenter field → "Prowadzi".
  "osoby…" stays fine where no activity label fits ("osoby towarzyszące",
  "Osoby z cichym banem"). Safety list of past co-players: "Spotkane
  osoby". Landing audience switch: "Dla organizacji" / "Dla
  uczestniczących".
- **shadowban action** → "Zbanuj" (not "Cichy ban" on the button); the
  feature noun can still say "cichy ban" in longer help text.
