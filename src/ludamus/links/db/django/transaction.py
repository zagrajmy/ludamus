from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from django.db import DataError, IntegrityError, transaction

from ludamus.pacts.services import DatabaseConstraintError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager


class DjangoTransaction:
    # atomic()/savepoint() over Django's transaction API. Shared by the unit of
    # work (request.di.uow) and the services layer's TransactionProtocol impl so
    # both open savepoints the same way.

    @staticmethod
    def atomic() -> AbstractContextManager[None]:
        return transaction.atomic()

    @staticmethod
    @contextmanager
    def savepoint() -> Iterator[None]:
        # A nested savepoint: a constraint/data violation rolls back only this
        # block and is re-raised as DatabaseConstraintError, leaving the
        # surrounding transaction usable so the caller can record the failure.
        try:
            with transaction.atomic():
                yield
        except (IntegrityError, DataError) as exc:
            raise DatabaseConstraintError(str(exc)) from exc
