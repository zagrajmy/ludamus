import type { Connection } from "agents";

import { capabilityCookie, verifyCapability, type AuthEnv } from "./auth";
import {
  PASS_EXPIRED,
  PASS_REVOKED,
  type Capability,
  type ConnectionState,
  type Revocation,
  type ServerEvent,
} from "./protocol";

type Sockets = Iterable<Connection<ConnectionState>>;

function expired(capability: Capability): boolean {
  return capability.exp * 1_000 <= Date.now();
}

export function revokes(
  revocation: Pick<Revocation, "revokedBefore" | "sub">,
  capability: Capability,
): boolean {
  return (
    (revocation.sub === "*" || revocation.sub === capability.sub) &&
    capability.iat < revocation.revokedBefore
  );
}

export function passOf(connection: Connection<ConnectionState> | undefined): Capability {
  const state = connection?.state;
  if (connection === undefined || !state?.admitted) throw new Error("Missing capability");
  if (expired(state.capability)) {
    connection.close(PASS_EXPIRED, "Pass expired");
    throw new Error("Pass expired");
  }
  return state.capability;
}

export function sendWhere(
  sockets: Sockets,
  event: ServerEvent,
  include: (capability: Capability) => boolean = () => true,
): void {
  const message = JSON.stringify(event);
  for (const connection of sockets) {
    const state = connection.state;
    if (!state?.admitted || !include(state.capability)) continue;
    if (expired(state.capability)) connection.close(PASS_EXPIRED, "Pass expired");
    else connection.send(message);
  }
}

export function closeRevokedIn(
  sockets: Sockets,
  revocation: Pick<Revocation, "revokedBefore" | "sub">,
): void {
  for (const connection of sockets) {
    const capability = connection.state?.capability;
    if (capability !== undefined && revokes(revocation, capability)) {
      connection.close(PASS_REVOKED, "Access revoked");
    }
  }
}

// SAFETY: thrown from onConnect, a refusal closes the socket as a server
// error, which the browser redials every ten seconds for as long as the tab
// stays open, keeping the room awake. A pass close sends it for a new pass.
export async function passOnConnect(
  connection: Connection<ConnectionState>,
  request: Request,
  env: AuthEnv,
): Promise<Capability | null> {
  const token = capabilityCookie(request);
  const capability = token === null ? null : await verifyCapability(token, env).catch(() => null);
  if (capability === null) {
    const reason = token === null ? "Pass missing" : "Pass invalid";
    console.warn(`parley socket refused: ${reason}`);
    connection.close(PASS_EXPIRED, reason);
  }
  return capability;
}
