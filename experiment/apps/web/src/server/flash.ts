import { Option, Schema } from "effect";

import { FlashLevel } from "../ui/flash.js";
import type { Flash } from "../ui/flash.js";

export const FLASH_COOKIE = "flash";

export const FlashNote = Schema.Struct({
  level: FlashLevel,
  text: Schema.String,
});

export type FlashNote = typeof FlashNote.Type;

const FlashCookie = Schema.fromJsonString(Schema.Array(FlashNote));

const cookieValue = (header: string | null) =>
  Option.fromNullishOr(
    (header ?? "")
      .split(";")
      .map((pair) => pair.trim())
      .find((pair) => pair.startsWith(`${FLASH_COOKIE}=`))
      ?.slice(FLASH_COOKIE.length + 1)
  );

const decodeComponent = (value: string) =>
  Option.liftThrowable(decodeURIComponent)(value);

export const hasFlashCookie = (request: Request) =>
  Option.isSome(cookieValue(request.headers.get("cookie")));

export const readFlashes = (request: Request): readonly Flash[] =>
  cookieValue(request.headers.get("cookie")).pipe(
    Option.flatMap(decodeComponent),
    Option.flatMap(Schema.decodeUnknownOption(FlashCookie)),
    Option.map((notes) =>
      notes.map((note, index) => ({
        id: `flash-${index}`,
        level: note.level,
        text: note.text,
      }))
    ),
    Option.getOrElse(() => [])
  );

export const flashCookieHeader = (notes: readonly FlashNote[]) =>
  `${FLASH_COOKIE}=${encodeURIComponent(JSON.stringify(notes))}; Path=/; SameSite=Lax`;

export const clearedFlashCookie = `${FLASH_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
