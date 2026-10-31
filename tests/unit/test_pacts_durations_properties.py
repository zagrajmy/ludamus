"""Properties of reading a duration part typed into the hours/minutes steppers.

The part is user input on the import review, so every string must either read
as ASCII digits within range or be refused with `InvalidDurationError`; any
other exception escapes the view as a 500. The alphabet is every character
`str.isdigit` accepts, which is where `int` and `isdigit` disagree.
"""

import string
import sys

from hypothesis import given
from hypothesis import strategies as st

from ludamus.pacts.durations import (
    MAX_DURATION_HOURS,
    MAX_DURATION_MINUTES,
    InvalidDurationError,
    parse_duration_part,
)

_ISDIGIT_TRUE = tuple(
    char for code in range(sys.maxunicode + 1) if (char := chr(code)).isdigit()
)


@given(
    raw=st.text(
        alphabet=st.sampled_from(_ISDIGIT_TRUE) | st.sampled_from(string.digits + " "),
        max_size=3,
    ),
    maximum=st.sampled_from((MAX_DURATION_HOURS, MAX_DURATION_MINUTES)),
)
def test_a_part_is_ascii_digits_in_range_or_refused(raw: str, maximum: int) -> None:
    try:
        part = parse_duration_part(raw, maximum=maximum)
    except InvalidDurationError:
        return
    assert raw.strip().isascii()
    assert 0 <= part <= maximum
