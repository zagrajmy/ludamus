"""Smoke test: DBOS runs a durable workflow on Python 3.14 + SQLite.

Guards the de-risked-but-fragile platform assumption behind the offer-expiry
scheduler (durable DBOS.sleep on a SQLite system DB). Uses an isolated
system-database file and tears DBOS down so it never touches app fixtures.
"""

from dbos import DBOS

_INPUT = 21
_DOUBLED = 42


def test_dbos_durable_workflow_runs_on_sqlite(tmp_path):
    recorded: list[int] = []

    @DBOS.step()
    def record(value: int) -> None:
        recorded.append(value)

    @DBOS.workflow()
    def double_after_sleep(value: int) -> int:
        DBOS.sleep(0.01)
        record(value)
        return value * 2

    DBOS(
        config={
            "name": "ludamus-smoke",
            "system_database_url": f"sqlite:///{tmp_path / 'dbos_sys.sqlite'}",
            "run_admin_server": False,
        }
    )
    DBOS.launch()
    try:
        handle = DBOS.start_workflow(double_after_sleep, _INPUT)
        assert handle.get_result() == _DOUBLED
        assert recorded == [_INPUT]
    finally:
        DBOS.destroy()
