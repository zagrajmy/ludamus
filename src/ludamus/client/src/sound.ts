import type { SoundRole } from "./velvet-sound";

export const playSound = (role: SoundRole): void => {
  document.dispatchEvent(new CustomEvent("velvet:play", { detail: { role } }));
};
