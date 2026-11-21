import type { Html } from "foldkit/html";

import type { Child } from "../../ui/html.js";
import { tabList, tabShell } from "../../ui/tabs.js";
import type { PanelH } from "./page.js";

export const panelTabs = (
  options: Readonly<{
    active: string;
    body: readonly Child[];
    tabs: readonly Readonly<{ href: string; key: string; label: string }>[];
  }>,
  h: PanelH
): Html =>
  tabShell(
    {
      body: h.div([], options.body),
      tabs: tabList(
        {
          tabs: options.tabs.map((tab) => ({
            ...tab,
            active: tab.key === options.active,
          })),
        },
        h
      ),
    },
    h
  );
