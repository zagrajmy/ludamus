let unavailable = false;

export const isDice3dDown = () => unavailable;

// NOTE: one failure (chunk or WebGL) turns the 3D off for the rest of the
// visit; the card carries the result alone.
export function dropDice3d(error: unknown) {
  if (!unavailable) console.error("board: 3D dice unavailable, showing the card only", error);
  unavailable = true;
}
