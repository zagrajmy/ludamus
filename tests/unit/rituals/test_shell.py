"""What the ritual hands on from a command it ran."""

from vekna.folio.shell import ShellResult

from ludamus.edges.rituals.shell import (
    BUDGET,
    VERDICT_LINES,
    already_seen,
    coverage_report,
    said,
    same_verdict,
    verdict,
)

# Ten characters once its newline is counted, so a whole number of these is
# exactly the budget and the boundary can be named rather than approached.
_ROW = "x" * 9
_FITS = BUDGET // 10

_REPORT = """Diff Coverage
Diff: main...HEAD
-------------
src/ludamus/thing.py (80.0%): Missing lines 12-14
-------------
Total:   10 lines
Missing: 5 lines
Coverage: 50%
-------------
"""


def _ran(*, stdout: str = "", stderr: str = "") -> ShellResult:
    return ShellResult(stdout=stdout, stderr=stderr, exit_code=1)


def _rows(count: int) -> str:
    return "\n".join([_ROW] * count)


class TestSaid:
    def test_both_streams_are_kept(self) -> None:
        assert said(_ran(stdout="E501 too long", stderr="1 failed")) == (
            "E501 too long\n1 failed"
        )

    # The agent pays for what it reads, and a cursor move is not worth a token.
    def test_colour_and_cursor_moves_are_stripped(self) -> None:
        coloured = "\x1b[1A\x1b[2K\x1b[31m1 failed\x1b[39m"

        assert said(_ran(stdout=coloured)) == "1 failed"

    def test_a_trailing_newline_is_not_a_line(self) -> None:
        assert said(_ran(stdout="E501 too long\n", stderr="1 failed\n")) == (
            "E501 too long\n1 failed"
        )

    def test_a_log_that_fits_the_budget_comes_back_whole(self) -> None:
        fits = _rows(_FITS)

        assert said(_ran(stdout=fits)) == fits

    def test_one_line_over_the_budget_drops_exactly_one(self) -> None:
        over = _rows(_FITS + 1)

        trimmed = said(_ran(stdout=over))

        assert trimmed == f"[1 earlier lines omitted]\n{_rows(_FITS)}"

    def test_a_long_log_keeps_its_tail_and_says_what_it_dropped(self) -> None:
        run = "\n".join(
            [f"tests/test_{index}.py PASSED" for index in range(_FITS)] + ["1 failed"]
        )

        trimmed = said(_ran(stdout=run))

        assert trimmed.startswith("[")
        assert trimmed.endswith("1 failed")
        assert "tests/test_0.py PASSED" not in trimmed

    # mise puts its own task chatter on stderr and the tool's verdict on stdout,
    # so a budget shared between the streams is won by the chatter and the
    # repair agent is handed a progress log with no diagnosis in it.
    def test_a_long_stderr_cannot_evict_what_stdout_said(self) -> None:
        chatter = _rows(_FITS * 2)

        trimmed = said(_ran(stdout="E501 too long", stderr=chatter))

        assert trimmed.startswith("E501 too long\n[")

    def test_a_stream_that_said_nothing_is_left_out(self) -> None:
        assert said(_ran(stdout="1 failed", stderr="\n")) == "1 failed"


class TestVerdict:
    def test_the_tail_is_what_comes_back(self) -> None:
        run = "\n".join([f"line {index}" for index in range(50)] + ["1 failed"])

        assert verdict(_ran(stdout=run)).splitlines() == [
            *[f"line {index}" for index in range(50 - VERDICT_LINES + 1, 50)],
            "1 failed",
        ]

    # A progress reporter writing over itself leaves hundreds of these, and they
    # would spend the whole allowance saying nothing.
    def test_blank_lines_do_not_count_against_the_allowance(self) -> None:
        padded = "1 failed" + "\n" * 200 + "\n210 passed"

        assert verdict(_ran(stdout=padded)) == "1 failed\n210 passed"

    def test_colour_and_cursor_moves_are_stripped(self) -> None:
        coloured = "\x1b[1A\x1b[2K\x1b[31m1 failed\x1b[39m"

        assert verdict(_ran(stdout=coloured)) == "1 failed"

    # Under e2e, stderr is a web server logging every request it served. The
    # tools put their tally on stdout, and that is the whole answer.
    def test_a_stderr_transcript_cannot_bury_what_stdout_said(self) -> None:
        chatter = _rows(_FITS * 2)

        assert verdict(_ran(stdout="1 failed", stderr=chatter)) == "1 failed"

    # The task that died before it started says so on stderr and nowhere else.
    def test_a_silent_stdout_falls_back_to_stderr(self) -> None:
        assert verdict(_ran(stderr="mise: no such task")) == "mise: no such task"


class TestSameVerdict:
    # Timings and tallies move between branches; the failing test does not.
    def test_the_same_failure_counted_differently_is_the_same_failure(self) -> None:
        assert same_verdict(
            "1 failed\n  panel.spec.ts:77:5 > redirects\n210 passed (6.8m)",
            "1 failed\n  panel.spec.ts:77:5 > redirects\n212 passed (5.5m)",
        )

    def test_a_different_failure_is_not(self) -> None:
        assert not same_verdict("panel.spec.ts > redirects", "panel.spec.ts > assigns")

    # Nothing recognises nothing: a run with no verdict to compare has to go
    # round the repair loop like any other.
    def test_an_empty_verdict_matches_nothing(self) -> None:
        assert not same_verdict("", "")


class TestAlreadySeen:
    # Two things broken at once alternate down the queue, and a memo of one
    # recognises neither.
    def test_a_verdict_the_run_gave_up_on_earlier_is_still_recognised(self) -> None:
        assert already_seen(
            "1 failed (6.8m)", ["could not resolve host", "1 failed (5.5m)"]
        )

    def test_a_new_failure_is_not(self) -> None:
        assert not already_seen("2 errors", ["could not resolve host", "1 failed"])

    def test_a_run_that_has_given_up_on_nothing_recognises_nothing(self) -> None:
        assert not already_seen("1 failed", [])


class TestCoverageReport:
    # The listing is the work list, so it goes to the agent entire however many
    # files it names — and the suite that printed it goes nowhere at all.
    def test_the_report_outlives_the_suite_that_printed_it(self) -> None:
        transcript = _rows(_FITS * 3)

        report = coverage_report(_ran(stdout=f"{transcript}\n-------------\n{_REPORT}"))

        assert report == _REPORT

    def test_a_run_that_printed_no_report_falls_back_to_the_trimmed_log(self) -> None:
        assert coverage_report(_ran(stderr="no coverage data")) == "no coverage data"
