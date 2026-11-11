---
title: 'agents useAgent never redials a socket closed with any 4000-4999 code, whatever shouldReconnectOnClose says'
severity: 'minor'
---

### Expected Behavior

useAgent's shouldReconnectOnClose decides whether a closed socket redials, as with PartySocket.

### Current Behavior

agents 0.29 createCloseClassifier ANDs the caller's answer with !isTerminalCloseEvent, which treats 1008 and every 4000-4999 code as final. Parley's 4404 (not on the member list yet) was meant to redial and silently never did; only an e2e test waiting for the redial caught it.

### Possible Solution

Call reconnect() yourself from onClose, as use-room.ts now does.

### Minimal Reproducible Example

Close a useAgent socket from the server with code 4404 while shouldReconnectOnClose returns true: no reconnect follows.

### Context

src/ludamus/client/src/parley/use-room.ts, conversation rooms.
