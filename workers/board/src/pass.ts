import { importSPKI, jwtVerify } from "jose";

import { MAX_NAME_LENGTH } from "./limits";

export type PassEnv = {
  BOARD_PUBLIC_KEY: string;
  JWT_AUDIENCE: string;
  JWT_ISSUER: string;
};

// What the app vouches for: this person may be on this board while the
// board's link is at this version.
export type Pass = {
  board: string;
  link: number;
  name: string;
  owner: boolean;
  sub: string;
};

export async function verifyPass(token: string, env: PassEnv): Promise<Pass> {
  const publicKey = await importSPKI(env.BOARD_PUBLIC_KEY.replaceAll("\\n", "\n"), "RS256");
  const { payload } = await jwtVerify(token, publicKey, {
    algorithms: ["RS256"],
    audience: env.JWT_AUDIENCE,
    issuer: env.JWT_ISSUER,
    requiredClaims: ["exp", "iat", "sub"],
  });
  const { board, link, name, owner, sub } = payload;
  if (
    typeof sub !== "string" ||
    typeof board !== "string" ||
    typeof name !== "string" ||
    name.length === 0 ||
    name.length > MAX_NAME_LENGTH ||
    typeof owner !== "boolean" ||
    !Number.isInteger(link) ||
    (link as number) < 0
  ) {
    throw new Error("Invalid pass");
  }
  return { board, link: link as number, name, owner, sub };
}

export const DELETION_AUDIENCE = "board-deletion";

// NOTE: its own audience keeps the two kinds apart: a pass cannot delete a
// board, and a deletion token cannot open a socket or roll.
export async function verifyDeletion(token: string, env: PassEnv): Promise<string> {
  const publicKey = await importSPKI(env.BOARD_PUBLIC_KEY.replaceAll("\\n", "\n"), "RS256");
  const { payload } = await jwtVerify(token, publicKey, {
    algorithms: ["RS256"],
    audience: DELETION_AUDIENCE,
    issuer: env.JWT_ISSUER,
    requiredClaims: ["exp"],
  });
  if (typeof payload.board !== "string") throw new Error("Invalid deletion token");
  return payload.board;
}
