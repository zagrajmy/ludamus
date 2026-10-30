import type { Update } from "foldkit";
import { UrlRequest } from "foldkit/navigation";
import { modifyFields } from "foldkit/struct";
import { toString as urlToString } from "foldkit/url";

import { LoadPage } from "./command.js";
import { Message } from "./message.js";
import type { Model } from "./model.js";

type Return = Update.Return<Model, Message>;

export const update = (model: Model, message: Message): Return =>
  Message.match<Return>(message, {
    ChangedUrl: () => ({ model }),
    ClickedLink: ({ request }) =>
      UrlRequest.match<Return>(request, {
        External: ({ href }) => ({ commands: [LoadPage({ href })], model }),
        Internal: ({ url }) => ({
          commands: [LoadPage({ href: urlToString(url) })],
          model,
        }),
      }),
    NavigatedAway: () => ({ model }),
    ToggledMenu: () => ({
      model: modifyFields(model, { menuOpen: (open) => !open }),
    }),
  });
