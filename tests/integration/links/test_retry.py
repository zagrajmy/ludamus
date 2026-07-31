from __future__ import annotations

from unittest.mock import patch

import requests
import responses
from requests.adapters import HTTPAdapter
from responses import registries

from ludamus.links.retry import mount_retries

URL = "https://upstream.example.com/thing"
TOO_MANY_REQUESTS = 429


def test_bare_timeout_gains_a_bounded_connect_budget():
    session = mount_retries(requests.Session())

    with patch.object(HTTPAdapter, "send", return_value=requests.Response()) as send:
        session.get(URL, timeout=10)

    # The literal is the point: connect attempts are retried, so each one must
    # stay cheap no matter how long the caller is willing to wait for a reply.
    assert send.call_args.kwargs["timeout"] == (3.05, 10)


def test_caller_supplied_split_timeout_is_left_alone():
    session = mount_retries(requests.Session())

    with patch.object(HTTPAdapter, "send", return_value=requests.Response()) as send:
        session.get(URL, timeout=(1, 2))

    assert send.call_args.kwargs["timeout"] == (1, 2)


def test_rate_limiting_is_not_retried():
    session = mount_retries(requests.Session())

    with responses.RequestsMock(
        registry=registries.OrderedRegistry, assert_all_requests_are_fired=True
    ) as rsps:
        rsps.get(URL, status=TOO_MANY_REQUESTS)

        session.get(URL, timeout=10)

        # One call, not three: a rate-limited caller backs off at the flow
        # level rather than hammering the upstream that just said "slow down".
        assert len(rsps.calls) == 1
