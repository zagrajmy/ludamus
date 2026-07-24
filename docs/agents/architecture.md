# Architecture

## Layers

| Layer | Location | Purpose |
| ----- | -------- | ------- |
| pacts | `pacts.py` | Protocols, DTOs (Pydantic), errors, enums, TypedDicts |
| specs | `specs/{noun}.py` | Business invariants — pure constants, no IO |
| mills | `mills.py` | Business logic, Django-free |
| links | `links/` | Repositories, UoW, external clients |
| gates | `gates/` | Views, forms, URLs, templatetags |
| inits | `inits.py` | DI container, middleware wiring |
| edges | `edges/` | settings, wsgi/asgi — outside GLIMPSE |
| adapters | `adapters/` | Legacy — new code goes into GLIMPSE layers |

## Import Rules

Enforced by `importlinter`:

```text
General flow (Y can import X):
pacts -> mills -> links -> gates -> inits

specs sits at the bottom alongside pacts, consumed only by mills:
pacts -> specs -> mills

Forbidden:
mills   ✗ gates, links, inits, edges, django
links   ✗ gates, mills, inits, specs, edges
gates   ✗ links, inits, specs, edges
inits   ✗ edges
specs   ✗ gates, links, inits, mills, edges, django
pacts   ✗ gates, links, inits, mills, specs, edges, django
```

## Repository Pattern

```python
# links/db/django/repositories.py
class ProposalRepository(ProposalRepositoryProtocol):
    def read(self, pk: int) -> ProposalDTO:
        try:
            proposal = Proposal.objects.select_related("category").get(id=pk)
        except Proposal.DoesNotExist as exception:
            raise NotFoundError from exception
        return ProposalDTO.model_validate(proposal)
```

## Links Layout

`links` slices by **kind**, not by entity. The kinds — and the split
philosophy — are per-adapter; what follows is the shape for `db/django`.
Other adapters (`payment_api/stripe`, `gravatar`, `ticket_api`) split
differently or stay single-file.

```text
# Small (default)
links/db/django/
    __init__.py             # facade — public surface
    models.py               # ORM models — internal to links
    repositories.py         # repository implementations — public via the facade

# Promoted when a kind crosses ~1000 lines
links/db/django/
    __init__.py             # facade — unchanged public import path
    models/
        __init__.py         # re-exports model classes (required for Django app-loading)
        part1.py
        part2.py
    repositories/
        __init__.py         # may be empty; the facade is one level up
        part1.py
        part2.py
```

Models are internal to `links`; the public face is the repository classes,
exposed through the package facade and consumed via the protocols declared
in `pacts`. External code imports as:

```python
from ludamus.links.db.django import SessionRepository
```

and never reaches `models`.

**Splitting rules.** Baseline across adapters: halve, don't shard, and
arrange parts so they don't cause circular imports. For `db/django`,
models tend to halve along FK dependency or aggregate boundaries;
repositories halve by aggregate group. A per-entity submodule
(`repositories/agenda_item.py`) is an escape hatch when one entity's repo
genuinely dwarfs the rest, not the default.

## Repository Registry

Repositories are wired into a flat registry, internal to `inits/`, never
imported from gates:

```python
# inits/repositories.py
class Repositories:
    @cached_property
    def personal_data_fields(self) -> PersonalDataFieldRepository:
        return PersonalDataFieldRepository()

    @cached_property
    def proposal_categories(self) -> ProposalCategoryRepository:
        return ProposalCategoryRepository()
```

Buckets appear when the leaf count grows past ~12. Until then, stay flat.

## Services (mills)

Services take a `TransactionProtocol` plus the specific repo protocols they
actually touch — never the full UoW, never imports of concrete repos:

```python
# mills/chronology.py
class CFPPersonalDataFieldService:
    def __init__(
        self,
        transaction: TransactionProtocol,
        fields: PersonalDataFieldRepositoryProtocol,
        categories: ProposalCategoryRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._fields = fields
        self._categories = categories

    def create(self, event_pk: int, data, requirements) -> PersonalDataFieldDTO:
        with self._transaction.atomic():
            field = self._fields.create(event_pk, data)
            if requirements:
                self._categories.add_field_to_categories(field.pk, requirements)
        return field
```

Services own transactions (`transaction.atomic()`); views never start them.
Services return DTOs; views render them.

### Mills layout

`mills/{noun}.py` is promoted to a package when it crosses ~1000
lines. Modules slice **by service** — one view-facing service per module,
named after its area (`mills/submissions/importing.py`, `import_log.py`,
`field_layout.py`, `personal_data_fields.py`). A service holds the methods
used together in the same views; a method that landed somewhere only
because it matched the service name, or had no other service to go to,
gets its own service.

Shared code splits by kind:

- **Pure functions** go to a plain-function module
  (`mills/submissions/mapping.py` — row-cell parsing, slug generation).
- **Repo-bearing machinery** becomes a collaborator class
  (`mills/submissions/engine.py` — `ImportEngine`) that services compose
  internally. It is not a service: no protocol in `ServicesProtocol`,
  never exposed on `request.services`, and it owns no transactions —
  services open `atomic()` and call engine methods inside it.

`pacts/{noun}.py` stays a single module; each service gets its own
protocol there (`ProposalImportServiceProtocol`, `ImportLogServiceProtocol`,
`ImportFieldLayoutServiceProtocol`).

## Services Tree

Services are exposed to gates through a flat namespace at
`request.services.<service_name>`:

```python
# inits/services.py
class Services:
    @cached_property
    def personal_data_fields(self) -> CFPPersonalDataFieldService:
        return CFPPersonalDataFieldService(
            self._transaction,
            self._repos.personal_data_fields,
            self._repos.proposal_categories,
        )
```

The `ServicesProtocol` in `pacts/services.py` describes the navigation
shape. `ServiceInjectionMiddleware` attaches `request.services` per request.

## Views

Views are glue: parse forms, call services, render DTOs. They never reach
into repos or build services themselves. Type-hint request as
`RootRequestProtocol` (or a narrower request like `PanelRequest`):

```python
def get(self, request: PanelRequest, slug: str) -> TemplateResponse:
    service = request.services.personal_data_fields
    fields = service.list_summaries(event_pk)
    return TemplateResponse(
        request, "panel/personal-data-fields.html", {"fields": fields}
    )
```

## Strangler-fig migration

Two middleware run in parallel: the legacy `RepositoryInjectionMiddleware`
(attaches `request.di.uow`) and the new `ServiceInjectionMiddleware`
(attaches `request.services`). New code uses `request.services`. A single
view file picks one shape; never both in the same view.

Migration is per view file. The recipe lives in
[services-migration.md](services-migration.md). Once the last view migrates,
`RepositoryInjectionMiddleware` and `request.di.uow` are removed.

New code must use `request.services`. Do not extend the `request.di.uow`
surface — write a new mills service instead.

## Specs

Business invariants consumed only by mills. No IO, no Django.
Sliced by noun, mirroring pacts and mills:

```python
# specs/event.py
MAX_SESSIONS_PER_USER = 5
```

Pacts can define the structure; specs provide the values:

```python
# pacts/event.py
class SessionLimits(TypedDict):
    max_per_user: int

# specs/event.py
SESSION_LIMITS: SessionLimits = {"max_per_user": 5}
```

---

## Nouns

Slice by **noun**, cut by **verb**; gates slice by **page**. A noun is a
fat data cow: the model cluster everything else hangs off. A verb is an
activity (`enroll`, `propose`, `schedule`, `present`) — its modules hold
the records and logic of actions, not first-class data. No catch-all
verbs (`manage`, `organize`): a cut must name a real activity — if you
can't name one, the file isn't too big yet. Gates mirror the sitemap
(a page or page group plus its action views); mills mirror the domain.

The old **subdomain** / **bounded context** vocabulary is banned.
Some directory, URL, template, and test paths still carry the legacy subdomain
names; they are renamed opportunistically, tracked by the
`old-subdomain-loc` tingle metric. New code slices by noun.

| Legacy subdomain | Noun | Scope |
| ---------------- | ---- | ----- |
| Chronology | event | Scheduling, venues, enrollment, public event pages |
| Submissions | event | Proposal intake: CFP config, curation, `Session` lifecycle |
| Crowd | user | Authentication, profiles, delegate accounts |
| Multiverse | sphere | Sphere and concepts depending only on Sphere |
| Notice Board | encounter | Informal gatherings decoupled from events |
| — (RFC 0001) | party | The drużyna: the group that enrolls together |

---

### event

The fattest noun — legacy `chronology` and `submissions` both map here,
which dissolves the old ownership split: proposal intake writes `Session`,
scheduling and enrollment read it, all inside one noun. Verb cuts as it
grows: `propose` (CFP config, proposals, facilitators), `enroll`,
`schedule` (venues, time slots, tracks, timetable), `present` (public
pages, printing).

Enrollment behaviour currently bolted onto the `Session` model
(`enrolled_count`, `is_full`, `effective_participants_limit`,
`is_enrollment_available`, `SessionManager.has_conflicts`) belongs in
`enroll` mills/specs, not on the model.

#### Pages: Public event pages

What visitors see: event details, session list, session cards.

- **URLs:** `/chronology/event/<slug>/` (namespace `chronology`)
- **Views:** `adapters/web/django/views.py` — `EventPageView`
- **Templates:** `templates/chronology/event.html`,
  `_session_card.html`, `session_tags.html`
- **DTOs:** `EventDTO`, `SessionDTO`, `SessionListItemDTO`, `TrackDTO`

#### Pages: Proposal wizard

The multi-step wizard through which facilitators submit session proposals.

- **URLs:** `/chronology/session/propose/` (namespace `session`)
- **Views:** `gates/web/django/chronology/views.py` —
  `ProposeSessionPageView` and component views for each wizard step
  (category, personal data, time slots, session details, review, submit)
- **Templates:** `templates/chronology/propose/`
- **Service:** `ProposeSessionService` — resolves field requirements per
  category, creates `Facilitator`, persists `Session` and field values,
  rate-limits by IP
- **DTOs:** `ProposalCategoryDTO`, `SessionFieldRequirementDTO`,
  `PersonalFieldRequirementDTO`, `TimeSlotRequirementDTO`,
  `FacilitatorDTO`, `SessionData`

#### Pages: Enrollment

Session sign-ups for authenticated users and anonymous attendees;
proposal acceptance by organizers.

- **URLs:** `/chronology/session/<id>/enrollment/`,
  `/chronology/session/<id>/accept/`, `/chronology/anonymous/`
- **Views:** `adapters/web/django/views.py` — `SessionEnrollPageView`,
  `SessionEnrollmentAnonymousPageView`, `ProposalAcceptPageView`,
  `EventAnonymousActivateActionView`, `AnonymousLoadActionView`,
  `AnonymousResetActionView`
- **Templates:** `templates/chronology/enroll_select.html`,
  `anonymous_enroll.html`, `anonymous_manage.html`, `accept_proposal.html`
- **Services:** `AcceptProposalService` (transitions session → ACCEPTED,
  creates `AgendaItem`), `AnonymousEnrollmentService` (code-based
  anonymous user lookup)
- **DTOs:** `EnrollmentConfigDTO`, `UserEnrollmentConfigDTO`,
  `VirtualEnrollmentConfig`, `AgendaItemDTO`

#### Pages: Panel (event-scoped)

The organiser backoffice: event configuration, scheduling, venues,
enrollment administration, intake configuration, and curation — one page
group, no ownership split.

- **URLs:** `/panel/event/<slug>/…` (namespace `panel`), configured in
  `gates/web/django/event/panel/urls.py`
- **Views:** new pages live in `gates/web/django/event/panel/views/`; remaining
  pages under `gates/web/django/chronology/panel/views/` move there
  opportunistically. Each module owns one page or closely related page group.
- **Templates:** `templates/panel/`
- **Services:** `EventPanelService` loads the shared event-scoped navigation
  context through repository protocols; focused page services own page reads and
  writes. Legacy pages still use `PanelService` for cascade-safe deletion and
  time-slot validation until they migrate.

<!-- markdownlint-disable MD013 -->

| Area | Views | Templates |
| ---- | ----- | --------- |
| Proposal categories | `panel/views/cfp.py` | `cfp-*.html` |
| Proposals / sessions | `panel/views/proposals.py` | `proposal-*.html` |
| Personal data fields | `panel/views/personal_data_fields.py` | `personal-data-field-*.html` |
| Session fields | `panel/views/session_fields.py` | `session-field-*.html` |
| Facilitators | `panel/views/facilitators.py` | `facilitator-*.html` |
| Event settings | `chronology/panel/views/event_settings.py` | `settings.html` |
| Enrollment settings | `event/panel/views/enrollment_settings.py` | `enrollment-*.html` |
| Time slots | `panel/views/time_slots.py` | `time-slot*.html` |
| Tracks | `panel/views/tracks.py` | `track-*.html` |
| Venues (Space tree) | `panel/views/venues.py` | `spaces.html`, `_space_tree_node.html`, `space-*.html` |

<!-- markdownlint-enable MD013 -->

---

### sphere

Legacy name: `multiverse`. Sphere-scoped configuration shared across the
events that live under a sphere. Holds `Sphere` itself plus anything that
depends only on Sphere (no Event coupling).

#### Pages: Panel (sphere-scoped)

Sphere-scoped backoffice for sphere managers. Parallel to the event panel
and uses its own access mixin keyed off `current_sphere_id` without an
`EventContextMixin`.

- **URLs:** `/multiverse/sphere/<slug>/…` (namespace `multiverse:panel`)
- **Views:** `gates/web/django/multiverse/panel/views/…`
- **Templates:** `templates/multiverse/panel/`
- **Pacts/Mills/Specs:** `pacts/multiverse.py`, `mills/multiverse.py`
  (legacy module names; new cuts use `sphere`)
- **Access:** `SphereAccessMixin` (sphere-manager check via
  `request.di.uow.spheres.is_manager`)
- **First feature:** sphere-scoped import-connections CRUD
  ("Połączenia importu" subpage)

`Sphere` ORM models and repositories continue to live in
`links/db/django/models.py` and `links/db/django/repositories.py` per the
split-when-big rule; they are not moved into a sphere-named file.

---

### encounter

Legacy name: `notice_board`. Informal social gathering system, decoupled
from the formal event/session lifecycle.

#### Pages: Encounters

Users create one-off encounters (game sessions, meetups) and others RSVP
to join them. Includes the public share page, RSVP actions, and calendar
exports.

- **URLs:** `/encounters/` (authenticated), `/e/<share_code>/` (public,
  namespace `notice-board`)
- **Views:** `gates/web/django/notice_board/views.py` —
  `EncountersIndexPageView`, `EncounterCreatePageView`,
  `EncounterEditPageView`, `EncounterDeleteActionView`,
  `EncounterDetailPageView`, `EncounterRSVPActionView`,
  `EncounterCancelRSVPActionView`, `EncounterQrView`, `EncounterIcsView`
- **Templates:** `templates/notice_board/`
- **Service:** `EncounterService` — `build_detail()` (encounter + RSVPs +
  computed availability), `build_index()` (upcoming/past split, own vs
  RSVP'd)
- **DTOs:** `EncounterDTO`, `EncounterRSVPDTO`, `EncounterDetailResult`,
  `EncounterIndexItem`, `EncounterIndexResult`, `EncounterData`
- **Repositories:** `EncounterRepository`, `EncounterRSVPRepository`
- **External integrations:** Google Calendar and Outlook deep links,
  iCalendar `.ics` export, QR code generation

---

### user

Legacy name: `crowd`. Authentication, user profiles, and delegate
accounts.

#### Pages: Auth

Auth0 OAuth login/logout. State token management and JWT validation;
user upsert on callback.

- **URLs:** `/crowd/auth0/` (namespace `auth0`)
- **Views:** `gates/web/django/crowd/auth.py` — `Auth0LoginActionView`,
  `Auth0LoginCallbackActionView`, `Auth0LogoutActionView`,
  `Auth0LogoutRedirectActionView`, `LoginRequiredPageView`
- **Templates:** `templates/crowd/login_required.html`
- **Service:** `CrowdAuthService` (`request.services.crowd_auth`) — user
  provisioning on callback, identity sync, sphere-domain checks
- **External integration:** Auth0 PKCE/state OAuth flow

#### Pages: Profile

User profile management and delegate (connected) accounts.

- **URLs:** `/crowd/profile/`, `/crowd/profile/connected-users/` and
  `/crowd/claim/<token>/`
- **Views:** `gates/web/django/crowd/profile.py` — `ProfilePageView`,
  `ProfileAvatarPageView`, `ProfileShadowbanPageView`,
  `ProfileConnectedUsersPageView`,
  `ProfileConnectedUserUpdateActionView`,
  `ProfileConnectedUserDeleteActionView`,
  `ProfileConnectedUserClaimLinkActionView`, `ClaimPageView`
- **Templates:** `templates/crowd/user/edit.html`, `avatar.html`,
  `parties.html`, `shadowbans.html`, `crowd/claim.html`
- **Services:** `ProfileService` (self-profile reads/updates, avatar,
  confirmed-participation count), `CompanionsService` (connected-user
  CRUD), `ClaimService` (issue/redeem claim links), `ShadowbanService`
- **DTOs:** `UserDTO`, `ConnectedUserDTO`, `AvatarPageDTO`, `UserData`,
  `UserType` (`ACTIVE` / `CONNECTED` / `ANONYMOUS`)
- **Repositories:** `UserRepository`, `ConnectedUserRepository`,
  `ProfileStatsRepository`
- **External integration:** `MembershipApiClient` (`links/ticket_api.py`)
  — fetches enrollment quotas; Gravatar (`links/gravatar.py`) —
  email-hash avatar

---

### party

The drużyna: the group that enrolls together. Party CRUD, membership
invites, consent, and the companion (login-less member) lifecycle. See
RFC 0001. Already noun-named: `pacts/party.py`, `mills/party.py`,
`links/db/django/party.py`.

---

## Noun → Models

ORM models — in `links/db/django/models.py` — mapped to the noun that
owns them.

<!-- markdownlint-disable MD013 -->

| Noun | Models |
| ---- | ------ |
| user | `User` |
| sphere | `Sphere`, `Connection` |
| encounter | `Encounter`, `EncounterRSVP` |
| party | `Party`, `PartyMembership` |
| event | `Event`, `EventSettings`, `EventProposalSettings`, `Session`, `ProposalCategory`, `Facilitator`, `PersonalDataField`, `PersonalDataFieldOption`, `PersonalDataFieldRequirement`, `PersonalDataFieldValue`, `SessionField`, `SessionFieldOption`, `SessionFieldRequirement`, `SessionFieldValue`, `TimeSlotRequirement`, `Venue`, `Area`, `Space`, `TimeSlot`, `Track`, `AgendaItem`, `ScheduleChangeLog`, `EnrollmentConfig`, `UserEnrollmentConfig`, `DomainEnrollmentConfig`, `SessionParticipation` |

<!-- markdownlint-enable MD013 -->

Notes:

- The old Submissions/Chronology ownership split over `Session` is gone —
  proposal intake writes it, scheduling and enrollment read it, all
  inside the event noun. The remaining debt is the enrollment behaviour
  still living on the `Session` model (see the event section).
- `Tag` / `TagCategory` are slated for deletion and are intentionally
  absent from this mapping.
