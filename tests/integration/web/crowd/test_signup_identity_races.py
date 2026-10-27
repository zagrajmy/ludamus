from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier, Event
from time import monotonic

import pytest
from django.contrib.auth.hashers import make_password
from django.db import connection, transaction

from ludamus.inits.services import Services
from ludamus.links.db.django.models import SphereSubscription, User
from ludamus.pacts.crowd import AgeBand, UserType
from tests.integration.conftest import UserFactory


def _complete(claim_token):
    return Services().crowd_auth.provision_user(
        username="auth0|racing",
        create_data={
            "username": "auth0|racing",
            "slug": "racing",
            "password": make_password(None),
            "age_band": AgeBand.SIXTEEN_PLUS,
            "email": "child@example.com",
            "name": "Child",
            "avatar_url": "https://pic.test/child",
        },
        claim_token=claim_token,
    )


def _reject():
    Services().crowd_auth.reject_signup(
        username="auth0|racing", slug="racing", password=make_password(None)
    )


def _contend(*, reject_first, claim_token, barrier, pids):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            pids.put(cursor.fetchone()[0])
        barrier.wait(timeout=10)
        return _complete(claim_token) if reject_first else _reject()
    finally:
        connection.close()


def _wait_for_blocked_identity(*, pid, future):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))", [pid])
            if cursor.fetchone() == (True,):
                return
        if future.done():
            future.result()
            pytest.fail("Competing identity transaction did not wait for the first")
        Event().wait(0.01)
    pytest.fail("Competing identity transaction never reached the identity lock")


@pytest.mark.postgres
@pytest.mark.usefixtures("transactional_db")
class TestSignupIdentityRaces:
    @pytest.mark.parametrize("reject_first", (False, True))
    @pytest.mark.parametrize("claim", (False, True))
    def test_underage_denial_wins_with_uncommitted_identity(
        self, *, reject_first, claim, non_root_sphere
    ):
        companion = None
        if claim:
            manager = UserFactory()
            companion = UserFactory(
                user_type=UserType.CONNECTED, manager=manager, claim_token="invitation"
            )
        claim_token = "invitation" if claim else ""
        barrier = Barrier(2)
        pids = Queue()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                if reject_first:
                    _reject()
                else:
                    result = _complete(claim_token)
                    SphereSubscription.objects.create(
                        user_id=result.user.pk, sphere=non_root_sphere
                    )
                future = pool.submit(
                    _contend,
                    reject_first=reject_first,
                    claim_token=claim_token,
                    barrier=barrier,
                    pids=pids,
                )
                pid = pids.get(timeout=10)
                barrier.wait(timeout=10)
                _wait_for_blocked_identity(pid=pid, future=future)
            completed = future.result(timeout=10)

        user = User.objects.get(username="auth0|racing")
        assert user.is_active is False
        assert user.age_band == "unknown"
        assert not user.has_usable_password()
        assert not SphereSubscription.objects.filter(user=user).exists()
        if reject_first:
            assert completed.user.pk == user.pk
            assert completed.user.is_active is False
            assert (user.email, user.name, user.avatar_url) == ("", "", "")
        if companion:
            companion.refresh_from_db()
            if reject_first:
                assert companion.user_type == UserType.CONNECTED
                assert companion.claim_token == "invitation"
            else:
                assert user.pk == companion.pk
                assert companion.user_type == UserType.ACTIVE
                assert not companion.claim_token
