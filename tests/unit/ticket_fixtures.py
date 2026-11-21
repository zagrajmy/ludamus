"""The ticket services over the fakes of `tests.unit.ticket_fakes`, as fixtures.

A test module takes them with `pytest_plugins = ("tests.unit.ticket_fixtures",)`
and never imports this module: pytest must load it first to rewrite it.
"""

import pytest

from ludamus.mills.tickets import PayoutService, TicketPanelService, TicketSalesService
from ludamus.pacts.tickets import TicketRepos
from tests.unit.factories import FakeTransaction
from tests.unit.ticket_fakes import (
    FakeAccounts,
    FakeClaimCodec,
    FakeMailer,
    FakeOrders,
    FakePlans,
    FakeTicketPayments,
    FakeTicketTypes,
    FakeUsers,
    TicketBook,
)


@pytest.fixture(name="book")
def book_fixture():
    return TicketBook()


@pytest.fixture(name="types")
def types_fixture(book):
    return FakeTicketTypes(book)


@pytest.fixture(name="orders")
def orders_fixture(book):
    return FakeOrders(book)


@pytest.fixture(name="accounts")
def accounts_fixture():
    return FakeAccounts()


@pytest.fixture(name="payments")
def payments_fixture():
    return FakeTicketPayments()


@pytest.fixture(name="plans")
def plans_fixture():
    return FakePlans()


@pytest.fixture(name="mailer")
def mailer_fixture():
    return FakeMailer()


@pytest.fixture(name="claims")
def claims_fixture():
    return FakeClaimCodec()


@pytest.fixture(name="users")
def users_fixture():
    return FakeUsers()


@pytest.fixture(name="repos")
def repos_fixture(types, orders, accounts, plans, users):
    return TicketRepos(
        ticket_types=types, orders=orders, accounts=accounts, plans=plans, users=users
    )


@pytest.fixture(name="payout")
def payout_fixture(accounts, payments):
    return PayoutService(
        transaction=FakeTransaction(), accounts=accounts, payments=payments
    )


@pytest.fixture(name="sales")
def sales_fixture(repos, payments, mailer, claims):
    return TicketSalesService(
        transaction=FakeTransaction(),
        repos=repos,
        payments=payments,
        mailer=mailer,
        claims=claims,
    )


@pytest.fixture(name="panel")
def panel_fixture(repos, payments):
    return TicketPanelService(
        transaction=FakeTransaction(), repos=repos, payments=payments
    )
