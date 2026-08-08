"""What the ritual hands on from a command it ran."""

from vekna.folio.shell import ShellResult

from ludamus.edges.rituals.shell import TAIL, said


def _ran(*, stdout: str = "", stderr: str = "") -> ShellResult:
    return ShellResult(stdout=stdout, stderr=stderr, exit_code=1)


class TestSaid:
    def test_both_streams_are_kept(self) -> None:
        assert said(_ran(stdout="E501 too long", stderr="1 failed")) == (
            "E501 too long\n1 failed"
        )

    def test_a_long_log_keeps_its_tail_and_says_what_it_dropped(self) -> None:
        run = "\n".join([f"tests/test_{index}.py PASSED" for index in range(TAIL + 50)])

        trimmed = said(_ran(stdout=run, stderr="1 failed"))

        assert trimmed.startswith("[51 earlier lines omitted]\n")
        assert trimmed.endswith("1 failed")
        assert "tests/test_0.py PASSED" not in trimmed
        assert len(trimmed.split("\n")) == TAIL + 1
