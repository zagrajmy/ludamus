"""Export what Django renders for dates and Accept-Language, for the TS replay.

test/fixtures/django-cases.json holds inputs and the real Django output for
the date filters and template tags the event page, event cards and session
cards use, plus LocaleMiddleware's language pick for a set of headers.
test/django-cases.test.ts runs every case through @zagrajmy/i18n.

Run from the repository root:

    .venv/bin/python experiment/packages/i18n/scripts/export_django_cases.py
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "experiment" / "packages" / "i18n"
OUT = PACKAGE / "test" / "fixtures" / "django-cases.json"
SEED = 20261030
RANDOM_MOMENTS = 24
NOW = datetime(2026, 10, 30, 19, 18, 49, 274130, tzinfo=UTC)
FORMATS = (
    "a A b c d D E f F g G h H i I j l L m M n N O P s S t T u U w y Y z Z",
    "l, j E",
    "D M j",
    "Y-m-d\\TH:i",
    "DATE_FORMAT",
    "DATETIME_FORMAT",
    "MONTH_DAY_FORMAT",
    "SHORT_DATE_FORMAT",
    "SHORT_DATETIME_FORMAT",
    "TIME_FORMAT",
    "YEAR_MONTH_FORMAT",
)
HEADERS = (
    "en-US,en;q=0.9",
    "pl-PL",
    "de",
    "",
    "*",
    "*, en",
    "en_US",
    "en;q=2",
    "EN",
    "de-DE,de;q=0.9,en;q=0.8",
    "fr;q=1.0, en;q=0",
    "en;q=0.5, pl;q=0.9",
    "pl;q=0.1,en",
    "zh-Hant-TW,en",
    "x-pl, pl",
    "en-",
    ",en",
    "en ,pl",
    "pl-PL;q=0.8,en-GB;q=0.80",
    "en-gb-oed",
    "i-klingon,en",
    "  en",
    "en;q =0.5",
    "pl ; q=1.000",
    "de-DE," * 100 + "en",
    "en," + "de-DE," * 100,
)


def _load_env() -> None:
    for raw in (ROOT / ".env.e2e").read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env()
sys.path.insert(0, str(ROOT / "src"))

import django

django.setup()

from django.test import RequestFactory
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation.trans_real import get_language_from_request

from ludamus.gates.web.django.templatetags.date_tags import (
    date_leaf,
    format_datetime_range,
    short_date,
)


def _sqlite(moment: datetime) -> str:
    text = moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    return f"{text}.{moment.microsecond:06d}" if moment.microsecond else text


def _moments(rng: random.Random) -> list[datetime]:
    fixed = [
        datetime(2026, 9, 4, 14, 0, tzinfo=UTC),
        datetime(2026, 3, 29, 0, 59, tzinfo=UTC),
        datetime(2026, 3, 29, 1, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
        datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
        datetime(2026, 1, 3, 23, 0, tzinfo=UTC),
        datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
        datetime(2024, 2, 29, 23, 0, 7, 123456, tzinfo=UTC),
        datetime(2031, 10, 30, 9, 0, tzinfo=UTC),
    ]
    start = datetime(2020, 1, 1, tzinfo=UTC)
    drawn = [
        start
        + timedelta(
            seconds=rng.randrange(12 * 365 * 86400),
            microseconds=rng.choice([0, rng.randrange(1, 10**6)]),
        )
        for _ in range(RANDOM_MOMENTS)
    ]
    return fixed + drawn


def _leaf(start: datetime, end: datetime | None) -> dict[str, object]:
    leaf = date_leaf(start, end)
    return {
        "band": leaf["band"],
        "bandIsLong": leaf["band_is_long"],
        "datetime": leaf["datetime"],
        "day": leaf["day"],
        "hour": leaf["hour"],
        "isOngoing": leaf["is_ongoing"],
        "isRange": leaf["is_range"],
        "isSunday": leaf["is_sunday"],
        "isToday": leaf["is_today"],
        "label": leaf["label"],
        "weekday": leaf["weekday"],
    }


def _date_cases(rng: random.Random) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    spans = [timedelta(hours=hours) for hours in (0, 1, 5, 7, 30, 80, 24 * 400)]
    for locale in ("en", "pl"):
        with translation.override(locale):
            for moment in _moments(rng):
                local = timezone.localtime(moment)
                value = _sqlite(moment)
                cases.extend(
                    {
                        "expected": date_format(local, spec),
                        "format": spec,
                        "kind": "format",
                        "locale": locale,
                        "value": value,
                    }
                    for spec in FORMATS
                )
                end = moment + rng.choice(spans)
                window = SimpleNamespace(start_time=moment, end_time=end)
                window_fields = {
                    "end": _sqlite(end),
                    "locale": locale,
                    "now": _sqlite(NOW),
                    "start": value,
                }
                cases.extend(
                    [
                        {
                            "expected": short_date(local),
                            "kind": "shortDate",
                            "locale": locale,
                            "value": value,
                        },
                        {
                            **window_fields,
                            "expected": format_datetime_range(window),
                            "kind": "range",
                        },
                        {
                            **window_fields,
                            "expected": _leaf(moment, end),
                            "kind": "leaf",
                        },
                        {
                            "expected": _leaf(moment, None),
                            "kind": "leaf",
                            "locale": locale,
                            "now": _sqlite(NOW),
                            "start": value,
                        },
                    ]
                )
    return cases


def _negotiation_cases() -> list[dict[str, object]]:
    requests = RequestFactory()
    return [
        {
            "expected": get_language_from_request(
                requests.get("/", HTTP_ACCEPT_LANGUAGE=header)
            ),
            "header": header,
            "kind": "negotiate",
        }
        for header in HEADERS
    ]


def main() -> None:
    rng = random.Random(SEED)
    with patch("django.utils.timezone.now", return_value=NOW):
        cases = _date_cases(rng) + _negotiation_cases()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.write(f"{OUT}: {len(cases)} cases\n")


if __name__ == "__main__":
    main()
