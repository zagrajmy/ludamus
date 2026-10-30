import { Runtime } from "foldkit";

import { view } from "../features/app.js";
import { init } from "./init.js";
import { Message } from "./message.js";
import { Flags, Model } from "./model.js";
import { update } from "./update.js";

import "../styles.css";

const application = Runtime.makeApplication({
  Flags,
  Model,
  container: document.querySelector("#root"),
  init,
  routing: {
    onUrlChange: (url) => Message.ChangedUrl({ url }),
    onUrlRequest: (request) => Message.ClickedLink({ request }),
  },
  update,
  view,
});

Runtime.hydrate(application);
