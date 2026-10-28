"""Task: a small asyncio-free task/awaitable runtime.

This is a deliberately small runtime, not an asyncio compatibility layer.

Public API
----------
    Task.configure(max_workers=8, max_pending_background=128)
    Task.run(async_function, *args, token=token)
    Task.run(blocking_function, *args, token=token, pass_token=True)
    await Task.delay(0.5, token=token)
    await IO.wait_readable(sock, token=token)
    await IO.wait_writable(sock, token=token)

    cts = CancellationTokenSource()
    linked = CancellationTokenSource.create_linked_token_source(cts.token, other.token)
    cts.cancel()

There is no application-managed Runtime object and no asyncio dependency. The
runtime is process-wide and starts lazily. Call Task.shutdown() for an explicit,
observable shutdown; it can be started again by subsequent Task.run calls.

Cancellation is cooperative for coroutines and worker functions. A worker can
receive the same token with pass_token=True and should check it between units
of work. Python cannot safely force-stop an arbitrary running thread.
"""
from __future__ import annotations

import atexit
import heapq
import inspect
import logging
import os
import queue
import selectors
import socket
import threading
import time
from collections import deque
from collections.abc import Generator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from itertools import count
from typing import Any, Generic, TypeVar, cast, Iterable, Final, overload
import functools
from functools import wraps
from collections.abc import Awaitable, Callable, Coroutine


import flpit

T = TypeVar("T")
_LOG = logging.getLogger("task")
_MISSING = object()
_WAKE = object()


class OperationCanceledError(Exception):
    """Raised when an operation is canceled.

    ``token`` records the token associated with cancellation when one exists.
    The exception intentionally derives from ``Exception`` so normal exception
    handling can catch cancellation explicitly or through a broad handler.
    """

    def __init__(
            self,
            message: str = "The operation was canceled.",
            token: CancellationToken | None = None,
    ) -> None:
        self.token = token
        super().__init__(message)


# Backwards-compatible spelling used by the first Task prototype.
CancelledError = OperationCanceledError


class InvalidStateError(RuntimeError):
    """An operation was requested before a Task reached a valid state."""


class BackgroundQueueFull(RuntimeError):
    """Raised when the bounded background-work queue has no free capacity."""


class RuntimeShutdownError(RuntimeError):
    """Raised when new work is submitted while the singleton runtime is stopping."""


class AggregateError(Exception):
    """Represents multiple errors, preserving the original exceptions.

    The default message follows the .NET ``AggregateException`` convention.
    ``exceptions`` is stored as an immutable snapshot.
    """

    def __init__(
            self,
            exceptions: Iterable[Exception],
            message: str = "One or more errors occurred.",
    ) -> None:
        self.exceptions = tuple(exceptions)
        if not self.exceptions:
            raise ValueError("exceptions must contain at least one exception")
        if not all(isinstance(error, Exception) for error in self.exceptions):
            raise TypeError("exceptions must contain Exception instances")
        super().__init__(message)


@dataclass(frozen=True)
class ShutdownReport:
    """Outcome of a runtime shutdown request."""

    runtime_stopped: bool
    tasks_cancelled: int
    workers_still_running: int
    timed_out: bool


class _CancellationState:
    """Thread-safe cancellation state shared by tokens and their source."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.cancelled = False
        self.callbacks: dict[int, Callable[[], Any]] = {}
        self.next_id = count(1)

    def register(self, callback: Callable[[], Any]) -> "CancellationTokenRegistration":
        with self.lock:
            if not self.cancelled:
                key = next(self.next_id)
                self.callbacks[key] = callback

                return CancellationTokenRegistration(self, key)

        exception = _invoke_cancellation_callback(callback)

        if exception is not None:
            raise exception

        return CancellationTokenRegistration(None, None)

    def unregister(self, key: int) -> None:
        with self.lock:
            self.callbacks.pop(key, None)

    def cancel(self) -> bool:
        with self.lock:

            if self.cancelled:
                return False

            self.cancelled = True
            callbacks = list(reversed(self.callbacks.values()))
            self.callbacks.clear()

        exceptions: list[Exception] = []

        for callback in callbacks:
            exception = _invoke_cancellation_callback(callback)
            if exception is not None:
                exceptions.append(exception)

        if exceptions:
            raise AggregateError(exceptions)

        return True


def _invoke_cancellation_callback(callback: Callable[[], Any]) -> Exception | None:
    try:
        callback()
    except Exception as exc:
        return exc

    return None


class CancellationTokenRegistration:
    """Disposable registration returned by CancellationToken.register()."""

    __slots__ = ("_state", "_key", "_disposed", "_lock")

    def __init__(self, state: _CancellationState | None, key: int | None) -> None:
        self._state = state
        self._key = key
        self._disposed = False
        self._lock = threading.Lock()

    def dispose(self) -> None:
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            state, key = self._state, self._key
            self._state = None
            self._key = None
        if state is not None and key is not None:
            state.unregister(key)

    close = dispose

    def __enter__(self) -> "CancellationTokenRegistration":
        return self

    def __exit__(self, *_: Any) -> None:
        self.dispose()


class CancellationToken:
    """Read-only cancellation handle. Create cancellable tokens via a source."""

    __slots__ = ("_state",)

    def __init__(self, state: _CancellationState | None = None) -> None:
        # A public no-argument token is intentionally non-cancellable, matching
        # the role of CancellationToken.none(). Sources create tokens with state.
        self._state = state

    @classmethod
    def none(cls) -> "CancellationToken":
        return _NONE_TOKEN

    @property
    def can_be_cancelled(self) -> bool:
        return self._state is not None

    @property
    def is_cancellation_requested(self) -> bool:
        state = self._state
        if state is None:
            return False
        with state.lock:
            return state.cancelled

    def throw_if_cancellation_requested(self) -> None:
        if self.is_cancellation_requested:
            raise OperationCanceledError("Cancellation was requested")

    def register(self, callback: Callable[[], Any]) -> CancellationTokenRegistration:
        if not callable(callback):
            raise TypeError("callback must be callable")
        state = self._state
        if state is None:
            return CancellationTokenRegistration(None, None)
        return state.register(callback)

    def __repr__(self) -> str:
        return (
            "CancellationToken(can_be_cancelled=False)"
            if self._state is None
            else f"CancellationToken(cancelled={self.is_cancellation_requested})"
        )


_NONE_TOKEN = CancellationToken()


class CancellationTokenSource:
    """Owns cancellation state and provides a token consumers can observe."""

    def __init__(self) -> None:
        self._state = _CancellationState()
        self._token = CancellationToken(self._state)
        self._lock = threading.RLock()
        self._disposed = False
        self._timer: threading.Timer | None = None
        self._linked_registrations: list[CancellationTokenRegistration] = []

    @property
    def token(self) -> CancellationToken:
        return self._token

    @property
    def is_cancellation_requested(self) -> bool:
        return self._token.is_cancellation_requested

    def cancel(self) -> bool:
        with self._lock:
            self._throw_if_disposed()
            timer = self._timer
            self._timer = None
            links = list(self._linked_registrations)
            self._linked_registrations.clear()
        if timer is not None:
            timer.cancel()
        try:
            cancelled = self._state.cancel()
        finally:
            # A linked source no longer needs to hold registrations after its own
            # cancellation has fired. Also clean these up if a callback failed.
            for registration in links:
                registration.dispose()
        return cancelled

    def cancel_after(self, seconds: float | None) -> None:
        """Request cancellation after seconds; None or -1 disables the timer."""
        with self._lock:
            self._throw_if_disposed()
            old_timer = self._timer
            self._timer = None
            if seconds is not None and seconds != -1:
                if seconds < 0:
                    raise ValueError("seconds must be >= 0, -1, or None")
                timer = threading.Timer(seconds, self._cancel_from_timer)
                timer.daemon = True
                self._timer = timer
            else:
                timer = None
        if old_timer is not None:
            old_timer.cancel()
        if timer is not None:
            timer.start()

    def _cancel_from_timer(self) -> None:
        try:
            self.cancel()
        except RuntimeError:
            # The source was disposed concurrently with its timer firing.
            pass

    @classmethod
    def create_linked_token_source(
            cls, *tokens: CancellationToken
    ) -> "CancellationTokenSource":
        if any(not isinstance(token, CancellationToken) for token in tokens):
            raise TypeError("all linked values must be CancellationToken instances")
        linked = cls()
        for token in tokens:
            registration = token.register(linked._cancel_from_link)
            linked._linked_registrations.append(registration)
            # If the source token was already cancelled, the callback executes
            # synchronously during register() and the linked source is now cancelled.
            if linked.is_cancellation_requested:
                break
        if linked.is_cancellation_requested:
            linked._dispose_link_registrations()
        return linked

    def _cancel_from_link(self) -> None:
        try:
            self.cancel()
        except RuntimeError:
            pass

    def _dispose_link_registrations(self) -> None:
        with self._lock:
            links = list(self._linked_registrations)
            self._linked_registrations.clear()
        for registration in links:
            registration.dispose()

    def dispose(self) -> None:
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            timer = self._timer
            self._timer = None
            links = list(self._linked_registrations)
            self._linked_registrations.clear()
        if timer is not None:
            timer.cancel()
        for registration in links:
            registration.dispose()

    close = dispose

    def _throw_if_disposed(self) -> None:
        if self._disposed:
            raise RuntimeError("CancellationTokenSource has been disposed")

    def __enter__(self) -> "CancellationTokenSource":
        self._throw_if_disposed()
        return self

    def __exit__(self, *_: Any) -> None:
        self.dispose()


class _Operation:
    """Instruction yielded by an awaitable and consumed by the scheduler."""

    def __init__(self, runtime: "_Runtime", token: CancellationToken | None = None) -> None:
        self.runtime = runtime
        self.token = token or CancellationToken.none()
        self._token_registration: CancellationTokenRegistration | None = None

    def __await__(self):
        result = yield self
        return result


class _Sleep(_Operation):
    def __init__(self, runtime: "_Runtime", delay: float) -> None:
        super().__init__(runtime)
        self.delay = delay
        self.deadline = time.monotonic() + delay


class _YieldNow(_Operation):
    pass


class _WaitIO(_Operation):
    def __init__(
            self, runtime: "_Runtime", sock: socket.socket, mode: str,
            token: CancellationToken | None = None,
    ) -> None:
        super().__init__(runtime, token)
        self.sock = sock
        self.mode = mode


class _WaitTask[T](_Operation):
    def __init__(self, runtime: "_Runtime", ttw: "Task[T]") -> None:
        super().__init__(runtime)
        self.task = ttw


class _WaitMany[T](_Operation):
    """Wait for all or any of a set of tasks to complete."""

    def __init__(
            self, runtime: "_Runtime", tasks: tuple["Task[T]", ...], mode: str
    ) -> None:
        super().__init__(runtime)
        if mode not in ("all", "any"):
            raise ValueError("mode must be 'all' or 'any'")
        self.tasks = tasks
        self.mode = mode


class _BackgroundCall(_Operation):
    def __init__(
            self,
            runtime: "_Runtime",
            function: Callable[..., Any],
            args: tuple[Any, ...],
            kwargs: dict[str, Any],
    ) -> None:
        super().__init__(runtime)
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.future: Future[Any] | None = None
        self._counted_active = False


async def _await_any(awaitable: Any) -> Any:
    return await awaitable


async def _invoke_async(
        function: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Any:
    return await function(*args, **kwargs)


async def _invoke_background(
        runtime: "_Runtime",
        function: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
) -> Any:
    result = await _BackgroundCall(runtime, function, args, kwargs)
    # Support sync wrappers that return an awaitable.
    if inspect.isawaitable(result):
        return await result
    return result


async def _delay_coroutine(runtime: "_Runtime", delay: float) -> None:
    await _Sleep(runtime, delay)


class Task(Generic[T]):
    """Result-bearing task managed by FlpIt's process-wide scheduler."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def __init__(
            self,
            runtime: "_Runtime",
            *,
            name: str | None = None,
            token: CancellationToken | None = None,
    ) -> None:
        self._runtime = runtime
        self.name = name or f"Task-{id(self):x}"
        self._state = self.PENDING
        self._result: Any = None
        self._exception: BaseException | None = None
        self._coroutine: Coroutine[Any, Any, Any] | None = None
        self._awaiters: set[Task[Any]] = set()
        self._waiting_on: _Operation | None = None
        self._queued = False
        self._running = False
        self._next_value: Any = None
        self._next_exception: BaseException | None = None
        self._cancel_requested = False
        self._completed = threading.Event()
        self._token = token or CancellationToken.none()
        self._token_registration: CancellationTokenRegistration | None = None
        self._pass_token = False
        self._is_promise_task = False
        self.async_state: Any = None

    @property
    def status(self) -> str:
        """Current task state: pending, succeeded, failed, or cancelled."""
        return self._state

    @classmethod
    def configure(
            cls,
            *,
            max_workers: int | None = None,
            max_pending_background: int | None = None,
    ) -> None:
        """Configure worker capacity before the runtime is first started.

        Background overload policy is intentionally explicit and currently fixed
        to rejection: excess work fails with BackgroundQueueFull rather than
        growing an unbounded queue or blocking the scheduler thread.
        """
        global _runtime_config
        with _runtime_lock:
            if _runtime is not None and not _runtime.closed:
                raise RuntimeError("Task.configure() must be called before runtime startup")
            config = dict(_runtime_config)
            if max_workers is not None:
                if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
                    raise ValueError("max_workers must be an integer >= 1")
                config["max_workers"] = max_workers
            if max_pending_background is not None:
                if (
                        isinstance(max_pending_background, bool)
                        or not isinstance(max_pending_background, int)
                        or max_pending_background < 0
                ):
                    raise ValueError("max_pending_background must be an integer >= 0")
                config["max_pending_background"] = max_pending_background
            _runtime_config = config

    @classmethod
    def set_exception_handler(
            cls, handler: Callable[[dict[str, Any]], Any] | None
    ) -> None:
        """Install a handler for unexpected scheduler/backend errors.

        Handler receives a context mapping containing at least ``message`` and
        ``exception``. If no handler is installed, these failures are logged.
        """
        if handler is not None and not callable(handler):
            raise TypeError("handler must be callable or None")
        _get_runtime().set_exception_handler(handler)

    @overload
    @classmethod
    def run[R](
            cls,
            work: Callable[..., Coroutine[Any, Any, R]],
            /,
            *args: Any,
            name: str | None = None,
            token: CancellationToken | None = None,
            pass_token: bool = False,
            **kwargs: Any,
    ) -> Task[R]: ...

    @overload
    @classmethod
    def run[R](
            cls,
            work: Callable[..., R],
            /,
            *args: Any,
            name: str | None = None,
            token: CancellationToken | None = None,
            pass_token: bool = False,
            **kwargs: Any,
    ) -> Task[R]: ...

    @classmethod
    def run(
            cls,
            work: Callable[..., Any],
            /,
            *args: Any,
            name: str | None = None,
            token: CancellationToken | None = None,
            pass_token: bool = False,
            **kwargs: Any,
    ) -> Task[Any]:
        # Keep your existing implementation here.
        ...
        """Schedule a coroutine/awaitable or ordinary callable.

        Ordinary functions run in the bounded worker pool. ``token`` controls
        the Task's cancellation. With ``pass_token=True``, that same token is
        also supplied to the target callable as the keyword argument ``token``
        (useful for cooperative worker functions).
        """
        if inspect.isawaitable(work):
            if args or kwargs or pass_token:
                if inspect.iscoroutine(work):
                    work.close()
                raise TypeError("args/kwargs/pass_token cannot be supplied with an awaitable instance")
        elif not callable(work):
            raise TypeError("Task.run() expects an awaitable or a callable")
        if token is not None and not isinstance(token, CancellationToken):
            if inspect.iscoroutine(work):
                work.close()
            raise TypeError("token must be a CancellationToken")
        if pass_token and token is None:
            if inspect.iscoroutine(work):
                work.close()
            raise ValueError("pass_token=True requires an explicit token")
        runtime = _get_runtime()
        task = cls(runtime, name=name, token=token)
        task._pass_token = pass_token
        runtime._submit(task, work, args, kwargs)
        return task

    @classmethod
    def when_all(
            cls,
            *tasks: Awaitable[T],
            name: str | None = None,
            token: CancellationToken | None = None,
    ) -> "Task[list[Any]]":
        """Complete when every supplied task completes, preserving input order.

        Accepts Task instances and raw awaitables (including coroutine objects)
        as positional arguments or in one iterable. Raw awaitables are scheduled
        automatically. Child tasks are not cancelled if this
        aggregate task is cancelled. A single child failure is re-raised; if
        several children fail, TaskAggregateError exposes all their exceptions.
        If there are no tasks, the result is an empty list.
        """
        if token is not None and not isinstance(token, CancellationToken):
            raise TypeError("token must be a CancellationToken")
        normalized = _normalize_tasks(tasks, allow_empty=True)
        return cast(
            "Task[list[Any]]",
            cls.run(_when_all_coroutine, normalized, name=name, token=token),
        )

    @classmethod
    def when_any(
            cls,
            *tasks: Any,
            name: str | None = None,
            token: CancellationToken | None = None,
    ) -> "Task[Task[Any]]":
        """Complete when one supplied task completes and return that task.

        Accepts Task instances and raw awaitables (including coroutine objects)
        positionally or in one iterable. Raw awaitables are scheduled
        automatically. The winning task is returned even if it failed or was
        canceled; inspect/await that task to observe
        its outcome. Losing tasks continue running. An empty input is invalid.
        If multiple tasks are already complete at observation time, input order
        breaks the tie deterministically.
        """
        if token is not None and not isinstance(token, CancellationToken):
            raise TypeError("token must be a CancellationToken")
        normalized = _normalize_tasks(tasks, allow_empty=False)
        return cast(
            "Task[Task[Any]]",
            cls.run(_when_any_coroutine, normalized, name=name, token=token),
        )

    @staticmethod
    async def collect(*tasks: Task[Any] | list[Task[Any]]):
        """
        Yields tasks as they complete. Accepts either a list or loose positional tasks.
        """
        # FIX: If it's a list or tuple, extract and cast the FIRST element to a mutable list
        if len(tasks) == 1 and isinstance(tasks[0], (list, tuple)):
            pending = list(tasks[0])  # Converts the inner container into a fresh list
        else:
            pending = list(tasks)     # Converts the *tasks tuple into a fresh list

        while pending:
            finished_task = await Task.when_any(pending)
            pending.remove(finished_task)  # Safe to call, because pending is ALWAYS a list!
            yield finished_task

    @classmethod
    def delay(
            cls,
            seconds: float,
            *,
            token: CancellationToken | None = None,
            name: str | None = None,
    ) -> "Task[None]":
        """Return a task completed after seconds without blocking a worker."""
        if seconds < 0:
            raise ValueError("delay must be >= 0")
        if token is not None and not isinstance(token, CancellationToken):
            raise TypeError("token must be a CancellationToken")
        runtime = _get_runtime()
        task: Task[None] = cls(runtime, name=name or f"Delay({seconds:g}s)", token=token)
        # During graceful cancellation, allow an already-running coroutine to
        # create a delay for async cleanup. External callers are still rejected.
        runtime._submit_coroutine(
            task,
            _delay_coroutine(runtime, seconds),
            allow_during_shutdown=runtime.is_runtime_thread(),
        )
        return task

    @classmethod
    def yield_now(cls) -> _YieldNow:
        """Awaitable that lets other ready tasks run."""
        return _YieldNow(_get_runtime())

    @classmethod
    def shutdown(
            cls,
            *,
            grace_timeout: float = 1.0,
            worker_timeout: float = 2.0,
    ) -> ShutdownReport:
        """Stop the singleton runtime and report work that could not be stopped.

        Coroutines receive cancellation and get up to ``grace_timeout`` to unwind.
        Running synchronous worker functions are allowed up to ``worker_timeout``
        to finish; Python cannot forcibly stop them. Pending worker jobs are cancelled.
        The singleton can be lazily recreated by later Task.run calls.
        """
        if grace_timeout < 0 or worker_timeout < 0:
            raise ValueError("shutdown timeouts must be >= 0")
        global _runtime
        with _runtime_lock:
            runtime = _runtime
        if runtime is None:
            return ShutdownReport(True, 0, 0, False)
        report = runtime.shutdown(grace_timeout=grace_timeout, worker_timeout=worker_timeout)
        with _runtime_lock:
            if _runtime is runtime and runtime.closed:
                _runtime = None
        return report

    @property
    def cancellation_token(self) -> CancellationToken:
        return self._token

    def done(self) -> bool:
        return self._completed.is_set()

    def cancelled(self) -> bool:
        return self._completed.is_set() and self._state == self.CANCELLED

    def result(self) -> T:
        """Block an external thread until completion and return/raise the result."""
        if not self.done() and self._runtime.is_runtime_thread():
            raise RuntimeError("Task.result() would block the runtime thread; use 'await task'")
        self._completed.wait()
        return self._raise_or_return()

    def exception(self) -> BaseException | None:
        if not self.done() and self._runtime.is_runtime_thread():
            raise RuntimeError("Task.exception() would block the runtime thread")
        self._completed.wait()
        if self._state == self.CANCELLED:
            raise self._cancellation_exception()
        return self._exception

    def _cancellation_exception(self) -> OperationCanceledError:
        if isinstance(self._exception, OperationCanceledError):
            return self._exception
        return OperationCanceledError(f"{self.name} was cancelled")

    def cancel(self) -> bool:
        """Request cancellation of this Task, independently of other token users."""
        if self.done():
            return False
        try:
            self._runtime._post(lambda: self._cancel_on_runtime(), internal=True)
        except RuntimeShutdownError:
            return False
        return True

    def __await__(self) -> Generator[Any, T, T]:
        if self.done():
            return self._raise_or_return()
        result = yield _WaitTask[T](self._runtime, self)
        return result

    def _raise_or_return(self) -> T:
        if self._state == self.CANCELLED:
            raise self._cancellation_exception()
        if self._state == self.FAILED:
            assert self._exception is not None
            raise self._exception
        if self._state != self.SUCCEEDED:
            raise InvalidStateError(f"{self.name} has not completed")
        return cast(T, self._result)

    def _bind_token(self) -> None:
        if not self._token.can_be_cancelled or self._token_registration is not None:
            return
        self._token_registration = self._token.register(self.cancel)

    def _cancel_on_runtime(self) -> None:
        if self.done():
            return
        self._cancel_requested = True
        self._runtime._detach_wait(self)
        if self._is_promise_task:
            self._finish(
                self.CANCELLED,
                exception=OperationCanceledError(f"{self.name} cancelled"),
            )
        elif not self._running:
            self._runtime._schedule(self, exc=OperationCanceledError(f"{self.name} cancelled"))

    def _finish(
            self,
            state: str,
            result: Any = None,
            exception: BaseException | None = None,
    ) -> None:
        if self.done():
            return
        self._state = state
        self._result = result
        self._exception = exception
        registration = self._token_registration
        self._token_registration = None
        if registration is not None:
            registration.dispose()
        self._completed.set()
        self._runtime._task_completed(self)

    def _step(self) -> None:
        if self.done():
            return
        coroutine = self._coroutine
        if coroutine is None:
            self._finish(self.FAILED, exception=RuntimeError("task has no coroutine"))
            return
        value = self._next_value
        exc = self._next_exception
        self._next_value = None
        self._next_exception = None
        self._running = True
        previous_task = self._runtime._current_task
        self._runtime._current_task = self
        if isinstance(exc, OperationCanceledError):
            self._cancel_requested = False
        try:
            try:
                if exc is not None:
                    yielded = coroutine.throw(exc)
                else:
                    yielded = coroutine.send(value)
            except StopIteration as stop:
                self._finish(self.SUCCEEDED, result=stop.value)
                return
            except OperationCanceledError as cancelled:
                self._finish(self.CANCELLED, exception=cancelled)
                return
            except BaseException as error:
                self._finish(self.FAILED, exception=error)
                return
        finally:
            self._running = False
            self._runtime._current_task = previous_task
        if self._cancel_requested:
            self._runtime._schedule(self, exc=OperationCanceledError(f"{self.name} cancelled"))
            return
        try:
            self._runtime._handle_yielded(self, yielded)
        except BaseException as error:
            self._runtime._detach_wait(self)
            self._runtime._schedule(self, exc=error)

    def __repr__(self) -> str:
        return f"<{self.name} state={self._state}>"


class TaskCompletionSource(Generic[T]):
    """Externally controlled producer for a stable, awaitable ``Task[T]``.

    The source can complete its task with a result, exception, cancellation, or
    the terminal outcome of an already-completed task. Completion methods are
    safe to call from arbitrary threads. Exactly one terminal transition wins.

    ``state`` is carried by the task as ``task.async_state`` for diagnostics and
    callback-to-task adapters. ``set_result()`` without a value is allowed for
    the non-generic-style use case and completes with ``None``.
    """

    def __init__(self, state: Any = None) -> None:
        runtime = _get_runtime()
        self._runtime = runtime
        self._task: Task[T] = Task(runtime)
        self._task._is_promise_task = True
        self._task.async_state = state
        # Promise tasks are tracked so runtime shutdown can cancel unresolved
        # externally-completed tasks and wake any awaiters.
        runtime._call_sync(lambda: runtime._tasks.add(self._task), internal=False)

    @property
    def task(self) -> Task[T]:
        """The stable task controlled by this source."""
        return self._task

    @property
    def Task(self) -> Task[T]:  # .NET-spelling alias for source-porting convenience
        return self._task

    def set_result(self, result: T = cast(T, _MISSING)) -> None:
        if result is _MISSING:
            result = cast(T, None)
        if not self.try_set_result(result):
            raise InvalidStateError("TaskCompletionSource task has already completed")

    def try_set_result(self, result: T = cast(T, _MISSING)) -> bool:
        if result is _MISSING:
            result = cast(T, None)
        return self._try_complete(Task.SUCCEEDED, result=result)

    @staticmethod
    def _normalize_exceptions(
            error: Exception | Iterable[Exception],
    ) -> tuple[Exception, ...] | Exception:
        if isinstance(error, Exception):
            return error
        if error is None:
            raise TypeError("exception must not be None")
        if isinstance(error, (str, bytes, bytearray)):
            raise TypeError("exception must be an Exception or iterable of Exceptions")
        try:
            exceptions = tuple(error)
        except TypeError as exc:
            raise TypeError("exception must be an Exception or iterable of Exceptions") from exc
        if not exceptions:
            raise ValueError("exception iterable must not be empty")
        if not all(isinstance(item, Exception) for item in exceptions):
            raise TypeError("exception iterable must contain only Exception instances")
        return exceptions

    def set_exception(self, error: Exception | Iterable[Exception]) -> None:
        normalized = self._normalize_exceptions(error)
        exception = (
            normalized
            if isinstance(normalized, Exception)
            else AggregateError(normalized)
        )
        if not self._try_complete(Task.FAILED, exception=exception):
            raise InvalidStateError("TaskCompletionSource task has already completed")

    def try_set_exception(self, error: Exception | Iterable[Exception]) -> bool:
        normalized = self._normalize_exceptions(error)
        exception = (
            normalized
            if isinstance(normalized, Exception)
            else AggregateError(normalized)
        )
        return self._try_complete(Task.FAILED, exception=exception)

    def set_canceled(self, token: CancellationToken | None = None) -> None:
        self._validate_token(token)
        cancellation = OperationCanceledError(
            "The task was canceled.", token=token
        )
        if not self._try_complete(Task.CANCELLED, exception=cancellation):
            raise InvalidStateError("TaskCompletionSource task has already completed")

    def try_set_canceled(self, token: CancellationToken | None = None) -> bool:
        self._validate_token(token)
        cancellation = OperationCanceledError(
            "The task was canceled.", token=token
        )
        return self._try_complete(Task.CANCELLED, exception=cancellation)

    @staticmethod
    def _validate_token(token: CancellationToken | None) -> None:
        if token is not None and not isinstance(token, CancellationToken):
            raise TypeError("token must be a CancellationToken or None")

    def set_from_task(self, completed_task: flpit.task.Task[Any]) -> None:
        self._validate_completed_task(completed_task)
        if not self._try_copy_task(completed_task):
            raise InvalidStateError("TaskCompletionSource task has already completed")

    def try_set_from_task(self, completed_task: flpit.task.Task[Any]) -> bool:
        self._validate_completed_task(completed_task)
        return self._try_copy_task(completed_task)

    def _validate_completed_task(self, source: "flpit.task.Task[Any] | None") -> None:
        if source is None:
            raise TypeError("completed_task must not be None")
        if not isinstance(source, Task):
            raise TypeError("completed_task must be a Task instance")
        if not source.done():
            raise ValueError("completed_task must already be completed")

    def _try_copy_task(self, source: "flpit.task.Task[Any]") -> bool:
        if source._state == Task.SUCCEEDED:
            return self._try_complete(Task.SUCCEEDED, result=source._result)
        if source._state == Task.FAILED:
            assert source._exception is not None
            return self._try_complete(Task.FAILED, exception=source._exception)
        if source._state == Task.CANCELLED:
            return self._try_complete(
                Task.CANCELLED,
                exception=source._cancellation_exception(),
            )
        # A terminal state not recognized here would indicate a runtime invariant
        # violation rather than a normal rejected completion.
        raise InvalidStateError(f"Cannot copy task in state {source._state!r}")

    def _try_complete(
            self,
            state: str,
            *,
            result: Any = None,
            exception: Exception | BaseException | None = None,
    ) -> bool:
        if self._task.done():
            return False

        def complete_on_runtime() -> bool:
            if self._task.done():
                return False
            self._task._finish(state, result=result, exception=exception)
            return True

        try:
            return bool(self._runtime._call_sync(complete_on_runtime, internal=True))
        except RuntimeShutdownError:
            # Shutdown may have won the race and completed this promise task as
            # cancelled. In that case TrySet* follows the standard lost-race path.
            if self._task.done():
                return False
            raise


def _normalize_tasks(items: tuple[Any, ...], *, allow_empty: bool) -> tuple[Task[Any], ...]:
    """Normalize task-combinator inputs, scheduling raw awaitables as Tasks.

    Accepts Task instances, coroutine objects, and other awaitables supported by
    this runtime. A single iterable is also accepted. If validation fails,
    coroutine objects supplied to this call are closed so Python does not emit
    "coroutine was never awaited" warnings for rejected inputs.
    """
    # A single awaitable is one operation, not an iterable of operations.
    if (
            len(items) == 1
            and not isinstance(items[0], Task)
            and not inspect.isawaitable(items[0])
            and not isinstance(items[0], (str, bytes, bytearray))
    ):
        candidate = items[0]
        try:
            items = tuple(candidate)
        except TypeError:
            pass

    if not items and not allow_empty:
        raise ValueError("Task.when_any() requires at least one task or awaitable")

    def close_raw_coroutines(values: tuple[Any, ...]) -> None:
        seen: set[int] = set()
        for value in values:
            if inspect.iscoroutine(value) and id(value) not in seen:
                seen.add(id(value))
                try:
                    value.close()
                except BaseException:
                    _LOG.exception("Failed to close rejected coroutine supplied to Task.when_all/when_any")

    # Validate everything before scheduling anything, avoiding partial starts
    # when the caller accidentally mixes a coroutine with a non-awaitable.
    invalid = [item for item in items if not isinstance(item, Task) and not inspect.isawaitable(item)]
    if invalid:
        close_raw_coroutines(items)
        raise TypeError(
            "Task.when_all/when_any accepts Task instances or awaitables; "
            f"got {type(invalid[0]).__name__}"
        )

    # The same one-shot coroutine/awaitable cannot safely be scheduled twice.
    seen_awaitables: set[int] = set()
    for item in items:
        if isinstance(item, Task):
            continue
        identity = id(item)
        if identity in seen_awaitables:
            close_raw_coroutines(items)
            raise ValueError("the same awaitable instance was supplied more than once")
        seen_awaitables.add(identity)

    normalized: list[Task[Any]] = []
    index = 0
    try:
        for index, item in enumerate(items):
            if isinstance(item, Task):
                normalized.append(item)
            else:
                # Task.run takes ownership of the awaitable and schedules it.
                normalized.append(Task.run(item))
    except BaseException:
        # The failed Task.run closes its own coroutine when possible. Close any
        # later coroutine inputs which have not been handed to the runtime.
        close_raw_coroutines(tuple(items[index + 1 :]))
        raise
    return tuple(normalized)


async def _when_all_coroutine(tasks: tuple[Task[T], ...]) -> list[T]:
    await _WaitMany(_get_runtime(), tasks, "all")
    failures = tuple(task._exception for task in tasks if task._state == Task.FAILED)

    if len(failures) == 1:
        assert failures[0] is not None
        raise failures[0]
    if len(failures) > 1:
        raise AggregateError(cast(tuple[Exception, ...], failures))
    if any(task._state == Task.CANCELLED for task in tasks):
        raise OperationCanceledError("One or more tasks passed to Task.when_all() were cancelled")
    return [task._result for task in tasks]


async def _when_any_coroutine(tasks: tuple[Task[T], ...]) -> Task[T]:
    winner = await _WaitMany(_get_runtime(), tasks, "any")
    return cast(Task[Any], winner)


class IO:
    """Selector-backed awaitables for nonblocking sockets."""

    @staticmethod
    def wait_readable(
            sock: socket.socket, *, token: CancellationToken | None = None
    ) -> _WaitIO:
        if token is not None and not isinstance(token, CancellationToken):
            raise TypeError("token must be a CancellationToken")
        return _WaitIO(_get_runtime(), sock, "read", token)

    @staticmethod
    def wait_writable(
            sock: socket.socket, *, token: CancellationToken | None = None
    ) -> _WaitIO:
        if token is not None and not isinstance(token, CancellationToken):
            raise TypeError("token must be a CancellationToken")
        return _WaitIO(_get_runtime(), sock, "write", token)


class _Runtime:
    """Private singleton scheduler: ready queue + timers + selector + workers."""

    def __init__(self, *, max_workers: int, max_pending_background: int) -> None:
        self._selector = selectors.DefaultSelector()
        self._wake_reader, self._wake_writer = socket.socketpair()
        self._wake_reader.setblocking(False)
        self._wake_writer.setblocking(False)
        self._selector.register(self._wake_reader, selectors.EVENT_READ, data=_WAKE)
        self._ready: deque[Task[Any]] = deque()
        self._tasks: set[Task[Any]] = set()
        self._timers: list[tuple[float, int, Task[Any], _Sleep]] = []
        self._timer_sequence = count()
        self._io_waiters: dict[socket.socket, dict[str, set[Task[Any]]]] = {}
        self._commands: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._max_workers = max_workers
        self._max_pending_background = max_pending_background
        self._pending_background: deque[tuple[Task[Any], _BackgroundCall]] = deque()
        self._background_active = 0  # scheduler-thread-owned submitted call count
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Thread")
        self._inflight_lock = threading.Condition()
        self._inflight_futures: set[Future[Any]] = set()
        self._current_task: Task[Any] | None = None
        self._thread_id: int | None = None
        self._start_lock = threading.Lock()
        self._started = threading.Event()
        self._state_lock = threading.RLock()
        self._shutdown_requested = False
        self._shutdown_deadline: float | None = None
        self._stopping = False
        self._closed = False
        self._shutdown_tasks_cancelled = 0
        self._thread: threading.Thread | None = None
        self._exception_handler: Callable[[dict[str, Any]], Any] | None = None

    @property
    def closed(self) -> bool:
        with self._state_lock:
            return self._closed

    def _ensure_started(self) -> None:
        if self._started.is_set():
            return
        with self._start_lock:
            if self._started.is_set():
                return
            with self._state_lock:
                if self._closed or self._shutdown_requested:
                    raise RuntimeShutdownError("Task runtime is shutting down")
            self._thread = threading.Thread(target=self._loop, name="Task-runtime", daemon=True)
            self._thread.start()
            self._started.wait()

    def is_runtime_thread(self) -> bool:
        return self._thread_id == threading.get_ident()

    def set_exception_handler(self, handler: Callable[[dict[str, Any]], Any] | None) -> None:
        self._exception_handler = handler

    def _report_exception(self, context: dict[str, Any], error: BaseException) -> None:
        handler = self._exception_handler
        if handler is not None:
            try:
                handler({**context, "exception": error})
                return
            except Exception:
                _LOG.exception("Task exception handler itself failed")
        message = str(context.get("message", "Unexpected Task runtime error"))
        _LOG.error("%s", message, exc_info=(type(error), error, error.__traceback__))

    def _call_sync(self, callback: Callable[[], T], *, internal: bool = False) -> T:
        """Run a small state mutation on the scheduler thread and return its value.

        External completion APIs use this so callbacks/awaiters are manipulated
        only by the scheduler thread while callers retain synchronous Set/TrySet
        semantics. The operation fails rather than hanging if the runtime stops.
        """
        self._ensure_started()
        if self.is_runtime_thread():
            return callback()

        completed = threading.Event()
        outcome: dict[str, Any] = {}

        def invoke() -> None:
            try:
                outcome["value"] = callback()
            except BaseException as error:
                outcome["error"] = error
            finally:
                completed.set()

        self._post(invoke, internal=internal)
        while not completed.wait(0.05):
            thread = self._thread
            if thread is None or not thread.is_alive():
                raise RuntimeShutdownError(
                    "Task runtime stopped before the scheduled operation ran"
                )
        if "error" in outcome:
            raise outcome["error"]
        return cast(T, outcome.get("value"))

    def _post(self, callback: Callable[[], None], *, internal: bool = False) -> None:
        self._ensure_started()
        execute_inline = False
        with self._state_lock:
            if self._closed or self._stopping or (self._shutdown_requested and not internal):
                raise RuntimeShutdownError("Task runtime is shutting down")
            if self.is_runtime_thread():
                execute_inline = True
            else:
                self._commands.put(callback)
        if execute_inline:
            callback()
            return
        try:
            self._wake_writer.send(b"\x00")
        except (BlockingIOError, OSError):
            # A full wake-up socket already guarantees selector readability.
            pass

    def _submit(self, task: Task[Any], work: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        try:
            self._post(lambda: self._start_target(task, work, args, kwargs))
        except BaseException:
            if inspect.iscoroutine(work):
                work.close()
            raise

    def _submit_coroutine(
            self,
            task: Task[Any],
            coroutine: Coroutine[Any, Any, Any],
            *,
            allow_during_shutdown: bool = False,
    ) -> None:
        try:
            self._post(
                lambda: self._start_coroutine(task, coroutine),
                internal=allow_during_shutdown,
            )
        except BaseException:
            coroutine.close()
            raise

    def _start_target(
            self, task: Task[Any], work: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        if task.done():
            if inspect.iscoroutine(work):
                work.close()
            return
        if task._token.is_cancellation_requested:
            if inspect.iscoroutine(work):
                work.close()
            task._finish(Task.CANCELLED, exception=OperationCanceledError(f"{task.name} cancelled before start"))
            return
        try:
            call_kwargs = dict(kwargs)
            if task._pass_token:
                call_kwargs["token"] = task._token
            if inspect.isawaitable(work):
                coroutine = work if inspect.iscoroutine(work) else _await_any(work)
            elif _is_async_callable(work):
                coroutine = _invoke_async(work, args, call_kwargs)
            else:
                coroutine = _invoke_background(self, work, args, call_kwargs)
            self._start_coroutine(task, coroutine)
        except BaseException as error:
            self._tasks.add(task)
            task._finish(Task.FAILED, exception=error)

    def _start_coroutine(self, task: Task[Any], coroutine: Coroutine[Any, Any, Any]) -> None:
        if task.done():
            coroutine.close()
            return
        task._coroutine = coroutine
        self._tasks.add(task)
        task._bind_token()
        self._schedule(task)

    def _schedule(
            self, task: Task[Any], value: Any = None, exc: BaseException | None = None
    ) -> None:
        if task.done():
            return
        if task._queued:
            if exc is not None:
                task._next_exception = exc
                task._next_value = None
            elif task._next_exception is None:
                task._next_value = value
            return
        task._queued = True
        task._next_value = value
        task._next_exception = exc
        self._ready.append(task)

    def _task_completed(self, task: Task[Any]) -> None:
        self._tasks.discard(task)
        if self._shutdown_requested and task._state == Task.CANCELLED:
            self._shutdown_tasks_cancelled += 1
        self._detach_wait(task)
        for waiter in list(task._awaiters):
            operation = waiter._waiting_on
            if isinstance(operation, _WaitTask) and operation.task is task:
                self._detach_wait(waiter)
                if task._state == Task.SUCCEEDED:
                    self._schedule(waiter, value=task._result)
                elif task._state == Task.CANCELLED:
                    self._schedule(waiter, exc=OperationCanceledError(f"{task.name} was cancelled"))
                else:
                    assert task._exception is not None
                    self._schedule(waiter, exc=task._exception)
            elif isinstance(operation, _WaitMany) and task in operation.tasks:
                if operation.mode == "any":
                    self._detach_wait(waiter)
                    self._schedule(waiter, value=task)
                elif all(child.done() for child in operation.tasks):
                    self._detach_wait(waiter)
                    self._schedule(waiter, value=operation.tasks)
        task._awaiters.clear()

    def _handle_yielded(self, task: Task[Any], yielded: Any) -> None:
        if not isinstance(yielded, _Operation):
            raise RuntimeError(
                f"{task.name} yielded unsupported object {yielded!r}; "
                "this runtime only supports Task awaitables"
            )
        if yielded.runtime is not self:
            raise RuntimeError("awaitable belongs to a different runtime")
        if yielded.token.is_cancellation_requested:
            self._schedule(task, exc=OperationCanceledError("Operation token was cancelled"))
            return

        if isinstance(yielded, _YieldNow):
            self._schedule(task)
        elif isinstance(yielded, _Sleep):
            if yielded.delay == 0:
                self._schedule(task)
            else:
                task._waiting_on = yielded
                heapq.heappush(self._timers, (yielded.deadline, next(self._timer_sequence), task, yielded))
                self._register_operation_token(task, yielded)
        elif isinstance(yielded, _WaitIO):
            self._arm_io(task, yielded)
            self._register_operation_token(task, yielded)
        elif isinstance(yielded, _WaitMany):
            if yielded.mode == "any":
                # Deterministic tie-breaking for tasks already completed when
                # the operation is first observed: first completed in input order.
                winner = next((child for child in yielded.tasks if child.done()), None)
                if winner is not None:
                    self._schedule(task, value=winner)
                    return
            elif all(child.done() for child in yielded.tasks):
                self._schedule(task, value=yielded.tasks)
                return

            pending = [child for child in yielded.tasks if not child.done()]
            if any(child._runtime is not self for child in pending):
                raise RuntimeError("cannot combine pending tasks from different runtimes")
            task._waiting_on = yielded
            for child in pending:
                child._awaiters.add(task)
        elif isinstance(yielded, _WaitTask):
            target = yielded.task
            if target is task:
                raise RuntimeError("a task cannot await itself")
            if target.done():
                if target._state == Task.SUCCEEDED:
                    self._schedule(task, value=target._result)
                elif target._state == Task.CANCELLED:
                    self._schedule(task, exc=OperationCanceledError(f"{target.name} was cancelled"))
                else:
                    assert target._exception is not None
                    self._schedule(task, exc=target._exception)
            else:
                task._waiting_on = yielded
                target._awaiters.add(task)
                self._register_operation_token(task, yielded)
        elif isinstance(yielded, _BackgroundCall):
            task._waiting_on = yielded
            if self._background_active < self._max_workers and not self._pending_background:
                self._start_background(task, yielded)
            elif len(self._pending_background) < self._max_pending_background:
                self._pending_background.append((task, yielded))
                self._register_operation_token(task, yielded)
            else:
                task._waiting_on = None
                raise BackgroundQueueFull(
                    f"background queue is full (max_workers={self._max_workers}, "
                    f"max_pending_background={self._max_pending_background})"
                )
        else:
            raise RuntimeError(f"unsupported operation type: {type(yielded).__name__}")

    def _register_operation_token(self, task: Task[Any], operation: _Operation) -> None:
        token = operation.token
        if not token.can_be_cancelled:
            return

        def on_cancel() -> None:
            try:
                self._post(lambda: self._cancel_operation_wait(task, operation), internal=True)
            except RuntimeShutdownError:
                pass

        operation._token_registration = token.register(on_cancel)

    def _dispose_operation_token(self, operation: _Operation) -> None:
        registration = operation._token_registration
        operation._token_registration = None
        if registration is not None:
            registration.dispose()

    def _cancel_operation_wait(self, task: Task[Any], operation: _Operation) -> None:
        if task.done() or task._waiting_on is not operation:
            return
        self._detach_wait(task)
        self._schedule(task, exc=OperationCanceledError("Operation token was cancelled"))

    def _start_background(self, task: Task[Any], operation: _BackgroundCall) -> None:
        if task.done() or task._waiting_on is not operation or self._shutdown_requested:
            return
        self._background_active += 1
        operation._counted_active = True
        try:
            future = self._executor.submit(operation.function, *operation.args, **operation.kwargs)
        except BaseException as error:
            self._background_active -= 1
            operation._counted_active = False
            task._waiting_on = None
            self._dispose_operation_token(operation)
            self._schedule(task, exc=error)
            self._pump_background_queue()
            return
        operation.future = future
        with self._inflight_lock:
            self._inflight_futures.add(future)
        future.add_done_callback(
            lambda completed, task=task, op=operation: self._background_worker_done(task, op, completed)
        )

    def _background_worker_done(
            self, task: Task[Any], operation: _BackgroundCall, future: Future[Any]
    ) -> None:
        with self._inflight_lock:
            self._inflight_futures.discard(future)
            self._inflight_lock.notify_all()
        try:
            self._post(lambda: self._background_finished(task, operation, future), internal=True)
        except RuntimeShutdownError:
            # The future's terminal state is still recorded in _inflight_futures;
            # after shutdown there is no scheduler left to resume a task.
            pass

    def _background_finished(
            self, task: Task[Any], operation: _BackgroundCall, future: Future[Any]
    ) -> None:
        if operation._counted_active:
            operation._counted_active = False
            self._background_active = max(0, self._background_active - 1)
        if not task.done() and task._waiting_on is operation:
            task._waiting_on = None
            self._dispose_operation_token(operation)
            try:
                value = future.result()
            except BaseException as error:
                self._schedule(task, exc=error)
            else:
                self._schedule(task, value=value)
        self._pump_background_queue()

    def _pump_background_queue(self) -> None:
        if self._shutdown_requested:
            return
        while self._background_active < self._max_workers and self._pending_background:
            task, operation = self._pending_background.popleft()
            if task.done() or task._waiting_on is not operation:
                continue
            self._dispose_operation_token(operation)
            self._start_background(task, operation)

    def _arm_io(self, task: Task[Any], operation: _WaitIO) -> None:
        if operation.sock.fileno() < 0:
            raise ValueError("cannot wait on a closed socket")
        task._waiting_on = operation
        sides = self._io_waiters.setdefault(operation.sock, {"read": set(), "write": set()})
        sides[operation.mode].add(task)
        self._refresh_socket(operation.sock)

    def _refresh_socket(self, sock: socket.socket) -> None:
        sides = self._io_waiters.get(sock)
        mask = 0
        if sides:
            if sides["read"]:
                mask |= selectors.EVENT_READ
            if sides["write"]:
                mask |= selectors.EVENT_WRITE
        try:
            self._selector.get_key(sock)
            registered = True
        except (KeyError, ValueError, OSError):
            registered = False
        try:
            if mask:
                if registered:
                    self._selector.modify(sock, mask, data=None)
                else:
                    self._selector.register(sock, mask, data=None)
            else:
                if registered:
                    try:
                        self._selector.unregister(sock)
                    except (KeyError, ValueError, OSError):
                        pass
                self._io_waiters.pop(sock, None)
        except (KeyError, ValueError, OSError) as error:
            # A socket may be closed while tasks are waiting on it. Fail those
            # waits instead of allowing a selector error to kill the scheduler.
            sides = self._io_waiters.pop(sock, None) or {"read": set(), "write": set()}
            affected = set(sides["read"]) | set(sides["write"])
            for task in affected:
                operation = task._waiting_on
                if isinstance(operation, _WaitIO) and operation.sock is sock:
                    task._waiting_on = None
                    self._dispose_operation_token(operation)
                    self._schedule(task, exc=error)
            try:
                self._selector.unregister(sock)
            except (KeyError, ValueError, OSError):
                pass

    def _detach_wait(self, task: Task[Any]) -> None:
        operation = task._waiting_on
        if operation is None:
            return
        task._waiting_on = None
        self._dispose_operation_token(operation)
        if isinstance(operation, _WaitIO):
            sides = self._io_waiters.get(operation.sock)
            if sides is not None:
                sides[operation.mode].discard(task)
                self._refresh_socket(operation.sock)
        elif isinstance(operation, _WaitTask):
            operation.task._awaiters.discard(task)
        elif isinstance(operation, _WaitMany):
            for target in operation.tasks:
                target._awaiters.discard(task)
        elif isinstance(operation, _BackgroundCall):
            if operation.future is None:
                try:
                    self._pending_background.remove((task, operation))
                except ValueError:
                    pass
            else:
                # This cancels queued executor work where possible. If already
                # running, the worker continues and remains tracked until it exits.
                operation.future.cancel()
        # Timer entries are lazily discarded when they reach the heap's top.

    def _drain_wakeup(self) -> None:
        while True:
            try:
                if not self._wake_reader.recv(4096):
                    break
            except BlockingIOError:
                break
            except OSError:
                break
        while True:
            try:
                callback = self._commands.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except BaseException as error:
                self._report_exception(
                    {"message": "Unhandled exception in Task scheduler callback", "callback": callback},
                    error,
                )

    def _process_events(self, events: list[tuple[selectors.SelectorKey, int]]) -> None:
        for key, mask in events:
            if key.data is _WAKE:
                self._drain_wakeup()
                continue
            sock: Any = key.fileobj
            sides = self._io_waiters.get(sock)
            if sides is None:
                continue
            to_wake: set[Task[Any]] = set()
            if mask & selectors.EVENT_READ:
                to_wake.update(sides["read"])
                sides["read"].clear()
            if mask & selectors.EVENT_WRITE:
                to_wake.update(sides["write"])
                sides["write"].clear()
            for task in to_wake:
                operation = task._waiting_on
                if isinstance(operation, _WaitIO) and operation.sock is sock:
                    task._waiting_on = None
                    self._dispose_operation_token(operation)
                    self._schedule(task)
            self._refresh_socket(sock)

    def _expire_timers(self) -> None:
        now = time.monotonic()
        while self._timers and self._timers[0][0] <= now:
            _, _, task, operation = heapq.heappop(self._timers)
            if task.done() or task._waiting_on is not operation:
                continue
            task._waiting_on = None
            self._dispose_operation_token(operation)
            self._schedule(task)

    def _next_timeout(self) -> float | None:
        max_selector_wait = 24 * 60 * 60  # 24 hours, in seconds

        while self._timers:
            deadline, _, task, operation = self._timers[0]
            if task.done() or task._waiting_on is not operation:
                heapq.heappop(self._timers)
            else:
                remaining = max(0.0, deadline - time.monotonic())
                return min(remaining, max_selector_wait)

        return None

    def _begin_shutdown(self) -> None:
        self._shutdown_deadline = time.monotonic() + self._shutdown_grace
        for task in list(self._tasks):
            task._cancel_on_runtime()
        # Anything waiting in our bounded background queue is removed as its
        # task receives cancellation. Do not admit more background work at shutdown.

    def _loop(self) -> None:
        self._thread_id = threading.get_ident()
        self._started.set()
        try:
            while not self._stopping:
                self._drain_wakeup()
                if self._shutdown_requested:
                    if not self._tasks:
                        self._stopping = True
                    elif self._shutdown_deadline is not None and time.monotonic() >= self._shutdown_deadline:
                        self._stopping = True
                while self._ready and not self._stopping:
                    task = self._ready.popleft()
                    task._queued = False
                    task._step()
                    self._drain_wakeup()
                    if self._shutdown_requested:
                        if not self._tasks:
                            self._stopping = True
                        elif self._shutdown_deadline is not None and time.monotonic() >= self._shutdown_deadline:
                            self._stopping = True
                self._expire_timers()
                if self._stopping:
                    break
                if self._ready:
                    continue
                try:
                    events = self._selector.select(self._next_timeout())
                except (OSError, ValueError) as error:
                    if self._stopping or self.closed:
                        break
                    self._report_exception(
                        {"message": "Selector failed; stopping Task runtime"}, error
                    )
                    self._stopping = True
                    break
                try:
                    self._process_events(events)
                except BaseException as error:
                    self._report_exception(
                        {"message": "Unhandled error while processing selector events"}, error
                    )
                    self._stopping = True
        except BaseException as error:
            self._report_exception({"message": "Fatal error in Task scheduler loop"}, error)
            self._stopping = True
        finally:
            # Stop accepting work before releasing scheduler resources. The
            # closed flag is published after cleanup, so new runtimes do not
            # overlap this runtime's resource finalization.
            tasks = list(self._tasks)
            for task in tasks:
                self._detach_wait(task)
            for task in tasks:
                coroutine = task._coroutine
                if coroutine is not None:
                    try:
                        coroutine.close()
                    except BaseException as error:
                        self._report_exception(
                            {"message": f"Error closing coroutine for {task.name}"}, error
                        )
                task._finish(Task.CANCELLED, exception=OperationCanceledError("runtime shutting down"))
            # Remove scheduler-owned pending calls; they have never entered a worker.
            self._pending_background.clear()
            try:
                self._selector.close()
            except BaseException as error:
                self._report_exception({"message": "Error closing selector"}, error)
            for wake_socket in (self._wake_reader, self._wake_writer):
                try:
                    wake_socket.close()
                except OSError:
                    pass
            with self._state_lock:
                self._closed = True

    def shutdown(self, *, grace_timeout: float, worker_timeout: float) -> ShutdownReport:
        if self.is_runtime_thread():
            raise RuntimeError("Task.shutdown() cannot block from the runtime thread")
        with self._state_lock:
            if self._closed:
                thread = self._thread
            else:
                self._shutdown_requested = True
                self._shutdown_grace = grace_timeout
                self._commands.put(self._begin_shutdown)
                thread = self._thread
        try:
            self._wake_writer.send(b"\x00")
        except (BlockingIOError, OSError):
            pass
        if thread is not None and thread.is_alive():
            # Grace timeout is enforced by the loop; the small allowance lets the
            # loop execute its finalizer after the deadline.
            thread.join(timeout=grace_timeout + 1.0)
        runtime_stopped = thread is None or not thread.is_alive()
        if not runtime_stopped:
            self._report_exception(
                {"message": "Task scheduler thread did not stop before timeout"},
                TimeoutError("scheduler shutdown timed out"),
            )

        # Cancel executor-queued calls. Already-running functions are not killable.
        self._executor.shutdown(wait=False, cancel_futures=True)
        worker_deadline = time.monotonic() + worker_timeout
        with self._inflight_lock:
            while self._inflight_futures:
                remaining = worker_deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._inflight_lock.wait(remaining)
            workers_still_running = len(self._inflight_futures)
        if workers_still_running == 0:
            # It is now safe to join worker threads without an unbounded wait.
            self._executor.shutdown(wait=True, cancel_futures=True)
        return ShutdownReport(
            runtime_stopped=runtime_stopped,
            tasks_cancelled=self._shutdown_tasks_cancelled,
            workers_still_running=workers_still_running,
            timed_out=(not runtime_stopped or workers_still_running > 0),
        )


def _is_async_callable(value: Any) -> bool:
    if inspect.iscoroutinefunction(value):
        return True
    call = getattr(value, "__call__", None)
    return inspect.iscoroutinefunction(call)


_runtime_lock = threading.RLock()
_runtime: _Runtime | None = None
_runtime_config: dict[str, int] = {
    "max_workers": min(32, (os.cpu_count() or 1) + 4),
    "max_pending_background": 128,
}


def _get_runtime() -> _Runtime:
    global _runtime
    with _runtime_lock:
        if _runtime is None or _runtime.closed:
            _runtime = _Runtime(**_runtime_config)
        runtime = _runtime
    runtime._ensure_started()
    return runtime


def _shutdown_at_exit() -> None:
    try:
        Task.shutdown(grace_timeout=0.2, worker_timeout=0.2)
    except BaseException:
        _LOG.exception("Error during Task interpreter shutdown")


atexit.register(_shutdown_at_exit)


@overload
def task[**P, T](
        function: Callable[P, Awaitable[T]]
) -> Callable[P, Task[T]]: ...

@overload
def task[**P, T](
        function: Callable[P, T]
) -> Callable[P, Task[T]]: ...

def task(function: Callable[..., Any]) -> Callable[..., Task[Any]]:
    """
    | Wraps sync functions and non-asyncio dependent coroutines to eagerly executed await-able tasks
    """
    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Task[Any]:
        return Task.run(function, *args, **kwargs)

    return wrapper


@overload
def asyncio_task[**P, T](
        async_function: Callable[P, Awaitable[T]]
) -> Callable[P, Task[T]]: ...

@overload
def asyncio_task[**P, T](
        async_function: Callable[P, T], /
) -> Callable[P, Task[T]]: ...

def asyncio_task(async_function: Callable[..., Any]) -> Callable[..., Task[Any]]:
    """
    | Wraps async functions with a dependency on asyncio to be compatible with Task.run(coro)

    Use with caution as this transfers execution control to an isolated asyncio loop runner.
    """
    import asyncio
    @functools.wraps(async_function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with asyncio.Runner() as runner:
            # Call the function with its arguments to generate the Coroutine object instance
            coro = async_function(*args, **kwargs)
            return runner.run(coro)

    return task(wrapper)


class _SyncBridge:
    def __rshift__(self, ttwa: Task[T]) -> T:
        frame = inspect.currentframe()
        try:
            assert frame is not None
            caller: Any = frame.f_back
            if caller and caller.f_code.co_flags & inspect.CO_COROUTINE:
                raise RuntimeError("twait >> cannot be used inside async def")

            return ttwa.result()
        finally:
            del frame


twait: Final = _SyncBridge()
"""
| If you seriously want to await in a sync context make it nice

twait >> Task.delay()
"""