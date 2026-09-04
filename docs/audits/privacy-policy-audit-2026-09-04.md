<!-- markdownlint-disable -->

# Privacy Policy Audit — 2026-09-04

Audit of [`src/ludamus/content/privacy-policy.md`](../../src/ludamus/content/privacy-policy.md)
(last updated 21.08.2026) against what the code in this repository actually
collects, stores, and sends outside. This is a **documentation-only** report:
it records findings and carries ready-to-paste Polish replacement text. It
changes neither the policy nor any source file.

## Method

Read the policy, then traced every outbound call, every model field holding
personal data, every consent gate, and every retention promise back to code.

- Outbound hosts: `grep` over `src/ludamus/links/` plus CSP allowances in
  `edges/settings.py`.
- Stored personal data: every `models.py` field on `User` and on models with
  a `User`/`Facilitator` foreign key.
- Consent and analytics: `client/src/prologue.ts`, `links/analytics/`.
- Retention: searched for purge/cleanup jobs (there are none).

Not covered: the deployed production configuration (which env vars are
actually set on the OVH host), the Auth0 tenant settings, contracts with
processors (DPAs), and the register of processing activities. Several
findings below say "verify in production" because the code allows a setup
the policy does not describe, and only the deployment shows which is live.

**This is an engineering audit, not legal advice.** The GDPR article
references point at what to check with a lawyer, not at settled conclusions.

## Verdict

The policy is unusually honest about analytics — §3.4/§3.5 describe the
PostHog split (consent-gated product analytics, consent-independent minimized
fault reports) and the code matches it line for line. That part is better than
most.

Everything else has drifted. The policy describes a small event-signup site
that knows a pseudonym and an email. The code is a multi-tenant platform that
imports real names from social logins, holds arbitrary organizer-defined
personal data, and talks to four third parties the policy never names.

| # | Finding | Severity |
| --- | --- | --- |
| F1 | User emails are sent to a third-party ticket shop (Sklep Kapitularz); not disclosed | High |
| F2 | Google Sheets/Forms import and export move personal data; Google not disclosed | High |
| F3 | §2 data categories omit most of what is stored, including real names | High |
| F4 | Organizers (spheres) are invisible in the policy; no controller/processor split | High |
| F5 | Gravatar (Automattic, US) receives hashed emails and viewer IPs; not disclosed | Medium-high |
| F6 | Retention promises are backed by no code; soft-deleted data survives "deletion" | Medium-high |
| F7 | RSVP IP addresses stored forever to serve a 60-second rate limit | Medium-high |
| F8 | §3.2 calls email notifications "planowana"; they have been live for a while | Medium |
| F9 | Legal basis for the core service should be art. 6(1)(b), not legitimate interest | Medium |
| F10 | Media may live in a Google Cloud Storage bucket; not disclosed | Medium |
| F11 | Social login (Google/Facebook via Auth0) and provider avatars not disclosed | Medium |
| F12 | Data published to other users and to the open web is not described as disclosure | Medium |
| F13 | The MCP endpoint hands event data to operators' AI agents; not disclosed | Medium |
| F14 | Missing mandatory art. 13 elements (automated decisions, provision requirement) | Medium |
| F15 | §9 cookies section omits `localStorage` and names no cookie | Low-medium |
| F16 | §5 third-country transfers name no safeguard and miss Google and Gravatar | Low-medium |
| F17 | Controller identified by email only; no address; site contact may differ | Low |

## Findings

### F1 — User emails go to Sklep Kapitularz, undisclosed — High

`src/ludamus/links/sklep_kapitularz.py:89-110` sends the signed-in user's
email address to an external shop's HTTPS API to read how many memberships
that person holds; `mills/enrollment.py:611` and `:637` call it on the
enrollment path, and the answer decides how many session slots the person
gets (`enrollment.py:617-623`).

The policy's §4 lists exactly two technical providers, OVH and Auth0. A
commercial ticket shop learning "this email address enrolled at this event"
is a disclosure to a separate controller, and disclosing the categories of
recipients is not optional (art. 13(1)(e) RODO).

**Fix:** name the ticketing provider in §4, say the email is what is sent
and the membership count is what comes back, and state the basis. Also
confirm whether a data-processing or data-sharing agreement exists — a
lookup like this is likely controller-to-controller, not entrusting.

### F2 — Google Sheets/Forms move personal data both ways, undisclosed — High

- `links/google_forms.py:36-39` and `links/google_sheets.py:31-45` read
  spreadsheets and form definitions with a Google service account.
- `mills/submissions/engine.py` imports proposal rows into `Facilitator` and
  `PersonalDataFieldValue` rows — that is a facilitator's real name, email,
  and whatever else the organizer's form asked for.
- `mills/konwencik.py:44-58` writes the scheduled agenda **back out** to a
  Google Sheet a third-party mobile app reads, including `Prowadzący`
  (facilitator name) and a photo link.

Google appears nowhere in §4 or §5. This is both an undisclosed processor
and an undisclosed third-country transfer, and the Konwencik export is an
undisclosed onward disclosure to yet another party.

**Fix:** add Google to §4 (processor, on the organizer's instruction) and to
§5 (transfer safeguard). Describe the CFP import as a source of data — §2
currently implies every byte comes from the user's own registration.

### F3 — §2 lists a fraction of what is stored — High

§2.1 says the registration data is pseudonym, email, and an Auth0 id. §2.3
says activity data is signup history and logs. What the code stores:

| Stored | Where |
| --- | --- |
| Display name, **defaulted to the real name from the social login** | `models.py:106`; `crowd/auth.py:132-141,155` maps `name`/`given_name`+`family_name` into `User.name` |
| Profile picture URL from Google/Facebook via Auth0 | `models.py:128`; `crowd/auth.py:154,162` |
| Gravatar preference | `models.py:135` |
| Discord username | `models.py:122`, collected in `crowd/forms.py:26-31` |
| Companion ("child") accounts and single-use claim tokens | `models.py:143`, `CompanionForm` |
| Party membership and invite tokens | `models.py:227-273` |
| Shadowban lists — who a user blocked | `models.py:186-207` |
| Event bans with a free-text reason | `models.py:209` |
| Session bookmarks | `models.py:275` |
| In-app notifications with rendered copy and payload | `models.py:1344` |
| Facilitator records: display name, accreditation type, guild, contact organizer | `models.py:893-935` |
| **Arbitrary organizer-defined personal data** attached to a facilitator | `PersonalDataField*`, `models.py:1391-1507` |
| Change logs: who edited which field, old and new value | `models.py:1780,1844,1865` |
| Import log entries holding the imported row and the response | `models.py:2024` |
| RSVP IP addresses | `models.py:1692` — see F7 |

The real-name point is the sharpest one: both the policy (§2.1) and the
Regulamin (§2.1.3, "pseudonim — nie musi być prawdziwym imieniem i
nazwiskiem") present the account as pseudonymous, while a Google or Facebook
login silently fills `User.name` with the person's legal name and their
profile photo. That is not what a reader is told.

**Fix:** rewrite §2 against the table above. Say plainly that signing in with
a social provider imports the name and picture that provider holds, and that
the name can be changed afterwards in the profile.

### F4 — Organizers are invisible — High

The platform is multi-tenant: `Sphere` is a community site with its own
domain, its own managers, its own events. Sphere managers read participant
lists, read personal-data field answers, ban people, mint MCP tokens
(`docs/agents/mcp.md`, "Organizer tier"), and configure the integrations in
F1 and F2 that ship data to Google and to a shop.

The policy names one natural person as the sole administrator of the data and
never mentions organizers. Whoever is actually deciding the purposes for an
organizer-run event's data is either a separate controller, a joint controller
(art. 26), or a processor under an entrusting agreement (art. 28) — and the
policy has to say which, and users have to be told who holds their data.

**Fix:** this is a structural decision, not a wording one. Decide the model
first, then add a section describing it. If organizers are joint controllers,
art. 26(2) requires the essence of the arrangement to be made available to
data subjects.

### F5 — Gravatar receives hashed emails and viewer IPs — Medium-high

`links/gravatar.py:5-11` builds `https://www.gravatar.com/avatar/<sha256 of
the lowercased email>`. Whenever that URL is rendered, the **viewer's**
browser requests it, so Automattic (US) receives the viewer's IP, user agent,
referring page, and a stable hash identifying the account holder. A hashed
email is pseudonymised, not anonymous.

Not in §4, not in §5. The CSP comment at `edges/settings.py:441` acknowledges
avatars come from "arbitrary Auth0/gravatar HTTPS hosts".

**Fix:** disclose it, or proxy avatars server-side so the third party sees
the server rather than every visitor. The proxy is the better outcome and
removes the disclosure entirely.

### F6 — Retention promises nothing enforces — Medium-high

§6 promises technical logs for "maksymalnie 12 miesięcy" and account data
"do momentu usunięcia konta". In the repository there is **no purge job, no
cleanup task, no retention setting** — a search for scheduled deletion across
`inits/` and `mills/` returns nothing. Meanwhile:

- `SoftDeleteModel` (`models.py:66-84`) marks rows deleted with a timestamp
  and keeps them. `Facilitator`, `Session`, and `Discount` are soft-deleted.
  A user asking for erasure has no way to know their facilitator row is still
  in the table.
- Change logs are explicitly designed to outlive the thing they describe:
  "`deleted_at` records when and a restore erases even that, so the log is
  the only trace of who" (`mills/submissions/personal_data_fields.py:70-72`).
- Import log entries, notifications, and RSVP rows have no expiry at all.

**Fix:** either implement the retention the policy promises, or change the
policy to describe what the system does — including that soft-deleted records
and audit logs are kept, on what basis, and for how long. A promise the code
cannot keep is worse than a longer honest period.

### F7 — RSVP IPs kept forever for a 60-second check — Medium-high

`models.py:1692` stores an IP on every encounter RSVP. Its only use is
`mills/encounter.py:191` → `repositories/notice_board.py:132`, a
`recent_rsvp_exists(ip_address, seconds=60)` flood check. The row is never
deleted and the column is surfaced in Django admin (`admin.py:232`), joined
to the user.

Storing an identifier permanently to answer a question with a 60-second
window fails data minimisation (art. 5(1)(c)) and storage limitation
(art. 5(1)(e)) regardless of what the policy says.

**Fix (code):** keep a hash instead of the address, or null the column on a
short schedule, or move the rate limit to the cache layer and drop the column.
Whichever is chosen, add it to §2/§6.

### F8 — Email notifications are live, not "planowana" — Medium

§3.2 describes user communication as planned. `links/db/django/notifications.py:318`
calls `send_mail`, reached from eight notification kinds (`_deliver` callers at
`:78, :108, :134, :159, :183, :213, :245, :289`) covering waitlist promotions,
party invitations, and shadowban warnings. SMTP is wired in every environment
(`edges/settings.py:583-593`).

**Fix:** drop "(planowana)", describe the actual message types, and name the
SMTP provider in §4 — it is a processor that sees recipient addresses and
message bodies.

### F9 — Legal basis for the core service — Medium

§3.1 and §3.2 rest the signup service and its transactional email on
legitimate interest (art. 6(1)(f)). There is a Regulamin the user accepts
(`terms-of-service.md` §1.2.2), and the processing is what performs it, which
makes art. 6(1)(b) the natural basis. Legitimate interest also requires a
balancing test on file and gives users an art. 21 objection right that §7.6
then describes generically.

**Fix:** move §3.1 and the transactional half of §3.2 to art. 6(1)(b); keep
legitimate interest for security, abuse prevention, and fault reporting,
where it genuinely fits.

### F10 — Media may live in Google Cloud Storage — Medium

`edges/settings.py:44-47` accepts `GS_BUCKET_NAME`, `GS_CREDENTIALS_JSON`,
and `GS_LOCATION` to put uploads in a Google bucket, and the CSP comment at
`:441` says "media from GCS". Uploads include event and sphere logos, session
and encounter cover images, and venue map pages — user-supplied files, some of
which are photographs.

**Verify in production** whether GCS is enabled. If it is, Google belongs in
§4 and §5. Note also that nothing deletes an upload when its row goes away:
`repositories/storage.py:35` deletes the *replaced* file, and there is no
`post_delete` handler anywhere, so files orphaned by a deleted or soft-deleted
row stay in the bucket.

### F11 — Social login and provider avatars — Medium

The Regulamin (§2.1.2) says login goes through Auth0 "z możliwością logowania
przez Google, Facebook". The policy mentions only Auth0. Signing in tells the
chosen provider that the person uses this service, and the stored
`avatar_url` points at that provider's CDN, so rendering it discloses each
viewer's IP to Google or Facebook.

**Fix:** name the identity providers in §4 and cover the avatar fetch, or
proxy avatars alongside the Gravatar fix in F5.

### F12 — Publication is a disclosure — Medium

Participant lists render on session pages, facilitator names and bios render
in the programme, `PersonalDataField.is_public` (`models.py:1410`) lets an
organizer publish an answer to a personal-data question, and
`Encounter.is_public` (`models.py:1660`) publishes an encounter with its
creator. §4 lists only technical providers; being visible to other users and,
for public pages, to search engines is the disclosure users care about most.

**Fix:** add a subsection to §4 saying which data is visible to other
participants, which to organizers, and which to anyone on the internet.

### F13 — Event data reaches operators' AI agents — Medium

`/mcp/` and `/mcp/organizer/` (`gates/web/django/mcp/`) let a maintainer's or
an organizer's LLM client — Claude Code, Cursor, Executor, per
`docs/agents/mcp.md` — read and write platform data over the same services
the views use. `gates/mcp/programme_tools.py:233` lists an event's
facilitators by name; sphere-wide reads cover sibling events.

The application itself calls no model and stores no LLM credentials, and the
docs are explicit about that ("the app has no model and no LLM dependency").
But the data does leave through the operator's own agent to whichever model
provider that agent uses, and the policy says nothing about AI processing at
all.

**Fix:** a short §4 entry stating that authorized operators may use AI
assistants to administer the programme, which data such a tool can reach, and
that no automated decision about a user is taken that way. Pair it with an
operator rule: organizer tokens only with tools that do not train on the data.

### F14 — Missing mandatory art. 13 content — Medium

Absent from the policy:

- Whether providing the data is a contractual requirement and what happens if
  it is not provided (art. 13(2)(e)).
- Automated decision-making (art. 13(2)(f)). Two mechanisms qualify for at
  least a mention: waitlist auto-promotion when a seat frees up, and the
  membership-count lookup in F1 setting `allowed_slots`
  (`mills/enrollment.py:617-623`) — a third party's answer automatically
  decides how much of the service someone gets.
- Per-category retention periods (art. 13(2)(a)) — see F6.
- That withdrawing analytics consent does not affect processing already
  carried out (art. 13(2)(c)); §3.4 says consent can be withdrawn but not this.

### F15 — Cookies section — Low-medium

§9 describes three cookie categories and names none of them. PostHog persists
to `localStorage` as well as cookies (`client/src/prologue.ts:205,227`), and
the consent decision itself is a `localStorage` key (`STORAGE_KEY`), not a
cookie — the banner copy already flags this tension in a comment
(`templates/components/consent-banner.html:8-11`). Polish practice under the
Prawo telekomunikacyjne treats terminal-device storage the same way whatever
its technical form.

**Fix:** a small table — name, purpose, lifetime, first/third party —
covering `sessionid`, `csrftoken`, the PostHog `ph_*` pair, and the
`localStorage` entries.

### F16 — Third-country transfers — Low-medium

§5 names Auth0 and says transfers happen "na podstawie odpowiednich
zabezpieczeń" without naming the mechanism. With F2, F5, and F10 added,
Google and Automattic belong here too.

**Fix:** name the actual safeguard per recipient — Data Privacy Framework
certification or standard contractual clauses — and say where a copy can be
requested. PostHog is EU-hosted (`eu.i.posthog.com`) and stays out of §5,
which is worth stating explicitly since the company is US-based.

### F17 — Controller identification — Low

§1 and §14 give an email address and no postal address. Art. 13(1)(a) wants
the controller's identity and contact details; for a natural person running a
service, a correspondence address is the expected form.

Separately, the site's own "Contact" link renders `SUPPORT_EMAIL`
(`templates/base.html:163`, `edges/settings.py:83`), which is env-configured
and may not be the address the policy names. **Verify in production** that the
two agree, or the RODO requests will arrive at an inbox that is not watching
for them.

## What holds up

Worth recording, because these were checked and are genuinely fine:

- **Analytics consent gating matches §3.4.** PostHog initialises only after
  an explicit accept (`prologue.ts:251`); declining calls
  `stopSessionRecording`, drops the identity, then opts out, in that order and
  for a documented reason (`:235-242`). Session recording sets
  `maskAllInputs: true` and holds social meta out of the snapshot
  (`:206-217`), which is what "zamaskowana zawartość wszystkich pól
  formularzy" claims.
- **Server fault reports match §3.5.** `links/analytics/reporting.py` sends
  the exception, a redacted path, the environment, and the user pk, with
  `$process_person_profile: False` and `disable_geoip: True`, and the
  reasoning for sending them without consent is written down in the code.
  `docs/analytics.md` records the middleware that was deliberately *not*
  installed because it would have attached emails and IPs.
- **No LLM in the request path.** No provider SDK is imported anywhere in
  `src/`; the MCP server is a transport (see F13 for the residual exposure).
- **Uploaded files get uuid names with an extension allowlist**
  (`links/db/django/uploads.py`), so a filename cannot smuggle a content type.
- **Integration secrets are encrypted at rest** and write-only at the
  repository surface (`models.py:1891-1893`).
- **No payment data anywhere.** `Discount` records an amount for an
  organizer's own accounting; no card, no payment provider, no PSP.
- **Age handling is coherent.** The 16+ rule in §11.1 matches the Regulamin
  §2.2, and the claim that no birth date is collected is true — no model
  stores one.

## Reading the ten-item checklist against this codebase

The prompt for this audit was a list of ten ways a vibe-coded app gets sued.
Where this repository stands:

| # | Item | Status |
| --- | --- | --- |
| 1 | No privacy policy | Has one, linked in the footer and from the consent banner |
| 2 | No "we collect user data" | §2 exists but is materially incomplete — F3 |
| 3 | No mention of AI in the policy | Gap, though narrow — F13 |
| 4 | No mention of third-party data collectors | The main gap — F1, F2, F5, F10, F11 |
| 5 | Not deleting user uploads | Orphaned files stay in storage — F10 |
| 6 | Public storage bucket | Media is public by design (event covers, logos); no user-private files exist, so this is a non-issue here. Verify the bucket has no listing enabled |
| 7 | Fake testimonials | None on the site |
| 8 | Cancelling harder than signing up | Signup and cancellation are both one action (Regulamin §3.2); account deletion is email-only, which is worth improving but is not the pattern being described — F6 |
| 9 | Auto-renew without reminder | No subscriptions, no payments |
| 10 | AI with no self-harm response | No user-facing AI |

## Proposed policy text

Ready-to-paste Polish replacements for the highest-severity gaps. They assume
the facts above; adjust once F4 (organizer role) is decided, since it changes
how §1 and §4 are phrased.

### §2.1 — replace

```markdown
### 2.1 Dane konta:

- Nazwa wyświetlana (może być pseudonimem; przy logowaniu przez Google lub
  Facebook wypełniamy ją imieniem i nazwiskiem z tego konta, a użytkownik
  może ją później zmienić w profilu)
- Adres email
- Unikalny identyfikator z systemu Auth0
- Adres zdjęcia profilowego pobrany od dostawcy logowania oraz wybór, czy
  zamiast niego pokazywać Gravatar
- Nazwa użytkownika na Discordzie (opcjonalnie)
- Nazwy wyświetlane osób dodanych do konta jako podopieczni
```

### §2.4 — add

```markdown
### 2.4 Dane związane z udziałem w wydarzeniach:

- Zapisy, lista rezerwowa, zapisane punkty programu i przynależność do drużyn
- Dane twórców programu: nazwa wyświetlana, rodzaj akredytacji, przynależność
  do grupy oraz odpowiedzi na pytania o dane osobowe skonfigurowane przez
  organizatora danego wydarzenia (zakres tych pytań ustala organizator)
- Blokady użytkowników („shadowban") i blokady udziału w wydarzeniu wraz z
  powodem
- Historia zmian wprowadzanych w panelu organizatora oraz logi importu
  programu
- Powiadomienia wysłane w serwisie i pocztą elektroniczną
```

### §4 — replace the provider list

```markdown
### 4.1 Dostawcy usług technicznych:

- **OVH SAS** (Francja) — hosting
- **Auth0 / Okta** (USA, Unia Europejska) — uwierzytelnianie. Logowanie przez Google lub
  Facebook oznacza, że wybrany dostawca dowiaduje się o korzystaniu z serwisu
- **Dostawca poczty wychodzącej** — powiadomienia email; widzi adres odbiorcy
  i treść wiadomości
- **Google Cloud Storage** (Google Ireland/LLC) — przechowywanie plików
  przesłanych do serwisu

### 4.2 Dostawcy analityki:

- **PostHog** — dane trafiają na serwery w Unii Europejskiej
  (`eu.i.posthog.com`). Dane z punktu 3.4 przekazujemy wyłącznie za zgodą;
  zgłoszenia błędów serwera z punktu 3.5 wysyłamy niezależnie od zgody

### 4.3 Usługi wykorzystywane przez organizatorów wydarzeń:

- **Google (Sheets, Forms)** — organizator może zaimportować zgłoszenia
  programu z arkusza lub formularza Google i wyeksportować harmonogram do
  arkusza czytanego przez zewnętrzną aplikację z programem wydarzenia.
  Eksportowany harmonogram zawiera nazwy twórców programu
- **Sklep z biletami** — przy zapisach na wydarzenie, w którym liczba miejsc
  zależy od posiadanego biletu lub członkostwa, wysyłamy do sklepu adres email
  użytkownika i otrzymujemy w odpowiedzi liczbę posiadanych uprawnień
- **Gravatar (Automattic, USA)** — jeżeli użytkownik wybierze awatar z
  Gravatara, przeglądarki osób oglądających profil pobierają obrazek z
  serwerów Gravatara; trafia tam skrót adresu email oraz adres IP osoby
  oglądającej

### 4.4 Inni użytkownicy i dostęp publiczny:

- Nazwa wyświetlana i zapisy są widoczne dla innych uczestników wydarzenia
- Organizatorzy wydarzenia widzą listy uczestników oraz odpowiedzi na pytania
  o dane osobowe skonfigurowane w danym wydarzeniu
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

### §3.1 — replace the basis

```markdown
- **Podstawa prawna:** niezbędność do wykonania umowy (art. 6 ust. 1 lit. b
  RODO) — umową jest Regulamin akceptowany przy korzystaniu z serwisu
```

### §6 — replace

```markdown
Dane osobowe przechowujemy:

- **Dane konta:** do momentu usunięcia konta przez użytkownika lub na jego
  żądanie
- **Historia zapisów:** do momentu usunięcia konta
- **Logi techniczne:** maksymalnie 12 miesięcy
- **Historia zmian w panelu organizatora i logi importu programu:** przez czas
  trwania wydarzenia i 12 miesięcy po jego zakończeniu; są to zapisy tego, kto
  wprowadził zmianę, i pozostają także po usunięciu opisywanego wpisu
- **Dane analityczne i zgłoszenia błędów:** zgodnie z polityką narzędzia
  analitycznego wskazanego w punkcie 4.2
```

### §13a — add before "Zmiany polityki"

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

## Recommended code changes

Separate from the policy text, ordered by how much they reduce exposure:

1. **Purge or hash `EncounterRSVP.ip_address`** (F7). The cheapest real
   privacy win in the codebase — the column serves a 60-second check and is
   kept forever.
2. **Proxy avatars** (F5, F11). One view that fetches and caches the remote
   image removes two third-party disclosures and the CSP's `img-src https:`
   wildcard at the same time.
3. **Delete stored files when their row goes** (F10), including on soft
   delete, or record why they are kept.
4. **Implement the 12-month log retention** the policy already promises (F6),
   or change the promise.
5. **Verify `SUPPORT_EMAIL` matches the policy's contact address** (F17).

## Suggested next step

F4 (the organizer/controller question) blocks the final wording of §1 and §4
and is the one finding an engineer cannot settle alone. Everything else in
"Proposed policy text" can be applied as written.
