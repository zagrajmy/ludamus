import type { Message } from "./protocol";

// The latest messages of the rooms opened most recently, so reopening one
// shows them at once while the room's own answer is on its way. One lives
// as long as one chat pass, so it never outlasts the person it was filled for.
const ROOMS = 20;

export type RoomCache = {
  forget: (roomId: string) => void;
  recall: (roomId: string) => Message[] | undefined;
  remember: (roomId: string, messages: Message[]) => void;
};

export function roomCache(): RoomCache {
  const rooms = new Map<string, Message[]>();
  return {
    forget: (roomId) => void rooms.delete(roomId),
    recall: (roomId) => rooms.get(roomId),
    remember: (roomId, messages) => {
      rooms.delete(roomId);
      rooms.set(roomId, messages);
      const oldest = rooms.keys().next();
      if (rooms.size > ROOMS && oldest.done !== true) rooms.delete(oldest.value);
    },
  };
}
