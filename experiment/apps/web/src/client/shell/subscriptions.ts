import { Dom } from "foldkit";

import { darkSchemeQuery } from "./command.js";
import { ShellMessage } from "./message.js";

export const colorSchemeChanges = Dom.streamFromMediaQuery({
  mapMatches: () => ShellMessage.ChangedSystemColorScheme(),
  query: darkSchemeQuery,
});
