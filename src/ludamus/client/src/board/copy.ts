// English for every string the board shows. Django sends the translated
// copy with the bootstrap; these stand in for a key it leaves out and for
// the screens shown before the bootstrap arrives.
export const FALLBACK = {
  addDie: "Add %(die)s",
  addToPlaces: "Add to places",
  boardFull: "This board is full. You will join as soon as someone leaves.",
  boardGone: "This board no longer exists.",
  bootstrapFailed: "Could not open the board. Check your connection and try again.",
  cancel: "Cancel",
  clearPool: "Clear",
  close: "Close",
  connectionLost: "Connection lost. Reconnecting…",
  dice: "Dice",
  die: "d%(sides)s",
  guest: "guest",
  imagesComingSoon: "Images are coming soon",
  join: "Join",
  linkReset: "The link to this board was reset. Ask the owner for the new link.",
  loading: "Loading the board…",
  myPlace: "My place",
  nameHelp: "Others at the board will see this name.",
  noPlacesYet: "No places yet. Select a shape, then add it to places.",
  noRollsYet: "No rolls yet.",
  people: "People",
  placeName: "Place name",
  places: "Places",
  poolEmpty: "Tap dice to add them to the pool.",
  reload: "Reload",
  removeDie: "Remove %(die)s",
  removePlace: "Remove from places",
  retry: "Try again",
  roll: "Roll",
  rollAgain: "Roll again",
  rolledBy: "%(name)s rolled",
  rollFailed: "The roll did not go through. Try again.",
  rollLog: "Roll log",
  rollTooFast: "Wait a moment before rolling again.",
  save: "Save",
  total: "Total",
  you: "you",
  yourName: "Your name",
};

export type Copy = Record<keyof typeof FALLBACK, string>;

export function withFallbacks(copy: Partial<Copy> | undefined): Copy {
  return { ...FALLBACK, ...copy };
}

export function fill(template: string, values: Record<string, number | string>): string {
  return template.replaceAll(/%\((\w+)\)s/gu, (whole, key: string) =>
    key in values ? String(values[key]) : whole,
  );
}

export const dieLabel = (copy: Copy, sides: number): string => fill(copy.die, { sides });
