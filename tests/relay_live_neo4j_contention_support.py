"""Controlled contention helpers for live Neo4j relay tests."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, wait
from threading import Barrier, BrokenBarrierError, Event, Lock, Thread


class _OperationBarrierRunner:
    """Hold matching operations until every intended contender is ready."""

    def __init__(self, runner: object, *, query_marker: str, parties: int) -> None:
        self._runner = runner
        self._query_marker = query_marker
        self._barrier = Barrier(parties, timeout=15)
        self._parties = parties
        self._lock = Lock()
        self._arrivals = 0
        self._waiting = 0
        self._peak_waiting = 0
        self._releases = 0
        self._all_released = Event()

    def run(
        self,
        query: str,
        parameters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        if self._query_marker in query:
            with self._lock:
                if self._arrivals >= self._parties:
                    raise AssertionError(
                        "relay operation crossed the contention gate too many times"
                    )
                self._arrivals += 1
                self._waiting += 1
                self._peak_waiting = max(self._peak_waiting, self._waiting)
            try:
                self._barrier.wait()
            except BrokenBarrierError as exc:
                raise AssertionError(
                    "contenders did not overlap at the gated relay operation"
                ) from exc
            finally:
                with self._lock:
                    self._waiting -= 1
            with self._lock:
                self._releases += 1
                if self._releases == self._parties:
                    self._all_released.set()
        return self._runner.run(query, parameters)

    def wait_until_released(self) -> bool:
        return self._all_released.wait(timeout=15)

    def assert_full_contention(self, test_case: object) -> None:
        test_case.assertEqual(self._arrivals, self._parties)
        test_case.assertEqual(self._peak_waiting, self._parties)
        test_case.assertEqual(self._releases, self._parties)


class _HeldNeo4jLock:
    """Hold a node-property write lock in a separate Neo4j transaction."""

    def __init__(
        self,
        driver: object,
        *,
        query: str,
        parameters: dict[str, object],
    ) -> None:
        self._driver = driver
        self._query = query
        self._parameters = parameters
        self._acquired = Event()
        self._release = Event()
        self._thread = Thread(target=self._hold, name="relay-live-lock-holder")
        self._error: BaseException | None = None

    def _hold(self) -> None:
        try:
            with self._driver.session() as session:
                transaction = session.begin_transaction()
                try:
                    result = transaction.run(self._query, self._parameters)
                    if result.single() is None:
                        raise AssertionError("Neo4j test lock target did not exist")
                    self._acquired.set()
                    if not self._release.wait(timeout=30):
                        raise AssertionError(
                            "timed out waiting to release Neo4j test lock"
                        )
                finally:
                    transaction.rollback()
        except BaseException as exc:
            self._error = exc
            self._acquired.set()

    def __enter__(self) -> "_HeldNeo4jLock":
        self._thread.start()
        if not self._acquired.wait(timeout=15):
            self._release.set()
            self._thread.join(timeout=15)
            raise AssertionError(
                "separate Neo4j transaction did not acquire test lock"
            )
        if self._error is not None:
            self._thread.join(timeout=15)
            raise self._error
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._release.set()
        self._thread.join(timeout=15)
        if self._thread.is_alive():
            raise AssertionError("Neo4j test lock-holder transaction did not stop")
        if exc_type is None and self._error is not None:
            raise self._error


def _assert_blocked_by_held_lock(
    test_case: object,
    gated_runner: _OperationBarrierRunner,
    futures: list[Future[object]],
) -> None:
    """Prove released contenders cannot complete while the DB lock is held."""
    test_case.assertTrue(
        gated_runner.wait_until_released(),
        "contenders did not all reach the gated database operation",
    )
    completed, _ = wait(futures, timeout=0.25, return_when=FIRST_COMPLETED)
    test_case.assertEqual(
        completed,
        set(),
        "a contender completed while the separate Neo4j lock was still held",
    )
