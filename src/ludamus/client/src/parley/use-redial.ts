import { useEffect, useRef } from "react";

type Redialable = {
  addEventListener(type: "close" | "open", listener: (event: Event) => void): void;
  reconnect: () => void;
  removeEventListener(type: "close" | "open", listener: (event: Event) => void): void;
};

type CloseRules = {
  // The Worker closed the socket because its pass has expired or been
  // revoked; the same pass would only be refused again.
  onPassClosed: () => void;
  // A conversation shut this person out. That may be a member list still on
  // its way, so this says whether they are still in it and worth a redial.
  onRefused?: () => Promise<boolean>;
};

// Spread into useAgent, whose own redials never stop and come at most 10 s
// apart: one tab that could not get in kept its rooms awake all day, and
// their wait cannot be cut short when the person comes back.
export const REDIAL_BY_HAND = { shouldReconnectOnClose: () => false };

const PASS_CLOSED = new Set([4401, 4403]);
const NOT_A_MEMBER = 4404;
const FIRST_WAIT_MS = 1000;
const LONGEST_WAIT_MS = 2 * 60 * 60 * 1000;
// A socket up this long had got in and then dropped; one that closed sooner
// was turned away, and the next try waits longer.
const SETTLED_MS = 5000;

const isFinal = (code: number) => code === 1008 || (code >= 4000 && code <= 4999);
const stayOut = () => Promise.resolve(false);

// Every close of a chat socket: a pass close fetches a new pass, a refusal
// redials only for a member, and any other drop redials after 1 s, then twice
// as long each time up to 2 h, and at once when the person is back: the tab
// shows again, or the network returns.
export function useRedial(socket: Redialable, { onPassClosed, onRefused = stayOut }: CloseRules) {
  const rules = useRef({ onPassClosed, onRefused });
  useEffect(() => {
    rules.current = { onPassClosed, onRefused };
  });
  useEffect(() => {
    let active = true;
    let failures = 0;
    let openedAt: number | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const dial = () => {
      timer = undefined;
      socket.reconnect();
    };
    const later = () => {
      if (!active) return;
      clearTimeout(timer);
      timer = setTimeout(dial, Math.min(FIRST_WAIT_MS * 2 ** failures, LONGEST_WAIT_MS));
      failures += 1;
    };
    const opened = () => {
      openedAt = Date.now();
    };
    const closed = (event: Event) => {
      const { code } = event as CloseEvent;
      if (openedAt !== null && Date.now() - openedAt >= SETTLED_MS) failures = 0;
      openedAt = null;
      if (PASS_CLOSED.has(code)) rules.current.onPassClosed();
      else if (code === NOT_A_MEMBER) {
        void rules.current.onRefused().then((member) => {
          if (member) later();
        });
      } else if (!isFinal(code)) later();
    };
    const back = () => {
      if (timer === undefined || document.visibilityState !== "visible") return;
      clearTimeout(timer);
      dial();
    };
    socket.addEventListener("open", opened);
    socket.addEventListener("close", closed);
    document.addEventListener("visibilitychange", back);
    globalThis.addEventListener("online", back);
    return () => {
      active = false;
      clearTimeout(timer);
      socket.removeEventListener("open", opened);
      socket.removeEventListener("close", closed);
      document.removeEventListener("visibilitychange", back);
      globalThis.removeEventListener("online", back);
    };
  }, [socket]);
}
