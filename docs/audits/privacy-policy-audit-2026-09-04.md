<!-- markdownlint-disable -->

# Privacy Policy Audit — 2026-09-04

What [`privacy-policy.md`](../../src/ludamus/content/privacy-policy.md)
(updated 21.08.2026) claims, against what the code does. Documentation only:
the policy file is untouched.

I traced every outbound call under `links/`, every model field holding
personal data, the consent path, and each retention promise. Not covered: the
env vars actually set on the OVH host, the Auth0 tenant config, and whether
processing agreements exist with any provider below. That is why a few
findings say "verify in production".

Engineering audit, not legal advice. The RODO references are places to point a
lawyer, not conclusions.

## Verdict

The analytics sections are accurate to the line. §3.4 and §3.5 describe the
PostHog split (consent-gated product analytics, consent-independent minimized
fault reports) and the code does exactly that. Whoever wrote those sections
read the code.

The rest has drifted. The policy describes a signup site that knows a
pseudonym and an email. The code runs a multi-tenant platform that fills the
display name with the person's legal name from their Google login, stores
whatever personal data an organizer decides to ask for, and talks to four
third parties §4 never mentions.

| # | Finding | Severity |
| --- | --- | --- |
| F1 | Enrollment sends user emails to a ticket shop; undisclosed | High |
| F2 | Google Sheets and Forms carry personal data both ways; Google undisclosed | High |
| F3 | §2 omits most of what is stored, real names included | High |
| F4 | Organizers do not exist in the policy; no controller model | High |
| F5 | Avatars leak to Gravatar, Google and Facebook on every page view | Medium-high |
| F6 | Retention promises nothing enforces; soft-deleted rows survive erasure | Medium-high |
| F7 | RSVP IPs kept forever to answer a 60-second question | Medium-high |
| F8 | §3.2 calls email notifications planned; they ship | Medium |
| F9 | Core service runs on legitimate interest where art. 6(1)(b) fits | Medium |
| F10 | Uploads may sit in a Google bucket, and orphans are never deleted | Medium |
| F11 | Nothing says which data is visible to other users or to the public | Medium |
| F12 | The MCP endpoint feeds event data to operators' AI agents | Medium |
| F13 | Four smaller gaps: cookies, transfers, art. 13 leftovers, contact | Low-medium |

F4 blocks the final wording of §1 and §4 and is the one an engineer cannot
settle alone. Everything under "Proposed policy text" can be applied as
written.

## Findings

### F1 — Enrollment sends user emails to a ticket shop — High

`links/sklep_kapitularz.py:89` sends the signed-in user's email to an external
shop's API to read how many memberships that address holds.
`mills/enrollment.py:611` calls it during enrollment, and the answer sets the
person's slot allowance at `:617-623`.

§4 lists OVH and Auth0 and stops. A shop learning that this address enrolled
at this event is a recipient, and art. 13(1)(e) wants recipients named.

Fix: name the provider in §4, say the email goes out and a count comes back.
Check whether an agreement covers it; this looks controller-to-controller
rather than entrusting.

### F2 — Google Sheets and Forms, both directions — High

`links/google_forms.py:36-39` and `links/google_sheets.py:31-45` read
spreadsheets and form definitions with a service account.
`mills/submissions/engine.py` turns those rows into `Facilitator` and
`PersonalDataFieldValue` records: a real name, an email, and whatever else the
organizer's form asked. Then `mills/konwencik.py:44-58` writes the scheduled
agenda back out to a sheet a third-party app reads, facilitator names and
photo links included.

Google is in neither §4 nor §5. One integration, three gaps: Google as a
processor, the transfer out of the EEA, and the onward disclosure to whoever
reads the exported sheet.

Fix: add Google to §4 and §5, and describe the CFP import as a source of data.
§2 currently implies every byte arrives from the user's own registration form.

### F3 — §2 omits most of what is stored — High

§2.1 says pseudonym, email, Auth0 id. What is actually in the tables:

| Stored | Where |
| --- | --- |
| Display name, filled with the real name from the social login | `models.py:106`; `crowd/auth.py:132-141,155` |
| Profile picture URL from the login provider | `models.py:128`; `crowd/auth.py:154,162` |
| Discord username | `models.py:122`, `crowd/forms.py:26-31` |
| Gravatar preference | `models.py:135` |
| Companion accounts and their single-use claim tokens | `models.py:143` |
| Party membership and invite tokens | `models.py:227-273` |
| Shadowban lists, so: who a user blocked | `models.py:186-207` |
| Event bans with a free-text reason | `models.py:209` |
| Session bookmarks | `models.py:275` |
| Notifications with rendered copy and payload | `models.py:1344` |
| Facilitator records: name, accreditation, guild, contact organizer | `models.py:893-935` |
| Whatever personal data an organizer decides to ask for | `models.py:1391-1507` |
| Change logs: who edited which field, old value and new | `models.py:1780,1844,1865` |
| Import log entries holding the imported row | `models.py:2024` |
| RSVP IP addresses | `models.py:1692`, see F7 |

The real-name row is the one that bothers me. Both the policy (§2.1) and the
Regulamin (§2.1.3, "pseudonim - nie musi być prawdziwym imieniem i
nazwiskiem") sell the account as pseudonymous, and then a Google or Facebook
login quietly writes the person's legal name and photo into their profile.

Fix: rewrite §2 from the table. Say that a social login imports the name and
picture that provider holds, and that the name can be changed afterwards.

### F4 — Organizers do not exist in the policy — High

A `Sphere` is a community site with its own domain, its own managers, its own
events. Sphere managers read participant lists, read personal-data answers,
ban people, mint MCP tokens, and configure the integrations from F1 and F2
that ship data to Google and to a shop.

The policy names one natural person as sole administrator and never mentions
any of them. Whoever decides the purposes for an organizer-run event is a
separate controller, a joint controller (art. 26), or a processor under an
entrusting agreement (art. 28), and users have to be told which.

Fix: decide the model, then write the section. Joint controllership also means
art. 26(2): the essence of the arrangement has to reach data subjects.

### F5 — Avatars leak on every page view — Medium-high

`links/gravatar.py:5-11` builds `gravatar.com/avatar/<sha256 of the email>`.
When that renders, the *viewer's* browser fetches it, so Automattic gets the
viewer's IP, the referring page, and a stable hash identifying the account
holder. A hashed email is pseudonymised, not anonymous. `avatar_url` does the
same for Google or Facebook, whose CDN serves the provider picture. The CSP
comment at `edges/settings.py:441` already admits avatars come from "arbitrary
Auth0/gravatar HTTPS hosts".

The Regulamin (§2.1.2) mentions Google and Facebook login; the policy does not.

Fix: proxy avatars server-side. One view that fetches and caches kills two
disclosures and lets `img-src` stop being `https:`. Failing that, disclose all
three recipients.

### F6 — Retention promises nothing enforces — Medium-high

§6 promises technical logs for at most 12 months and account data until the
account is deleted. There is no purge job in this repository. Nothing under
`inits/` or `mills/` deletes anything on a schedule. Meanwhile:

- `SoftDeleteModel` (`models.py:66-84`) stamps a timestamp and keeps the row.
  `Facilitator`, `Session` and `Discount` use it, so someone who asked for
  erasure has no way to know their facilitator record is still there.
- Change logs are built to outlive what they describe. The code says so:
  "`deleted_at` records when and a restore erases even that, so the log is the
  only trace of who" (`mills/submissions/personal_data_fields.py:70-72`).
- Import logs, notifications and RSVP rows have no expiry at all.

Fix: implement the retention §6 promises, or describe what the system does,
including the soft-deleted rows and the audit logs. A promise the code cannot
keep is worse than a longer honest number.

### F7 — RSVP IPs kept forever for a 60-second question — Medium-high

`models.py:1692` stores an IP on every encounter RSVP. Its only reader is
`mills/encounter.py:191` calling `recent_rsvp_exists(ip, seconds=60)`
(`repositories/notice_board.py:132`). The row is never deleted, and the column
shows up in Django admin next to the user (`admin.py:232`).

Keeping an identifier forever to answer a question with a 60-second window is
a minimisation problem (art. 5(1)(c)) whatever the policy says.

Fix (code): hash it, null it on a schedule, or move the flood check into the
cache and drop the column. Cheapest real win in the codebase.

### F8 — Email notifications ship — Medium

§3.2 calls user communication planned. `notifications.py:318` calls
`send_mail`, reached from eight notification kinds (`_deliver` callers at
`:78, :108, :134, :159, :183, :213, :245, :289`) covering waitlist promotions,
party invitations and shadowban warnings. SMTP is wired in every environment
(`edges/settings.py:583-593`).

Fix: drop "(planowana)", list the message types, and name the SMTP provider in
§4. It sees recipient addresses and message bodies.

### F9 — Legal basis for the core service — Medium

§3.1 and §3.2 rest the signup service and its transactional email on
legitimate interest. There is a Regulamin the user accepts
(`terms-of-service.md` §1.2.2) and this processing is what performs it, which
is art. 6(1)(b). Legitimate interest also wants a balancing test on file and
hands users an art. 21 objection right that §7.6 then describes generically.

Fix: move §3.1 and the transactional half of §3.2 to art. 6(1)(b). Keep
legitimate interest for security, abuse prevention and fault reporting, where
it belongs.

### F10 — Uploads: possibly Google, definitely orphaned — Medium

`edges/settings.py:44-47` accepts `GS_BUCKET_NAME`, `GS_CREDENTIALS_JSON` and
`GS_LOCATION` to put media in a Google bucket, and the CSP comment at `:441`
says "media from GCS". Verify in production whether that is on; if it is,
Google belongs in §4 and §5.

Either way, nothing deletes a file when its row goes.
`repositories/storage.py:35` deletes the file being *replaced*, and there is
no `post_delete` handler anywhere, so a deleted or soft-deleted row leaves its
upload behind.

### F11 — Being visible is a disclosure — Medium

Participant lists render on session pages. Facilitator names render in the
programme. `PersonalDataField.is_public` (`models.py:1410`) lets an organizer
publish an answer, and `Encounter.is_public` (`models.py:1660`) publishes an
encounter with its creator. §4 covers technical providers only, and the
disclosure users care about most is which of their neighbours can see what.

Fix: a §4 subsection splitting what other participants see, what organizers
see, and what the open internet sees.

### F12 — Event data reaches operators' AI agents — Medium

`/mcp/` and `/mcp/organizer/` let a maintainer's or organizer's LLM client
(Claude Code, Cursor, Executor, per `docs/agents/mcp.md`) drive the platform
through the same services the views use.
`gates/mcp/programme_tools.py:233` lists an event's facilitators by name, and
organizer tokens read sphere-wide.

The app itself calls no model and stores no LLM credentials; the docs are
explicit that it is a transport. The data still leaves through the operator's
agent to whatever provider that agent uses, and the policy has no word for AI
at all.

Fix: a short §4 entry saying operators may use AI assistants to run the
programme, what such a tool can reach, and that no automated decision about a
user is taken that way. Pair it with a rule that organizer tokens only go into
tools that do not train on the data.

### F13 — Four smaller gaps — Low-medium

**Cookies.** §9 describes three categories and names no cookie. PostHog also
persists to `localStorage` (`prologue.ts:205,227`), and the consent decision
itself is a `localStorage` key, not a cookie. The banner comment already
flags the tension (`components/consent-banner.html:8-11`). A small table with
names, purposes and lifetimes fixes it.

**Transfers.** §5 says "odpowiednie zabezpieczenia" without naming a
mechanism, and misses Google and Automattic. Name the safeguard per recipient.
Worth saying that PostHog is EU-hosted, since the company is not.

**Art. 13 leftovers.** Missing: whether providing the data is a contractual
requirement (13(2)(e)); automated decision-making (13(2)(f)), which covers
both waitlist auto-promotion and the F1 slot allowance; per-category retention
(13(2)(a)); and that withdrawing analytics consent does not undo what already
happened (13(2)(c)).

**Contact.** §1 and §14 give an email and no address. Separately, the site's
own Contact link renders `SUPPORT_EMAIL` (`templates/base.html:163`), which is
env-configured. Verify in production that it matches the policy, or the RODO
requests land in an inbox nobody is watching for them.

## What holds up

Checked, and fine. Worth knowing before anyone "improves" it:

- PostHog initialises only after an explicit accept (`prologue.ts:251`).
  Declining calls `stopSessionRecording`, drops the identity, then opts out,
  in that order and for a reason written down at `:235-242`. Recording sets
  `maskAllInputs: true` and holds social meta out of the snapshot
  (`:206-217`), which is what §3.4's masking claim promises.
- Fault reports carry the exception, a redacted path, the environment and the
  user pk, with `$process_person_profile: False` and `disable_geoip: True`
  (`links/analytics/reporting.py`). `docs/analytics.md` records the middleware
  deliberately not installed because it would have attached emails and IPs.
- No LLM provider SDK is imported anywhere in `src/`. F12 is the only
  residual exposure.
- Uploads get uuid names with an extension allowlist
  (`links/db/django/uploads.py`), so a filename cannot smuggle a content type.
- Integration secrets are encrypted and write-only at the repository surface
  (`models.py:1891-1893`).
- No payment data. `Discount` records an amount for an organizer's own
  accounting, and there is no PSP.
- The 16+ rule matches the Regulamin, and the claim that no birth date is
  collected is true.

## The ten-item list this audit started from

| # | Item | Here |
| --- | --- | --- |
| 1 | No privacy policy | Exists, linked from the footer and the consent banner |
| 2 | No "we collect user data" | §2 exists, and is missing most of it (F3) |
| 3 | No AI in the policy | Narrow gap (F12) |
| 4 | No third-party collectors | The main one (F1, F2, F5, F10) |
| 5 | Not deleting uploads | Orphans stay in storage (F10) |
| 6 | Public bucket | Media is public by design and no private files exist. Check the bucket has no listing |
| 7 | Fake testimonials | None |
| 8 | Cancelling harder than signing up | Both are one action. Account deletion is email-only, which is worth improving (F6) |
| 9 | Auto-renew | No subscriptions |
| 10 | AI with no self-harm response | No user-facing AI |

## Proposed policy text

Polish replacements for the worst gaps, in the existing file's style. Adjust
once F4 is decided, since it changes how §1 and §4 read.

### §2.1, replace

```markdown
### 2.1 Dane konta:

- Nazwa wyświetlana (może być pseudonimem; przy logowaniu przez Google lub
  Facebook wypełniamy ją imieniem i nazwiskiem z tego konta, a użytkownik może
  ją później zmienić w profilu)
- Adres email
- Unikalny identyfikator z systemu Auth0
- Adres zdjęcia profilowego pobrany od dostawcy logowania oraz wybór, czy
  zamiast niego pokazywać Gravatar
- Nazwa użytkownika na Discordzie (opcjonalnie)
- Nazwy wyświetlane osób dodanych do konta jako podopieczni
```

### §2.4, add

```markdown
### 2.4 Dane związane z udziałem w wydarzeniach:

- Zapisy, lista rezerwowa, zapisane punkty programu i przynależność do drużyn
- Dane twórców programu: nazwa wyświetlana, rodzaj akredytacji, przynależność
  do grupy oraz odpowiedzi na pytania o dane osobowe skonfigurowane przez
  organizatora danego wydarzenia
- Blokady użytkowników oraz blokady udziału w wydarzeniu wraz z powodem
- Historia zmian wprowadzanych w panelu organizatora i logi importu programu
- Powiadomienia wysłane w serwisie i pocztą elektroniczną
```

### §4, replace the provider list

```markdown
### 4.1 Dostawcy usług technicznych:

- **OVH SAS** (Francja) - hosting
- **Auth0 / Okta** (USA, Unia Europejska) - uwierzytelnianie. Logowanie przez
  Google lub Facebook oznacza, że wybrany dostawca dowiaduje się o korzystaniu
  z serwisu
- **Dostawca poczty wychodzącej** - powiadomienia email; widzi adres odbiorcy
  i treść wiadomości
- **Google Cloud Storage** - przechowywanie plików przesłanych do serwisu

### 4.2 Dostawcy analityki:

- **PostHog** - dane trafiają na serwery w Unii Europejskiej
  (`eu.i.posthog.com`). Dane z punktu 3.4 przekazujemy wyłącznie za zgodą;
  zgłoszenia błędów serwera z punktu 3.5 wysyłamy niezależnie od zgody

### 4.3 Usługi wykorzystywane przez organizatorów wydarzeń:

- **Google (Sheets, Forms)** - organizator może zaimportować zgłoszenia
  programu z arkusza lub formularza Google i wyeksportować harmonogram do
  arkusza czytanego przez zewnętrzną aplikację z programem wydarzenia.
  Eksportowany harmonogram zawiera nazwy twórców programu
- **Sklep z biletami** - przy zapisach na wydarzenie, w którym liczba miejsc
  zależy od posiadanego biletu lub członkostwa, wysyłamy do sklepu adres email
  użytkownika i otrzymujemy w odpowiedzi liczbę posiadanych uprawnień
- **Gravatar (Automattic, USA)** - jeżeli użytkownik wybierze awatar z
  Gravatara, przeglądarki osób oglądających profil pobierają obrazek z
  serwerów Gravatara; trafia tam skrót adresu email oraz adres IP osoby
  oglądającej

### 4.4 Inni użytkownicy i dostęp publiczny:

- Nazwa wyświetlana i zapisy są widoczne dla innych uczestników wydarzenia
- Organizatorzy widzą listy uczestników oraz odpowiedzi na pytania o dane
  osobowe skonfigurowane w danym wydarzeniu
- Program wydarzenia wraz z nazwami twórców programu jest publiczny
- Odpowiedzi na pytania oznaczone przez organizatora jako publiczne są
  widoczne dla wszystkich

### 4.5 Narzędzia administracyjne oparte na AI:

Osoby zarządzające serwisem i organizatorzy wydarzeń mogą korzystać z
asystentów AI do obsługi programu wydarzenia. Takie narzędzie działa na
uprawnieniach osoby, która je uruchamia, i może odczytać dane programu
wydarzenia, w tym nazwy twórców programu. Nie podejmujemy w ten sposób
zautomatyzowanych decyzji dotyczących użytkowników.
```

### §3.1, replace the basis

```markdown
- **Podstawa prawna:** niezbędność do wykonania umowy (art. 6 ust. 1 lit. b
  RODO) - umową jest Regulamin akceptowany przy korzystaniu z serwisu
```

### §6, add two entries

```markdown
- **Historia zmian w panelu organizatora i logi importu programu:** przez czas
  trwania wydarzenia i 12 miesięcy po jego zakończeniu; są to zapisy tego, kto
  wprowadził zmianę, i pozostają także po usunięciu opisywanego wpisu
- **Wpisy usunięte przez organizatora:** oznaczamy jako usunięte i
  przechowujemy przez 12 miesięcy, aby można było cofnąć pomyłkę
```

### §13a, add before "Zmiany polityki"

```markdown
## 13a. ZAUTOMATYZOWANE PODEJMOWANIE DECYZJI

W serwisie działają dwa mechanizmy automatyczne:

- zwolnione miejsce na wydarzeniu jest przydzielane kolejnej osobie z listy
  rezerwowej według kolejności zapisów,
- w wydarzeniach powiązanych ze sklepem z biletami liczba miejsc dostępnych
  dla użytkownika wynika z liczby uprawnień zwróconej przez sklep.

Nie profilujemy użytkowników i nie podejmujemy decyzji wywołujących skutki
prawne. W każdej sprawie można skontaktować się z nami pod adresem podanym w
punkcie 14 i poprosić o interwencję człowieka.
```

## Code changes worth making

1. Purge or hash `EncounterRSVP.ip_address` (F7).
2. Proxy avatars (F5). Removes two disclosures and the `img-src https:`
   wildcard with them.
3. Delete stored files when their row goes, soft deletes included (F10).
4. Implement the 12-month log retention §6 already promises (F6).
5. Check `SUPPORT_EMAIL` matches the policy's contact address (F13).
