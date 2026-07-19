# Services migration: per-file recipe

How to move one view file from the legacy `request.di.uow.<repo>` shape to
the new `request.services.<service_name>` shape. Each file is its own PR.

## Recipe

1. **Define the service protocol** in `pacts/<noun>.py`. Include any
   read DTOs the service returns (e.g. form-context aggregates that bundle
   what a template needs). Add a `@property` for the service to
   `ServicesProtocol` in `pacts/services.py`.

2. **Implement the service** in `mills/<noun>.py`. The constructor
   takes a `TransactionProtocol` plus the specific repo protocols the
   service touches — never the full UoW. Methods return DTOs (not models,
   not raw dicts). Multi-repo writes happen inside
   `with self._transaction.atomic():`.

3. **Wire repos** in `inits/repositories.py`. Add a `@cached_property` for
   any repository that doesn't already exist there. Stay flat until the
   leaf count crosses ~12.

4. **Wire the service** in `inits/services.py` as a `@cached_property` on
   `Services`. Pass the transaction adapter and the specific repos from
   the registry. Stay flat.

5. **Rewrite the view**. Replace every `request.di.uow.<repo>` call with
   `request.services.<service_name>.<method>(...)`. The view should shrink
   to glue: parse forms, dispatch to the service, render the returned DTO,
   handle redirects and flash messages. No `with uow.atomic()` blocks in
   the view — transactions belong to the service.

6. **Add unit tests** for the service. Mock the specific repo protocols
   and `TransactionProtocol` directly — never `MagicMock()` of UoW. The
   pattern is at `tests/unit/test_mills.py:60-75`. Existing integration
   tests for the view are the regression guard for end-to-end behavior.

## Boundaries

**View keeps:** request parsing (POST data, query strings), Django form
construction and validation, redirect/messages, template selection, HTTP
response wrapping. Anything that needs `request`, `HttpResponse`, or a
template name.

**Service owns:** the transaction, cross-repo writes, business invariants,
DTO assembly for templates (e.g. `*FormContextDTO` aggregates that bundle
all the reads a form needs). Anything Django-free that the integration
tests assert end-to-end.

**Crosses the seam:** the view passes parsed primitives (ints, strings,
TypedDicts of form data) into service methods; the service returns DTOs.
Models and ORM objects never cross. `NotFoundError` (from `pacts`) crosses
when the view needs distinct messaging on missing entities.

## Reference implementation

The `personal_data_fields` family is the canonical example to copy.

- **service:** `src/ludamus/mills/chronology.py` — `CFPPersonalDataFieldService`
  (constructor signature, transaction usage, DTO assembly)
- **protocol + DTOs:** `src/ludamus/pacts/chronology.py` —
  `CFPPersonalDataFieldServiceProtocol`, `PersonalDataFieldFormContextDTO`,
  `PersonalDataFieldEditContextDTO`
- **navigation protocol:** `src/ludamus/pacts/services.py` —
  `ServicesProtocol`, `TransactionProtocol`
- **wiring:** `src/ludamus/inits/services.py`,
  `src/ludamus/inits/repositories.py`,
  `src/ludamus/inits/transaction.py`,
  `src/ludamus/inits/middleware.py`
- **view:** `src/ludamus/gates/web/django/chronology/panel/views/personal_data_fields.py`
- **tests:** `tests/unit/test_mills.py` — `TestCFPPersonalDataFieldService`

## What never crosses the migration

- `inits/legacy.py`, `RepositoryInjectionMiddleware`, and `request.di.uow`
  stay until the last view migrates. Don't slim them piecewise.
- A single view file uses one shape, never both. If the migration is too
  large for one PR, split the view file along method boundaries first,
  then migrate one half.
- Don't promote a bare repository to `request.services`. Repositories
  stay on `request.di.uow` until they're being wrapped by an orchestrating
  service that earns its place on the services tree.
