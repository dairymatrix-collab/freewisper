"""Cancellable background tasks.

Long-running work (transcription, cleanup, injection) runs on a daemon
thread so the UI never blocks. A task can be cancelled *cooperatively*: the
token is checked at stage boundaries, so a cancelled task stops at the next
checkpoint instead of being killed mid-write.

Tasks can also be **exclusive**: submitting a task with a group name cancels
the in-flight task in that group. Pressing the hotkey twice quickly must not
transcribe the same audio twice.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from .errors import CancelledError


class CancelToken:
    """A cancellation flag that can be checked and waited on."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation. Idempotent."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """Has cancellation been requested?"""
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """Raise :class:`CancelledError` if cancellation was requested."""
        if self._event.is_set():
            raise CancelledError("operation cancelled")

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for cancellation. Returns ``True`` if it happened."""
        return self._event.wait(timeout)


def cancellable_sleep(seconds: float, token: CancelToken) -> None:
    """Sleep, but wake immediately if the task is cancelled.

    Raises:
        CancelledError: if the token was cancelled during the sleep.
    """
    token.wait(seconds)
    token.raise_if_cancelled()


class TaskHandle:
    """A running (or finished) task."""

    def __init__(
        self,
        *,
        name: str,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: Mapping[str, Any],
        token: CancelToken,
        group: str | None = None,
    ) -> None:
        self._name = name
        self._fn = fn
        self._args = args
        self._kwargs = dict(kwargs)
        self._token = token
        self._group = group
        self._done = threading.Event()
        self._result: Any = None
        self._exception: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._started_at = time.monotonic()

    @property
    def name(self) -> str:
        """The task's name."""
        return self._name

    @property
    def group(self) -> str | None:
        """The exclusivity group, if any."""
        return self._group

    @property
    def token(self) -> CancelToken:
        """The cancellation token."""
        return self._token

    @property
    def done(self) -> bool:
        """Has the task finished?"""
        return self._done.is_set()

    @property
    def cancelled(self) -> bool:
        """Was the task cancelled?"""
        return self._token.cancelled

    @property
    def duration_s(self) -> float:
        """How long the task ran (or has been running)."""
        end = time.monotonic()
        return end - self._started_at

    def cancel(self) -> None:
        """Request cancellation. The worker stops at its next checkpoint."""
        self._token.cancel()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the task to finish."""
        self._done.wait(timeout)

    def result(self, timeout: float | None = None) -> Any:
        """Wait for and return the task's result.

        Raises:
            CancelledError: if the task was cancelled.
            BaseException: whatever the task raised.
            TimeoutError: if the task did not finish in time.
        """
        if not self._done.wait(timeout):
            raise TimeoutError(f"task {self._name!r} did not finish in {timeout}s")
        if self._exception is not None:
            raise self._exception
        return self._result

    def exception(self) -> BaseException | None:
        """The exception the task raised, if any."""
        return self._exception

    def _attach(self, thread: threading.Thread) -> None:
        self._thread = thread

    def _run(self) -> None:
        try:
            self._result = self._fn(*self._args, token=self._token, **self._kwargs)
        except CancelledError as exc:
            self._exception = exc
        except BaseException as exc:  # noqa: BLE001 - captured and re-raised on result()
            self._exception = exc
        finally:
            self._done.set()


class TaskRunner:
    """Runs tasks on daemon threads, with optional exclusive groups."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._lock = threading.RLock()
        self._groups: dict[str, TaskHandle] = {}
        self._logger = logger or logging.getLogger("freewisper.core.tasks")

    def submit(
        self,
        fn: Callable[..., Any],
        *,
        name: str,
        group: str | None = None,
        args: tuple[Any, ...] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> TaskHandle:
        """Start ``fn`` on a daemon thread.

        The function is called as ``fn(*args, token=token, **kwargs)``.

        If ``group`` is given and a task in that group is still running, it
        is cancelled first.
        """
        token = CancelToken()
        handle = TaskHandle(
            name=name,
            fn=fn,
            args=args,
            kwargs=kwargs or {},
            token=token,
            group=group,
        )

        with self._lock:
            if group is not None:
                existing = self._groups.get(group)
                if existing is not None and not existing.done:
                    self._logger.info(
                        "Cancelling in-flight task %r in group %r.", existing.name, group
                    )
                    existing.cancel()
            if group is not None:
                self._groups[group] = handle

        thread = threading.Thread(target=handle._run, daemon=True, name=f"freewisper-{name}")
        handle._attach(thread)
        thread.start()
        return handle

    def active_group(self, group: str) -> TaskHandle | None:
        """The current task for ``group``, if any."""
        with self._lock:
            return self._groups.get(group)

    def cancel_group(self, group: str) -> bool:
        """Cancel whatever is running in ``group``."""
        with self._lock:
            handle = self._groups.get(group)
        if handle is None or handle.done:
            return False
        handle.cancel()
        return True

    def wait_for_group(self, group: str, timeout: float | None = None) -> bool:
        """Wait for the task in ``group`` to finish."""
        with self._lock:
            handle = self._groups.get(group)
        if handle is None:
            return True
        handle.join(timeout)
        return handle.done
