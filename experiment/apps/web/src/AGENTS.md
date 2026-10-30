# apps/web/src — page guide

The Django app's pages, rebuilt as one Foldkit program that the server renders per request and the browser hydrates. Read `experiment/AGENTS.md` and the "Page architecture" section of `experiment/PLAN.md` first; this file is the local map.

## Layout

| Path | What lives there |
| --- | --- |
| `client/<page>/` | The page's program: `flags.ts` (Schema the server fills), `model.ts` (Schema Model + `init<Page>`), `message.ts`, `update.ts`, `command.ts` (named `Command.define`). No views. |
| `client/shell/` | The `base.html` program: sphere, viewer, links, flash, theme, consent. |
| `client/{model,message,init,update,subscriptions,entry}.ts` | Composition: `PageFlags`/`PageModel` tagged unions, `Got<Page>Message` wrappers, `Update.foldChild` per interactive page, browser boot. |
| `features/<page>/view.ts` | The page's thin view, plus `<page>Title` (and a description when the page overrides the default one). Reads the Model, sends Messages, nothing else. |
| `features/shell/` | Layout (`shellView`), `documentTitle`, default meta description. |
| `features/app.ts` | Root view: picks the page by tag, wraps it in the shell, sets the title. |
| `ui/` | Tessera ported to view functions (buttons, fields, tabs, cards, modal, menus, navbar, footer, …). Generic over `Message`, take `h` last. `ui/icons.ts` is generated from heroicons: import the named export you need (`calendarDaysOutline`). |
| `server/pages/<page>.ts` | `load<Page>(context)`: an `Effect.fn` returning the page's Flags from stores and capabilities. |
| `server/router.ts` | Pathname → loader, status and redirects (`Routed.Page` / `Routed.Redirect`). |
| `server/request-context.ts` | Host → sphere, root sphere, viewer, locale, translator, `now`. |
| `server/shell.ts`, `server/document.ts` | Shell flags; `<head>` metadata through `renderDocument`'s `head` option. |
| `entry.server.ts` | `renderPage`, `renderDocument`, `prerenderPaths`. |
| `styles/` | The Django Tailwind theme, copied; `@source` scans `src/**/*.ts`. |
| `../public/static/` | Django's static files, served at `/static/...`. |

Browser code (`client`, `features`, `ui`) imports from workspace packages only `@zagrajmy/core/contracts`, `@zagrajmy/capability/rpc-group` and `@zagrajmy/i18n`. Server code may import anything.

## Add a page

1. `client/<page>/flags.ts`: a `Schema.Struct` with exactly what the Django template's context held. Presentation the server can decide (date leaves, cover URLs, counts) is computed in the loader, not the view.
2. Static page: the Model is the Flags; skip the rest of the program. Interactive page: `model.ts` (Flags fields + browser state, `init<Page>`), `message.ts` (`ClickedX`, `SucceededX`, `FailedX`), `command.ts`, `update.ts` returning `Update.Return`.
3. `features/<page>/view.ts`: static pages export `view(flags, context, h)`; interactive pages export a `defineView<Model, Message, PageInputs>` and build their context with `pageContextOf(inputs.shell)` (view inputs may hold data only, no functions). Export `<page>Title(context): PageTitle`; `sphereSuffix: false` drops the sphere for pages whose name is the sphere.
4. Register the case in `client/model.ts` (`PageFlags`, `PageModel`), `client/init.ts`, and for interactive pages `client/message.ts` (`Got<Page>Message`), `client/update.ts` (`Update.foldChild`) and `features/app.ts` (`h.submodel`). Commands a page returns from `init` are lifted with `Command.mapMessage`; they run after hydration only.
5. `server/pages/<page>.ts` loader, then a branch in `server/router.ts`. Missing objects are `Routed.Page` of `NotFound` with status 404, never the home page. Redirects are `Routed.Redirect`.
6. Tests in `apps/web/test/`: `<page>.scene.test.ts` drives the root `{ update, view }` from `features/app.ts` with roles, text and `data-*` (fixtures in `test/fixtures.ts`); `<page>.story.test.ts` drives the page's `update`. Name the failure mode in the test title.

## Flags flow

Request → `loadRequestContext` (sphere by `Host`, root sphere by `SITE_ID`, viewer from the Django `sessionid`, locale from `django_language` or `Accept-Language`) → `route` → page loader → `loadShellFlags` → `Server.renderToString` with `Flags { shell, page }` → `renderDocument` adds the head. The browser decodes the same Flags and `init` rebuilds the Model, so first render and hydration agree.

## Strings

`translator(locale)` from `ui/i18n.ts` (re-exports `@zagrajmy/i18n`). `t(msgid, vars)`, `tc(context, msgid)`, `n(singular, plural, count, { counter: count })` — pass `counter` yourself. Msgids are the English source from the Django template, byte for byte (`&nbsp;` included). A `blocktranslate` with links goes through `linkedText(t(...), h)`.

## UI kit

Use `ui/` before writing markup: `button`/`linkButton`/`iconButton`, `field` + `textInput`/`textareaInput`/`selectInput`, `checkboxField`, `checkboxToggle`, `choiceGroup`, `radio`, `label`, `pill`/`pillList`, `tabList`/`tabShell`, `statCard`, `statusHero`, `emptyState`, `flashMessages`, `modal`/`confirmDialog` (wrap `@foldkit/ui/dialog`; keep a `Dialog.Model` in your page Model and fold `Dialog.update`), `actionDropdown`/`disclosureMenu`/`menuSurface`, `avatar`, `infoPopover`, `visibilityBadge`/`visibilityIcon`, `coverStrip`/`coverTint`/`feedCover`, `dateLeaf`, `eventCard`/`encounterCard`/`feedGrid`/`feedTag`, `pagination`, `navbar`, `footer`, `themeSwitcher`. Keep the Django markup's roles, labels and `data-*` hooks; specs read those.

## Run one spec

```sh
cd experiment
pnpm --filter @zagrajmy/core --filter @zagrajmy/i18n --filter @zagrajmy/database --filter @zagrajmy/auth run build
pnpm --filter @zagrajmy/web exec vite build && pnpm --filter @zagrajmy/server run build
DATABASE_PATH=$PWD/../dev.e2e.sqlite3 SECRET_KEY=e2e-secret-key node apps/server/dist/main.js &
cd ../tests/e2e && E2E_BASE_URL=http://localhost:8000 E2E_SKIP_WEBKIT=1 npx playwright test --project=chromium feed-cards.spec.ts
```

The Playwright config also waits for `http://localhost:8001/`; when the Django privacy server is not needed, anything answering there will do (`python3 -m http.server 8001`). Restart the Node host after every web build: it loads the server bundle once, and stale hashes 404 the client. Unit tests: `pnpm --filter @zagrajmy/web exec vitest run`.
