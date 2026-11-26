// Every string the board shows, in English and Polish. The Polish follows the
// site's glossary (src/ludamus/locale/CLAUDE.md): the board is "tablica", a
// place is "miejsce", a die is "k6", and the copy stays gender-neutral.
// `%(name)s`-style placeholders are filled in by `fill`.
const EN = {
  addDie: "Add %(die)s",
  addToPlaces: "Add to places",
  backTo: "Back to %(sphere)s",
  backToMain: "Back to the main page",
  boardFull: "This board is full. You will join as soon as someone leaves.",
  boardGone: "This board no longer exists.",
  bootstrapFailed: "Could not open the board. Check your connection and try again.",
  cancel: "Cancel",
  clearPool: "Clear",
  close: "Close",
  connectionLost: "Connection lost. Reconnecting…",
  dice: "Dice",
  die: "d%(sides)s",
  guest: "Guest",
  imagesComingSoon: "Images are coming soon.",
  join: "Join the board",
  linkReset: "The board's link was reset. Ask its creator for the new one.",
  loading: "Opening the board…",
  myBoards: "My boards",
  myPlace: "My place",
  nameHelp: "Others at the board see this name. Up to 40 characters.",
  nameInvalid: "This name cannot be used. Try another one.",
  noPlacesYet: "No places yet. Select something on the board and add it to places.",
  noRollsYet: "Nobody has rolled yet.",
  people: "People",
  placeName: "Place name",
  places: "Places",
  poolEmpty: "Tap dice to add them to the roll.",
  reload: "Reload",
  removeDie: "Remove %(die)s",
  removePlace: "Remove from places",
  retry: "Try again",
  roll: "Roll",
  rollAgain: "Roll %(pool)s again",
  rolledBy: "%(name)s rolled",
  rollFailed: "The roll did not go through. Try again.",
  rollLog: "Roll log",
  rollTooFast: "Wait a moment before rolling again.",
  save: "Save",
  tooManyTries: "Too many tries. Wait a minute, then try again.",
  total: "Total",
  you: "you",
  yourName: "Your name",
};

export type Copy = Record<keyof typeof EN, string>;

const PL: Copy = {
  addDie: "Dodaj %(die)s",
  addToPlaces: "Dodaj do miejsc",
  backTo: "Wróć na stronę %(sphere)s",
  backToMain: "Wróć na stronę główną",
  boardFull: "Tablica jest pełna. Dołączysz, gdy tylko ktoś wyjdzie.",
  boardGone: "Ta tablica już nie istnieje.",
  bootstrapFailed: "Nie udało się otworzyć tablicy. Sprawdź połączenie i spróbuj ponownie.",
  cancel: "Anuluj",
  clearPool: "Wyczyść",
  close: "Zamknij",
  connectionLost: "Utracono połączenie. Łączymy ponownie…",
  // NOTE: the site's catalog shared this msgid with Parley's single die
  // ("Kość do gry"); the board's tray holds several, so it reads "Kości".
  dice: "Kości",
  die: "k%(sides)s",
  guest: "Gość",
  imagesComingSoon: "Dodawanie obrazów już wkrótce.",
  join: "Dołącz do tablicy",
  linkReset: "Ten link do tablicy już nie działa. Poproś o nowy osobę, która ją założyła.",
  loading: "Otwieramy tablicę…",
  myBoards: "Moje tablice",
  myPlace: "Moje miejsce",
  nameHelp: "Wszyscy przy tablicy zobaczą to imię. Do 40 znaków.",
  nameInvalid: "Tego imienia nie można użyć. Wpisz inne.",
  noPlacesYet: "Nie ma jeszcze miejsc. Zaznacz coś na tablicy i dodaj to do miejsc.",
  noRollsYet: "Nikt jeszcze nie rzucał.",
  people: "Osoby",
  placeName: "Nazwa miejsca",
  places: "Miejsca",
  poolEmpty: "Dotknij kości, żeby dodać je do rzutu.",
  reload: "Odśwież",
  removeDie: "Usuń %(die)s",
  removePlace: "Usuń z miejsc",
  retry: "Spróbuj ponownie",
  roll: "Rzuć",
  rollAgain: "Rzuć %(pool)s jeszcze raz",
  rolledBy: "%(name)s rzuca",
  rollFailed: "Nie udało się wykonać rzutu. Spróbuj ponownie.",
  rollLog: "Historia rzutów",
  rollTooFast: "Zaczekaj chwilę przed kolejnym rzutem.",
  save: "Zapisz",
  tooManyTries: "Za dużo prób. Zaczekaj minutę i spróbuj ponownie.",
  total: "Suma",
  you: "ty",
  yourName: "Twoje imię",
};

export type Language = "en" | "pl";

export const COPY: Record<Language, Copy> = { en: EN, pl: PL };

export function fill(template: string, values: Record<string, number | string>): string {
  return template.replaceAll(/%\((\w+)\)s/gu, (whole, key: string) =>
    key in values ? String(values[key]) : whole,
  );
}

export const dieLabel = (copy: Copy, sides: number): string => fill(copy.die, { sides });
