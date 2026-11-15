"""Cancellable tasks and the task runner."""

from __future__ import annotations

import threading
import time

import pytest

from freewisper.core.errors import CancelledError
from freewisper.core.tasks import CancelToken, TaskRunner, cancellable_sleep

# ---------------------------------------------------------------------------
# CancelToken
# ---------------------------------------------------------------------------


def test_a_new_token_is_not_cancelled() -> None:
    assert CancelToken().cancelled is False


def test_cancel_sets_the_flag() -> None:
    token = CancelToken()
    token.cancel()
    assert token.cancelled is True


def test_cancel_is_idempotent() -> None:
    token = CancelToken()
    token.cancel()
    token.cancel()
    assert token.cancelled is True


def test_raise_if_cancelled_raises_only_after_cancel() -> None:
    token = CancelToken()
    token.raise_if_cancelled()
    token.cancel()
    with pytest.raises(CancelledError):
        token.raise_if_cancelled()


def test_wait_returns_immediately_when_cancelled() -> None:
    token = CancelToken()
    token.cancel()
    assert token.wait(0.01) is True


def test_wait_times_out_when_not_cancelled() -> None:
    assert CancelToken().wait(0.01) is False


def test_cancellable_sleep_wakes_on_cancel() -> None:
    token = CancelToken()
    threading.Timer(0.05, token.cancel).start()

    started = time.monotonic()
    with pytest.raises(CancelledError):
        cancellable_sleep(5.0, token)

    assert time.monotonic() - started < 2.0


def test_cancellable_sleep_returns_normally() -> None:
    cancellable_sleep(0.01, CancelToken())


# ---------------------------------------------------------------------------
# TaskRunner
# ---------------------------------------------------------------------------


def test_a_task_runs_and_returns_its_result() -> None:
    runner = TaskRunner()

    def work(token: CancelToken) -> str:
        return "done"

    handle = runner.submit(work, name="work")
    assert handle.result(timeout=5.0) == "done"
    assert handle.done is True


def test_a_task_receives_its_arguments() -> None:
    runner = TaskRunner()

    def work(a: int, b: int, token: CancelToken) -> int:
        return a + b

    handle = runner.submit(work, name="sum", args=(2, 3))
    assert handle.result(timeout=5.0) == 5


def test_a_task_exception_is_captured_and_re_raised() -> None:
    runner = TaskRunner()

    def work(token: CancelToken) -> None:
        raise ValueError("boom")

    handle = runner.submit(work, name="bad")
    with pytest.raises(ValueError, match="boom"):
        handle.result(timeout=5.0)
    assert isinstance(handle.exception(), ValueError)


def test_a_task_exception_does_not_kill_the_process() -> None:
    runner = TaskRunner()

    def work(token: CancelToken) -> None:
        raise RuntimeError("boom")

    handle = runner.submit(work, name="bad")
    handle.join(5.0)
    assert handle.done is True


def test_cancel_stops_a_long_task_at_its_next_checkpoint() -> None:
    runner = TaskRunner()
    reached_end = threading.Event()

    def work(token: CancelToken) -> None:
        for _ in range(100):
            token.raise_if_cancelled()
            time.sleep(0.01)
        reached_end.set()

    handle = runner.submit(work, name="long")
    time.sleep(0.05)
    handle.cancel()

    with pytest.raises(CancelledError):
        handle.result(timeout=5.0)
    assert reached_end.is_set() is False


def test_a_new_task_cancels_the_in_flight_task_in_the_same_group() -> None:
    runner = TaskRunner()
    first_cancelled = threading.Event()

    def slow(token: CancelToken) -> None:
        try:
            for _ in range(200):
                token.raise_if_cancelled()
                time.sleep(0.01)
        except CancelledError:
            first_cancelled.set()
            raise

    def quick(token: CancelToken) -> str:
        return "second"

    first = runner.submit(slow, name="slow", group="dictation")
    time.sleep(0.05)
    second = runner.submit(quick, name="quick", group="dictation")

    assert second.result(timeout=5.0) == "second"
    assert first_cancelled.wait(5.0) is True
    with pytest.raises(CancelledError):
        first.result(timeout=5.0)


def test_tasks_in_different_groups_do_not_cancel_each_other() -> None:
    runner = TaskRunner()
    finished = threading.Event()

    def slow(token: CancelToken) -> None:
        for _ in range(100):
            token.raise_if_cancelled()
            time.sleep(0.01)
        finished.set()

    def quick(token: CancelToken) -> str:
        return "ok"

    first = runner.submit(slow, name="slow", group="a")
    second = runner.submit(quick, name="quick", group="b")

    assert second.result(timeout=5.0) == "ok"
    assert first.cancelled is False
    first.join(10.0)
    assert finished.is_set() is True


def test_cancel_group_reports_whether_something_was_cancelled() -> None:
    runner = TaskRunner()

    def work(token: CancelToken) -> None:
        for _ in range(100):
            token.raise_if_cancelled()
            time.sleep(0.01)

    runner.submit(work, name="work", group="g")
    assert runner.cancel_group("g") is True
    assert runner.cancel_group("missing") is False


def test_wait_for_group_returns_when_the_task_finishes() -> None:
    runner = TaskRunner()

    def work(token: CancelToken) -> str:
        return "ok"

    runner.submit(work, name="work", group="g")
    assert runner.wait_for_group("g", timeout=5.0) is True


def test_wait_for_an_unknown_group_is_immediately_true() -> None:
    assert TaskRunner().wait_for_group("nope", timeout=0.1) is True


def test_active_group_returns_the_current_handle() -> None:
    runner = TaskRunner()

    def work(token: CancelToken) -> None:
        time.sleep(0.2)

    handle = runner.submit(work, name="work", group="g")
    assert runner.active_group("g") is handle


def test_result_times_out_when_the_task_is_stuck() -> None:
    runner = TaskRunner()
    release = threading.Event()

    def work(token: CancelToken) -> None:
        release.wait(5.0)

    handle = runner.submit(work, name="stuck")
    try:
        with pytest.raises(TimeoutError):
            handle.result(timeout=0.05)
    finally:
        release.set()


def test_duration_is_measured() -> None:
    runner = TaskRunner()

    def work(token: CancelToken) -> None:
        time.sleep(0.05)

    handle = runner.submit(work, name="work")
    handle.join(5.0)
    assert handle.duration_s >= 0.04
