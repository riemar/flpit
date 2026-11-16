"""Task: a small asyncio-free task/awaitable runtime.

Although it's asyncio free, it can cooperate / co-exist with asyncio.

Public API
----------
    Task.configure(min_workers=8, max_workers=64)
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

Execution model
---------------
The runtime follows the .NET thread-pool model rather than an event loop:

* Coroutines and synchronous callables both execute on pool worker threads.
  A coroutine may resume on a different worker after every ``await``.
* There is no scheduler thread between two steps of a coroutine. Completing a
  task hands its continuations straight to the pool; awaiting an already
  completed task continues inline without leaving the worker.
* A single timer thread and (only when sockets are awaited) a single selector
  thread turn deadlines and socket readiness into completions. Neither of them
  ever runs coroutine code.
* The pool creates workers on demand up to ``min_workers``. Beyond that it
  injects further workers, up to ``max_workers``, when queued work makes no
  progress or when workers are blocked in ``Task.result()``.
* ``Task.result()`` called on a worker for a task that has not started yet
  runs that task inline on the calling worker instead of blocking.

With the GIL only one worker runs Python code at a time, exactly like any
other threaded program. On free-threaded builds (3.13t and later) workers run
in parallel; no state is funnelled through a single thread.

Cancellation is cooperative for coroutines and worker functions. A worker can
receive the same token with pass_token=True and should check it between units
of work. Python cannot safely force-stop an arbitrary running thread.
"""
from __future__ import annotations

import sys
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
import warnings
import weakref
from collections import deque
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass
from itertools import count
from types import CoroutineType, FunctionType, MethodType
from typing import Any, Generic, TypeVar, cast, Iterable, Final, overload
import functools
from functools import wraps
from collections.abc import Awaitable, Callable, Coroutine
from contextvars import Context, copy_context
from .threading import AsyncLocal, _run_with_context

import flpit

T = TypeVar("T")
_LOG = logging.getLogger("task")
_MISSING = object()
_WAKE = object()

_PENDING: Final = "pending"
_SUCCEEDED: Final = "succeeded"
_FAILED: Final = "failed"
_CANCELLED: Final = "cancelled"


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
    """No longer raised: the work queue is unbounded, as in the .NET thread pool.

    Kept so that existing ``except BackgroundQueueFull`` clauses keep importing.
    """


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


class _TaskMeta(type):

    @property
    def asyncio_interop(cls: "_TaskMeta") -> bool:
        return (
                getattr(cls, "__await__")
                is getattr(cls, "_await_asyncio_interop")
        )

    @asyncio_interop.setter
    def asyncio_interop(
            cls: "_TaskMeta",
            enabled: bool,
    ) -> None:
        implementation = getattr(
            cls,
            "_await_asyncio_interop"
            if enabled
            else "_await_pure_flpit_task",
        )
        setattr(cls, "__await__", implementation)


@dataclass(frozen=True)
class ShutdownReport:
    """Outcome of a runtime shutdown request."""

    runtime_stopped: bool
    tasks_cancelled: int
    workers_still_running: int
    timed_out: bool


class _ThreadState(threading.local):
    """Per-thread scheduling state. Class attributes are the defaults."""

    # The pool this thread works for, or None for foreign threads.
    pool: "_WorkerPool | None" = None
    # Work the worker runs next, without a round trip through the shared queue.
    slot: Callable[[], None] | None = None
    # True while a worker is between two work items (after user code returned).
    tail: bool = False
    # Consecutive slot hand-offs; bounded so queued work is not starved.
    streak: int = 0
    # True on the timer and selector threads, which must never block on a Task.
    internal: bool = False
    # Nesting depth of completions that run continuations on this thread.
    depth: int = 0
    # Nesting depth of tasks run inline by Task.result() on this thread.
    inline: int = 0


_thread_state = _ThreadState()

# A worker may keep feeding itself continuations this many times before it
# has to go back to the shared queue.
_MAX_SLOT_STREAK: Final = 64

# Completing a task can complete an aggregate (when_all/when_any), which can
# complete another one, and so on, all on one stack. Past this depth the
# remaining continuations are handed to the pool instead (.NET guards its
# synchronous continuations against deep stacks in the same way).
_MAX_COMPLETION_DEPTH: Final = 24

# Task.result() on a worker runs a not-yet-started task inline, and that task
# may do the same with another one. Past this depth the worker blocks instead
# (.NET stops inlining when the stack is running low).
_MAX_INLINE_DEPTH: Final = 32


class _TimerHandle:
    """Cancellable entry in the timer queue."""

    __slots__ = ("_queue", "_callback")

    def __init__(self, timer_queue: "_TimerQueue", callback: Callable[[], Any]) -> None:
        self._queue = timer_queue
        self._callback: Callable[[], Any] | None = callback

    def cancel(self) -> None:
        if self._callback is not None:
            self._queue._cancel(self)


class _TimerQueue:
    """One daemon thread serving every deadline in the process.

    Used for ``Task.delay`` and ``CancellationTokenSource.cancel_after``, which
    previously cost a scheduler round trip and one OS thread per timer
    respectively. Callbacks run on the timer thread and must not block; the
    runtime's own callbacks only complete a task or queue work to the pool.
    """

    # Condition.wait() cannot take arbitrarily large timeouts.
    _MAX_WAIT: Final = 24 * 60 * 60.0

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._heap: list[tuple[float, int, _TimerHandle]] = []
        self._sequence = 0
        self._cancelled = 0
        self._thread: threading.Thread | None = None

    def schedule(self, delay: float, callback: Callable[[], Any]) -> _TimerHandle:
        handle = _TimerHandle(self, callback)
        deadline = time.monotonic() + delay
        with self._condition:
            heap = self._heap
            if self._cancelled > 64 and self._cancelled * 2 > len(heap):
                # Mostly dead entries (timeouts that were cancelled early):
                # rebuild so they do not pin memory until their deadline.
                heap = [entry for entry in heap if entry[2]._callback is not None]
                heapq.heapify(heap)
                self._heap = heap
                self._cancelled = 0
            self._sequence += 1
            heapq.heappush(heap, (deadline, self._sequence, handle))
            thread = self._thread
            if thread is None or not thread.is_alive():
                thread = threading.Thread(
                    target=self._run, name="Task-timer", daemon=True, **_fresh_context()
                )
                self._thread = thread
                thread.start()
            elif heap[0][2] is handle:
                self._condition.notify()
        return handle

    def _cancel(self, handle: _TimerHandle) -> None:
        with self._condition:
            if handle._callback is not None:
                handle._callback = None
                self._cancelled += 1

    def _run(self) -> None:
        _thread_state.internal = True
        condition = self._condition
        due: list[Callable[[], Any]] = []
        while True:
            with condition:
                while True:
                    heap = self._heap
                    now = time.monotonic()
                    while heap:
                        deadline, _, handle = heap[0]
                        callback = handle._callback
                        if callback is None:
                            heapq.heappop(heap)
                            self._cancelled -= 1
                        elif deadline <= now:
                            heapq.heappop(heap)
                            handle._callback = None
                            due.append(callback)
                        else:
                            break
                    if due:
                        break
                    if heap:
                        condition.wait(min(heap[0][0] - now, self._MAX_WAIT))
                    else:
                        condition.wait()
            for callback in due:
                try:
                    callback()
                except BaseException:
                    _LOG.exception("Unhandled exception in Task timer callback")
            due.clear()


def _fresh_context() -> dict[str, Any]:
    """Thread() arguments that give a runtime thread an empty context.

    From Python 3.14 a new thread may inherit the context of the thread that
    happened to start it (the default on free-threaded builds). A pool thread
    started from inside a task would then keep that task's AsyncLocal values
    alive and observe them as its own.
    """
    if sys.version_info >= (3, 14):
        return {"context": Context()}
    return {}


_timers = _TimerQueue()


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

    __slots__ = ("_state", "_key")

    def __init__(self, state: _CancellationState | None, key: int | None) -> None:
        self._state = state
        self._key = key

    def dispose(self) -> None:
        # Needs no lock of its own: unregistering is idempotent, so two racing
        # dispose() calls are harmless.
        state = self._state
        if state is not None:
            self._state = None
            key = self._key
            if key is not None:
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
        # A single attribute read; cancellation is a one-way False -> True
        # transition, so polling it in a worker loop needs no lock.
        state = self._state
        return state is not None and state.cancelled

    def throw_if_cancellation_requested(self) -> None:
        if self.is_cancellation_requested:
            raise OperationCanceledError("Cancellation was requested", token=self)

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
        self._timer: _TimerHandle | None = None
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
                if not seconds >= 0:  # also rejects NaN
                    raise ValueError("seconds must be >= 0, -1, or None")
                # Served by the shared timer thread rather than one OS thread
                # per pending timeout. Registered callbacks therefore run on
                # that thread and, as in .NET, are expected to return quickly.
                self._timer = _timers.schedule(seconds, self._cancel_from_timer)
        if old_timer is not None:
            old_timer.cancel()

    def _cancel_from_timer(self) -> None:
        try:
            self.cancel()
        except RuntimeError:
            # The source was disposed concurrently with its timer firing.
            pass
        except AggregateError:
            _LOG.exception("Cancellation callbacks failed after cancel_after() elapsed")

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
    """Instruction yielded by an awaitable and consumed by the worker driving it."""

    __slots__ = ("runtime", "token", "waiter", "_token_registration")

    def __init__(self, runtime: "_Runtime", token: CancellationToken | None = None) -> None:
        self.runtime = runtime
        self.token = token if token is not None else _NONE_TOKEN
        # The task suspended on this operation; set when it parks.
        self.waiter: Task[Any] | None = None
        self._token_registration: CancellationTokenRegistration | None = None

    def __await__(self) -> Generator[Any, Any, Any]:
        result = yield self
        return result


class _YieldNow(_Operation):
    __slots__ = ()


class _WaitIO(_Operation):
    __slots__ = ("sock", "mode")

    def __init__(
            self, runtime: "_Runtime", sock: socket.socket, mode: str,
            token: CancellationToken | None = None,
    ) -> None:
        super().__init__(runtime, token)
        self.sock = sock
        self.mode = mode

    def _on_cancel(self) -> None:
        self.runtime._cancel_wait(self)


class _WaitTask(_Operation):
    """A coroutine awaiting another task. Doubles as that task's continuation."""

    __slots__ = ("task",)

    def __init__(self, runtime: "_Runtime", ttw: "Task[Any]") -> None:
        super().__init__(runtime)
        self.task = ttw

    def __call__(self, completed: "Task[Any]") -> None:
        waiter = self.waiter
        if waiter is not None and waiter._claim(self):
            _resume_from(waiter, completed)
            waiter._runtime._enqueue_task(waiter)

    def __repr__(self) -> str:
        return (
            "<flpit _WaitTask: this await operation requires the "
            "flpit scheduler; enable Task.asyncio_interop to await "
            "flpit Task from asyncio>"
        )


def _resume_from(waiter: "Task[Any]", completed: "Task[Any]") -> None:
    """Store the outcome of ``completed`` as the next value sent into ``waiter``.

    Only called by the thread that currently owns ``waiter`` (see Task._claim).
    """
    state = completed._state
    if state is _SUCCEEDED:
        waiter._next_value = completed._result
    elif state is _CANCELLED:
        waiter._next_exception = completed._cancellation_exception()
    else:
        waiter._next_exception = completed._exception


def _close_if_coroutine(value: Any) -> None:
    if type(value) is CoroutineType:
        value.close()


async def _await_any(awaitable: Any) -> Any:
    return await awaitable


class Task(Generic[T], metaclass=_TaskMeta):
    """Result-bearing task executed by FlpIt's process-wide thread pool.

    Ownership rule used throughout: at any moment a pending coroutine task is
    owned by exactly one party -- the worker running its current step, the
    pool queue, or the single operation it is parked on. A parked task is
    resumed by whoever wins ``_claim()`` for that operation; everyone else
    backs off. That is what makes completion, cancellation, timers and
    shutdown safe to race against each other without a scheduler thread.
    """

    PENDING = _PENDING
    SUCCEEDED = _SUCCEEDED
    FAILED = _FAILED
    CANCELLED = _CANCELLED

    def __init__(
            self,
            runtime: "_Runtime",
            *,
            token: CancellationToken | None = None,
            capture_context: bool = True,
    ) -> None:
        self._runtime = runtime
        # Guards the state transition, the continuation list and parking.
        self._lock = threading.Lock()
        self._state: str = _PENDING
        self._result: Any = None
        self._exception: BaseException | None = None
        self._continuations: list[Callable[[Task[Any]], Any]] | None = None
        self._done_event: threading.Event | None = None
        # Promise-style tasks never run code and need no execution context.
        self._execution_context: Context | None = (
            copy_context() if capture_context else None
        )
        self._work: tuple[Any, tuple[Any, ...], dict[str, Any]] | None = None
        self._coroutine: Coroutine[Any, Any, Any] | None = None
        self._waiting_on: _Operation | None = None
        self._running = False
        self._sync_running = False
        self._next_value: Any = None
        self._next_exception: BaseException | None = None
        self._cancel_requested = False
        self._token = token if token is not None else _NONE_TOKEN
        self._token_registration: CancellationTokenRegistration | None = None
        self._timer: _TimerHandle | None = None
        self._pass_token = False
        self._is_promise_task = False
        self._name: str | None = None
        self.async_state: Any = None

    @property
    def name(self) -> str:
        name = self._name
        if name is None:
            name = self._name = f"Task-{id(self):x}"
        return name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def status(self) -> str:
        """Current task state: pending, succeeded, failed, or cancelled."""
        return self._state

    @classmethod
    def configure(
            cls,
            *,
            min_workers: int | None = None,
            max_workers: int | None = None,
            max_pending_background: int | None = None,
    ) -> None:
        """Configure worker capacity before the runtime is first started.

        ``min_workers`` is the number of worker threads the pool creates on
        demand without delay (.NET ``ThreadPool.SetMinThreads``).
        ``max_workers`` is the hard upper bound (``SetMaxThreads``). Between
        the two, a worker is added only when queued work makes no progress
        for a while or when workers are blocked in ``Task.result()``.
        (A worker calling ``Task.result()`` on a task that has not started
        runs it inline and does not count as blocked.)

        Passing ``max_workers`` on its own configures a fixed-size pool:
        ``min_workers`` is set to the same value, so that many workers start
        on demand immediately and no more are ever added.

        ``max_pending_background`` is accepted for backwards compatibility and
        ignored: like the .NET thread pool, the work queue is unbounded.
        """
        global _runtime_config
        with _runtime_lock:
            if _runtime is not None and not _runtime.closed:
                raise RuntimeError("Task.configure() must be called before runtime startup")
            config = dict(_runtime_config)
            for label, value in (("min_workers", min_workers), ("max_workers", max_workers)):
                if value is None:
                    continue
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError(f"{label} must be an integer >= 1")
            if max_workers is not None:
                config["max_workers"] = max_workers
                config["min_workers"] = max_workers if min_workers is None else min_workers
            elif min_workers is not None:
                config["min_workers"] = min_workers
            if config["min_workers"] > config["max_workers"]:
                raise ValueError("min_workers must not exceed max_workers")
            if max_pending_background is not None:
                if (
                        isinstance(max_pending_background, bool)
                        or not isinstance(max_pending_background, int)
                        or max_pending_background < 0
                ):
                    raise ValueError("max_pending_background must be an integer >= 0")
                warnings.warn(
                    "max_pending_background is ignored: the Task work queue is unbounded",
                    DeprecationWarning,
                    stacklevel=2,
                )
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
            token: CancellationToken | None = None,
            pass_token: bool = False,
            **kwargs: Any,
    ) -> Task[Any]:
        """Schedule a coroutine/awaitable or ordinary callable on the pool.

        ``token`` controls the Task's cancellation: as in .NET it is checked
        before the work starts. With ``pass_token=True``, that same token is
        also supplied to the target callable as the keyword argument ``token``
        (useful for cooperative worker functions).
        """
        kind = type(work)
        is_coroutine = kind is CoroutineType
        if kind is FunctionType or kind is MethodType:
            pass  # the common case: skip the comparatively slow awaitable check
        elif is_coroutine or inspect.isawaitable(work):
            if args or kwargs or pass_token:
                if is_coroutine:
                    cast(Any, work).close()
                raise TypeError("args/kwargs/pass_token cannot be supplied with an awaitable instance")
        elif not callable(work):
            raise TypeError("Task.run() expects an awaitable or a callable")
        if token is not None and not isinstance(token, CancellationToken):
            if is_coroutine:
                cast(Any, work).close()
            raise TypeError("token must be a CancellationToken")
        if pass_token and token is None:
            if is_coroutine:
                cast(Any, work).close()
            raise ValueError("pass_token=True requires an explicit token")
        runtime = _get_runtime()
        task = cls(runtime, token=token)
        task._pass_token = pass_token
        runtime._submit(task, work, args, kwargs)
        return task

    @classmethod
    def when_all(
            cls,
            *tasks: Awaitable[T]
    ) -> "Task[list[Any]]":
        """Complete when every supplied task completes, preserving input order.

        Accepts Task instances and raw awaitables (including coroutine objects)
        as positional arguments or in one iterable. Raw awaitables are scheduled
        automatically. Child tasks are not cancelled if this
        aggregate task is cancelled. A single child failure is re-raised; if
        several children fail, TaskAggregateError exposes all their exceptions.
        If there are no tasks, the result is an empty list.
        """
        normalized = _normalize_tasks(tasks, allow_empty=True)
        promise: Task[list[Any]] = cls._promise(_get_runtime())
        _WhenAll(promise, normalized).start()
        return promise

    @classmethod
    def when_any(
            cls,
            *tasks: Any,
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
        normalized = _normalize_tasks(tasks, allow_empty=False)
        promise: Task[Task[Any]] = cls._promise(_get_runtime())
        _WhenAny(promise, normalized).start()
        return promise

    @staticmethod
    async def collect(*tasks: Task[Any] | list[Task[Any]]) -> AsyncGenerator[Task[Any], None]:
        """
        Yields tasks as they complete. Accepts either a list or loose positional tasks.
        """
        pending = _normalize_tasks(tasks, allow_empty=True)
        if not pending:
            return

        # Every task reports its own completion exactly once, so the whole
        # stream costs O(n) instead of one when_any over the rest per item.
        runtime = _get_runtime()
        lock = threading.Lock()
        completed: deque[Task[Any]] = deque()
        signal: list[Task[None] | None] = [None]

        def on_completed(finished: Task[Any]) -> None:
            with lock:
                completed.append(finished)
                waiter = signal[0]
                signal[0] = None
            if waiter is not None:
                waiter._finish(_SUCCEEDED)

        for item in pending:
            if not item._add_continuation(on_completed):
                on_completed(item)

        for _ in range(len(pending)):
            while True:
                with lock:
                    if completed:
                        finished = completed.popleft()
                        break
                    waiter = signal[0] = Task(runtime, capture_context=False)
                    waiter._is_promise_task = True
                await waiter
            yield finished

    @classmethod
    def delay(
            cls,
            seconds: float,
            *,
            token: CancellationToken | None = None,
    ) -> "Task[None]":
        """Return a task completed after seconds without blocking a worker."""
        if not seconds >= 0:  # also rejects NaN
            raise ValueError("delay must be >= 0")
        if token is not None and not isinstance(token, CancellationToken):
            raise TypeError("token must be a CancellationToken")
        # During graceful cancellation, allow an already-running coroutine to
        # create a delay for async cleanup. External callers are still rejected.
        task: Task[None] = cls._promise(
            _get_runtime(),
            token=token,
            internal=_current_task.value is not None,
        )
        if token is not None and token.is_cancellation_requested:
            task._delay_cancelled()
        elif seconds == 0:
            task._finish(_SUCCEEDED)
        else:
            # The timer thread completes the task directly; no coroutine and
            # no worker are involved until something awaits the result.
            try:
                task._timer = _timers.schedule(seconds, task._delay_elapsed)
                if token is not None and token.can_be_cancelled:
                    task._token_registration = token.register(task._delay_cancelled)
            except BaseException:
                task._runtime._tasks.discard(task)
                task._release_handles()
                raise
            if task._state is not _PENDING:
                # Completed while the handles were being attached.
                task._release_handles()
        return task

    @classmethod
    def _promise(
            cls,
            runtime: "_Runtime",
            *,
            token: CancellationToken | None = None,
            internal: bool = False,
    ) -> "Task[Any]":
        """Create a tracked task that is completed externally, not executed."""
        task: Task[Any] = cls(runtime, token=token, capture_context=False)
        task._is_promise_task = True
        runtime._track(task, internal=internal)
        return task

    def _delay_elapsed(self) -> None:
        self._finish(_SUCCEEDED)

    def _delay_cancelled(self) -> None:
        self._finish(
            _CANCELLED,
            exception=OperationCanceledError("Operation token was cancelled", token=self._token),
        )

    def _release_handles(self) -> None:
        with self._lock:
            registration = self._token_registration
            self._token_registration = None
            timer = self._timer
            self._timer = None
        if registration is not None:
            registration.dispose()
        if timer is not None:
            timer.cancel()

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
        return self._state is not _PENDING

    def cancelled(self) -> bool:
        return self._state is _CANCELLED

    def result(self) -> T:
        """Block the calling thread until completion and return/raise the result.

        As with .NET's ``Task.Result`` this also blocks when called from inside
        a task. Two things keep that from starving the pool:

        * A task that has not started yet is run inline on the calling worker
          instead of being waited for (.NET does the same). A coroutine runs
          inline up to its first pending ``await``.
        * Otherwise the pool is told that the worker is blocked, so it can add
          a replacement.

        With ``max_workers`` reached, tasks that have already started and block
        on each other can still starve the pool: prefer ``await task`` inside
        tasks.
        """
        if self._state is _PENDING:
            self._wait()
        return self._raise_or_return()

    def exception(self) -> BaseException | None:
        if self._state is _PENDING:
            self._wait()
        if self._state is _CANCELLED:
            raise self._cancellation_exception()
        return self._exception

    def _wait(self) -> None:
        state = _thread_state
        if state.internal:
            raise RuntimeError(
                "Task.result() would block the runtime's timer/IO thread; "
                "use 'await task'"
            )
        pool = state.pool
        if (
                pool is not None
                and self._work is not None
                and pool is self._runtime._pool
                and state.inline < _MAX_INLINE_DEPTH
        ):
            self._run_inline(state, pool)
        with self._lock:
            if self._state is not _PENDING:
                return
            event = self._done_event
            if event is None:
                event = self._done_event = threading.Event()
        if pool is None:
            event.wait()
            return
        pool._worker_blocked()
        try:
            event.wait()
        finally:
            pool._worker_unblocked()

    def _run_inline(self, state: _ThreadState, pool: "_WorkerPool") -> None:
        """Start this task on the calling worker instead of waiting for it.

        ``_start()`` takes the work under the task's lock, so either this
        thread or the worker that pops the queued item runs it, never both;
        the loser finds nothing to do.
        """
        tail = state.tail
        state.inline += 1
        try:
            self._start()
        finally:
            state.inline -= 1
            # The caller is still inside its own work item. Anything the
            # inlined task left for "this worker's next item" must not wait
            # until the caller returns -- the caller may be about to block on
            # exactly that.
            state.tail = tail
            item = state.slot
            if item is not None:
                state.slot = None
                # False only if the pool closed, and then shutdown has
                # already cancelled the task behind the item.
                pool.queue(item)

    def _add_continuation(self, continuation: Callable[[Task[Any]], Any]) -> bool:
        """Call ``continuation(self)`` on completion; False if already complete.

        Continuations run on the completing thread and must not block.
        """
        with self._lock:
            if self._state is not _PENDING:
                return False
            continuations = self._continuations
            if continuations is None:
                self._continuations = [continuation]
            else:
                continuations.append(continuation)
        return True

    def _remove_continuation(self, continuation: Callable[[Task[Any]], Any]) -> None:
        with self._lock:
            continuations = self._continuations
            if continuations:
                try:
                    continuations.remove(continuation)
                except ValueError:
                    pass

    def _cancellation_exception(self) -> OperationCanceledError:
        if isinstance(self._exception, OperationCanceledError):
            return self._exception
        return OperationCanceledError(f"{self.name} was cancelled")

    def _await_pure_flpit_task(self) -> Generator[Any, T, T]:
        if self._state is not _PENDING:
            return self._raise_or_return()
        result = yield _WaitTask(self._runtime, self)
        return result

    __await__ = _await_pure_flpit_task

    def _await_asyncio_interop(self) -> Generator[Any, T, T]:
        if self._state is not _PENDING:
            return self._raise_or_return()

        if "asyncio" in sys.modules:
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                future: asyncio.Future[T] = loop.create_future()

                def complete_future() -> None:
                    if future.done():
                        return

                    try:
                        result = self._raise_or_return()
                    except BaseException as exc:
                        future.set_exception(exc)
                    else:
                        future.set_result(result)

                def notify(_: Task[Any]) -> None:
                    try:
                        loop.call_soon_threadsafe(complete_future)
                    except RuntimeError:
                        pass

                if not self._add_continuation(notify):
                    notify(self)

                return (
                    yield from cast(Generator[Any, T, T], future.__await__())
                )

        result = yield _WaitTask(self._runtime, self)
        return result

    def _raise_or_return(self) -> T:
        state = self._state
        if state is _SUCCEEDED:
            return cast(T, self._result)
        if state is _CANCELLED:
            raise self._cancellation_exception()
        if state is _FAILED:
            assert self._exception is not None
            raise self._exception
        raise InvalidStateError(f"{self.name} has not completed")

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _finish(
            self,
            state: str,
            result: Any = None,
            exception: BaseException | None = None,
    ) -> bool:
        """Complete the task. Exactly one caller wins; the others get False."""
        with self._lock:
            if self._state is not _PENDING:
                return False
            self._result = result
            self._exception = exception
            # Published last: lock-free readers check the state first.
            self._state = state
            continuations = self._continuations
            self._continuations = None
            event = self._done_event
            registration = self._token_registration
            self._token_registration = None
            timer = self._timer
            self._timer = None
        if registration is not None:
            registration.dispose()
        if timer is not None:
            timer.cancel()
        runtime = self._runtime
        runtime._task_completed(self, state)
        if event is not None:
            event.set()
        if continuations is not None:
            thread = _thread_state
            if thread.depth >= _MAX_COMPLETION_DEPTH and runtime._pool.queue(
                    functools.partial(self._run_continuations, continuations)
            ):
                return True
            thread.depth += 1
            try:
                self._run_continuations(continuations)
            finally:
                thread.depth -= 1
        return True

    def _run_continuations(self, continuations: list[Callable[[Task[Any]], Any]]) -> None:
        for continuation in continuations:
            try:
                continuation(self)
            except BaseException as error:
                self._runtime._report_exception(
                    {"message": f"Unhandled exception in continuation of {self.name}"},
                    error,
                )

    def _claim(self, operation: _Operation) -> bool:
        """Take ownership of a task parked on ``operation``; one caller wins."""
        with self._lock:
            if self._waiting_on is operation:
                self._waiting_on = None
                return True
        return False

    def _park(self, operation: _Operation) -> bool:
        """Give up ownership to ``operation``. False if the task must not wait."""
        with self._lock:
            if self._state is not _PENDING or self._cancel_requested:
                return False
            self._waiting_on = operation
            self._running = False
        return True

    # ------------------------------------------------------------------
    # Execution (pool worker threads only)
    # ------------------------------------------------------------------

    def _start(self) -> None:
        """First work item of a task created by Task.run()."""
        with self._lock:
            work = self._work
            self._work = None
            if work is None:
                return  # taken by shutdown, or run inline by Task.result()
            alive = self._state is _PENDING
            if alive:
                self._running = True
        target, args, kwargs = work
        if not alive:
            _close_if_coroutine(target)
            return
        token = self._token
        if token.is_cancellation_requested or self._cancel_requested:
            _close_if_coroutine(target)
            self._finish(
                _CANCELLED,
                exception=OperationCanceledError(
                    f"{self.name} cancelled before start", token=token
                ),
            )
            return

        state = _thread_state
        context = cast(Context, self._execution_context)
        value: Any
        coroutine: Coroutine[Any, Any, Any]
        try:
            # The context belongs to this task alone, so the current task is
            # set once instead of being set and restored around every step.
            context.run(_current_task._value.set, self)
            if type(target) is CoroutineType:
                value = target
            elif inspect.isawaitable(target):
                value = _await_any(target)
            else:
                if self._pass_token:
                    kwargs = {**kwargs, "token": token}
                if _is_async_callable(target):
                    # Only creates the coroutine object; no user code runs yet.
                    value = context.run(target, *args, **kwargs)
                else:
                    self._sync_running = True
                    try:
                        value = _run_with_context(context, target, *args, **kwargs)
                    finally:
                        self._sync_running = False
                        state.tail = True
            if type(value) is CoroutineType:
                coroutine = value
            elif inspect.isawaitable(value):
                # Support sync wrappers that return an awaitable.
                coroutine = _await_any(value)
            else:
                self._finish(_SUCCEEDED, result=value)
                return
        except OperationCanceledError as error:
            state.tail = True
            self._finish(_CANCELLED, exception=error)
            return
        except BaseException as error:
            state.tail = True
            self._finish(_FAILED, exception=error)
            return

        self._coroutine = coroutine
        if self._runtime._shutdown_requested:
            # A synchronous function that returned an awaitable after the
            # shutdown sweep: it missed the cancellation request.
            self._cancel_requested = True
        self._drive()

    def _drive(self) -> None:
        """Run coroutine steps until the task parks, yields or completes."""
        runtime = self._runtime
        lock = self._lock
        context = cast(Context, self._execution_context)
        state = _thread_state
        while True:
            value: Any = None
            error: BaseException | None = None
            with lock:
                coroutine = self._coroutine
                alive = self._state is _PENDING
                if alive:
                    self._running = True
                    value = self._next_value
                    error = self._next_exception
                    self._next_value = None
                    self._next_exception = None
                    if self._cancel_requested:
                        self._cancel_requested = False
                        if not isinstance(error, OperationCanceledError):
                            error = OperationCanceledError(f"{self.name} cancelled")
                else:
                    # Finished from outside (shutdown) while it was not ours.
                    self._coroutine = None
                    self._running = False
            if coroutine is None:
                return
            if not alive:
                runtime._close_coroutine(self, coroutine)
                return

            state.tail = False
            try:
                if error is None:
                    yielded = _run_with_context(context, coroutine.send, value)
                else:
                    yielded = _run_with_context(context, coroutine.throw, error)
            except StopIteration as stop:
                state.tail = True
                self._coroutine = None
                self._finish(_SUCCEEDED, result=stop.value)
                return
            except OperationCanceledError as cancellation:
                state.tail = True
                self._coroutine = None
                self._finish(_CANCELLED, exception=cancellation)
                return
            except BaseException as failure:
                state.tail = True
                self._coroutine = None
                self._finish(_FAILED, exception=failure)
                return

            state.tail = True
            try:
                resume = runtime._suspend(self, yielded)
            except BaseException as failure:
                # Not expected. Rather than leave the task pending forever,
                # raise in the coroutine -- provided the task is still ours.
                with lock:
                    resume = self._running or self._waiting_on is yielded
                    if resume:
                        self._waiting_on = None
                        self._next_exception = failure
            if not resume:
                # Parked or re-queued: the task now belongs to someone else
                # and must not be touched from here.
                return

    # ------------------------------------------------------------------
    # Shutdown (called by the thread running Task.shutdown())
    # ------------------------------------------------------------------

    def _cancel_for_shutdown(self) -> bool:
        """Request cancellation. True if a synchronous function is executing."""
        work = None
        finish = False
        with self._lock:
            if self._state is not _PENDING:
                return False
            operation = self._waiting_on
            if operation is not None:
                self._waiting_on = None  # claimed
            elif self._is_promise_task:
                finish = True
            elif self._work is not None:
                # Still queued: it never starts.
                work = self._work
                self._work = None
                finish = True
            elif self._sync_running:
                return True
            else:
                # Running or queued for its next step; delivered at the next
                # step boundary by _drive()/_park().
                self._cancel_requested = True
        if operation is not None:
            runtime = self._runtime
            runtime._release_wait(operation)
            self._next_exception = OperationCanceledError(f"{self.name} cancelled")
            runtime._enqueue_task(self)
        elif finish:
            if work is not None:
                _close_if_coroutine(work[0])
            self._finish(
                _CANCELLED,
                exception=OperationCanceledError(f"{self.name} cancelled"),
            )
        return False

    def _force_cancel(self) -> None:
        """Complete as cancelled no matter what the task is doing."""
        with self._lock:
            if self._state is not _PENDING:
                return
            operation = self._waiting_on
            self._waiting_on = None
        runtime = self._runtime
        if operation is not None:
            runtime._release_wait(operation)
        self._finish(_CANCELLED, exception=OperationCanceledError("runtime shutting down"))
        with self._lock:
            if self._running:
                # A worker is inside a step; it cleans up when the step returns.
                return
            coroutine = self._coroutine
            self._coroutine = None
            work = self._work
            self._work = None
        if work is not None:
            _close_if_coroutine(work[0])
        if coroutine is not None:
            runtime._close_coroutine(self, coroutine)

    def __repr__(self) -> str:
        return f"<{self.name} state={self._state}>"


_current_task: AsyncLocal[Task[Any] | None] = AsyncLocal()


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
        # Promise tasks are tracked so runtime shutdown can cancel unresolved
        # externally-completed tasks and wake any awaiters.
        self._task: Task[T] = Task._promise(_get_runtime())
        self._task.async_state = state

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
        # Safe from any thread and never blocks: the task's own lock decides
        # the winner and its continuations are handed to the pool, so the
        # caller of set_result() does not end up running awaiting coroutines.
        return self._task._finish(state, result=result, exception=exception)


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


class _WhenAll:
    """Completes a promise once every child has completed.

    Registered as a continuation on each pending child, so no coroutine and no
    worker round trip is needed, and each completion is O(1).
    """

    __slots__ = ("_promise", "_tasks", "_remaining", "_lock")

    def __init__(self, promise: Task[list[Any]], tasks: tuple[Task[Any], ...]) -> None:
        self._promise = promise
        self._tasks = tasks
        # One extra count is held by start() until every child is registered.
        self._remaining = len(tasks) + 1
        self._lock = threading.Lock()

    def start(self) -> None:
        for child in self._tasks:
            if not child._add_continuation(self):
                self(child)
        self(None)

    def __call__(self, _completed: Task[Any] | None) -> None:
        with self._lock:
            self._remaining -= 1
            if self._remaining:
                return
        tasks = self._tasks
        failures = tuple(child._exception for child in tasks if child._state is _FAILED)
        if len(failures) == 1:
            self._promise._finish(_FAILED, exception=failures[0])
        elif failures:
            self._promise._finish(
                _FAILED,
                exception=AggregateError(cast(tuple[Exception, ...], failures)),
            )
        elif any(child._state is _CANCELLED for child in tasks):
            self._promise._finish(
                _CANCELLED,
                exception=OperationCanceledError(
                    "One or more tasks passed to Task.when_all() were cancelled"
                ),
            )
        else:
            self._promise._finish(_SUCCEEDED, result=[child._result for child in tasks])


class _WhenAny:
    """Completes a promise with the first child to complete."""

    __slots__ = ("_promise", "_tasks")

    def __init__(self, promise: Task[Task[Any]], tasks: tuple[Task[Any], ...]) -> None:
        self._promise = promise
        self._tasks = tasks

    def start(self) -> None:
        promise = self._promise
        # Deterministic tie-breaking for tasks already completed when the
        # operation is first observed: first completed in input order.
        for child in self._tasks:
            if child._state is not _PENDING:
                promise._finish(_SUCCEEDED, result=child)
                return
        for child in self._tasks:
            if not child._add_continuation(self):
                self(child)
            if promise._state is not _PENDING:
                break
        if promise._state is not _PENDING:
            # A winner arrived while registration was still in progress.
            self._detach(None)

    def __call__(self, completed: Task[Any]) -> None:
        if self._promise._finish(_SUCCEEDED, result=completed):
            self._detach(completed)

    def _detach(self, winner: Task[Any] | None) -> None:
        # Losers keep running; do not let them keep this aggregate alive.
        for child in self._tasks:
            if child is not winner:
                child._remove_continuation(self)


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


class _IOReactor:
    """Selector thread turning socket readiness into task wake-ups.

    Started on the first socket wait, so programs that never await a socket
    pay nothing for it. All selector state is owned by the reactor thread;
    other threads only post commands and wake it. It never runs task code.
    """

    def __init__(self, runtime: "_Runtime") -> None:
        self._runtime = runtime
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._selector: selectors.BaseSelector | None = None
        self._wake_reader: socket.socket | None = None
        self._wake_writer: socket.socket | None = None
        self._commands: queue.SimpleQueue[tuple[Callable[[_WaitIO], None], _WaitIO]] = (
            queue.SimpleQueue()
        )
        self._waiters: dict[socket.socket, dict[str, set[_WaitIO]]] = {}
        self._closing = False
        self._failure: BaseException | None = None

    def arm(self, operation: _WaitIO) -> None:
        error = self._post(self._arm, operation)
        if error is not None:
            # The wait can never be signalled: fail it rather than strand it.
            self._wake(operation, error)

    def disarm(self, operation: _WaitIO) -> None:
        if self._thread is not None:
            self._post(self._disarm, operation)

    def _post(
            self, command: Callable[[_WaitIO], None], operation: _WaitIO
    ) -> BaseException | None:
        """Hand a command to the reactor thread; returns why it could not."""
        if self._thread is None:
            with self._lock:
                if self._thread is None and not self._closing and self._failure is None:
                    try:
                        self._start()
                    except BaseException as error:
                        # For example out of file descriptors. Not latched:
                        # a later wait may well succeed.
                        self._discard_resources()
                        return error
        if self._closing or self._failure is not None or self._thread is None:
            return self._failure or RuntimeShutdownError("Task runtime is shutting down")
        self._commands.put((command, operation))
        self._notify()
        return None

    def _start(self) -> None:
        self._selector = selectors.DefaultSelector()
        self._wake_reader, self._wake_writer = socket.socketpair()
        self._wake_reader.setblocking(False)
        self._wake_writer.setblocking(False)
        self._selector.register(self._wake_reader, selectors.EVENT_READ, data=_WAKE)
        thread = threading.Thread(
            target=self._loop, name="Task-io", daemon=True, **_fresh_context()
        )
        thread.start()
        self._thread = thread

    def _discard_resources(self) -> None:
        selector, self._selector = self._selector, None
        reader, self._wake_reader = self._wake_reader, None
        writer, self._wake_writer = self._wake_writer, None
        try:
            if selector is not None:
                selector.close()
        except BaseException as error:
            self._runtime._report_exception({"message": "Error closing selector"}, error)
        for wake_socket in (reader, writer):
            if wake_socket is not None:
                try:
                    wake_socket.close()
                except OSError:
                    pass

    def _notify(self) -> None:
        writer = self._wake_writer
        if writer is not None:
            try:
                writer.send(b"\x00")
            except (BlockingIOError, OSError):
                # A full wake-up socket already guarantees selector readability.
                pass

    def _wake(self, operation: _WaitIO, error: BaseException | None = None) -> None:
        task = operation.waiter
        if task is not None and task._claim(operation):
            runtime = self._runtime
            runtime._dispose_operation_token(operation)
            if error is not None:
                task._next_exception = error
            runtime._enqueue_task(task)

    def _arm(self, operation: _WaitIO) -> None:
        task = operation.waiter
        if task is None or task._waiting_on is not operation:
            return  # cancelled before the reactor got to it
        sock = operation.sock
        sides = self._waiters.setdefault(sock, {"read": set(), "write": set()})
        sides[operation.mode].add(operation)
        self._refresh(sock)

    def _disarm(self, operation: _WaitIO) -> None:
        sides = self._waiters.get(operation.sock)
        if sides is not None:
            sides[operation.mode].discard(operation)
            self._refresh(operation.sock)

    def _refresh(self, sock: socket.socket) -> None:
        selector = cast(selectors.BaseSelector, self._selector)
        sides = self._waiters.get(sock)
        mask = 0
        if sides:
            if sides["read"]:
                mask |= selectors.EVENT_READ
            if sides["write"]:
                mask |= selectors.EVENT_WRITE
        try:
            selector.get_key(sock)
            registered = True
        except (KeyError, ValueError, OSError):
            registered = False
        try:
            if mask:
                if registered:
                    selector.modify(sock, mask, data=None)
                else:
                    selector.register(sock, mask, data=None)
            else:
                if registered:
                    try:
                        selector.unregister(sock)
                    except (KeyError, ValueError, OSError):
                        pass
                self._waiters.pop(sock, None)
        except (KeyError, ValueError, OSError) as error:
            # A socket may be closed while tasks are waiting on it. Fail those
            # waits instead of allowing a selector error to kill the reactor.
            sides = self._waiters.pop(sock, None) or {"read": set(), "write": set()}
            for operation in sides["read"] | sides["write"]:
                self._wake(operation, error)
            try:
                selector.unregister(sock)
            except (KeyError, ValueError, OSError):
                pass

    def _ready(self, sock: Any, mask: int) -> None:
        sides = self._waiters.get(sock)
        if sides is None:
            return
        to_wake: set[_WaitIO] = set()
        if mask & selectors.EVENT_READ:
            to_wake.update(sides["read"])
            sides["read"].clear()
        if mask & selectors.EVENT_WRITE:
            to_wake.update(sides["write"])
            sides["write"].clear()
        for operation in to_wake:
            self._wake(operation)
        self._refresh(sock)

    def _loop(self) -> None:
        _thread_state.internal = True
        selector = cast(selectors.BaseSelector, self._selector)
        reader = cast(socket.socket, self._wake_reader)
        commands = self._commands
        failure: BaseException | None = None
        try:
            while not self._closing:
                for key, mask in selector.select(None):
                    if key.data is _WAKE:
                        try:
                            while reader.recv(4096):
                                pass
                        except OSError:  # includes BlockingIOError
                            pass
                    else:
                        self._ready(key.fileobj, mask)
                while True:
                    try:
                        command, operation = commands.get_nowait()
                    except queue.Empty:
                        break
                    command(operation)
        except BaseException as error:
            failure = error
            if not self._closing:
                self._runtime._report_exception(
                    {"message": "Fatal error in Task IO thread; socket waits are unavailable"},
                    error,
                )
        finally:
            with self._lock:
                self._failure = failure or RuntimeShutdownError("Task runtime is shutting down")
            # Nothing will ever signal the remaining waits: fail them, both
            # the armed ones and those still sitting in the command queue.
            stranded = [
                operation
                for sides in self._waiters.values()
                for operation in sides["read"] | sides["write"]
            ]
            self._waiters.clear()
            while True:
                try:
                    command, operation = commands.get_nowait()
                except queue.Empty:
                    break
                if command == self._arm:
                    stranded.append(operation)
            for operation in stranded:
                self._wake(operation, self._failure)
            self._discard_resources()

    def close(self) -> bool:
        """Stop the reactor thread. False if it did not stop in time."""
        with self._lock:
            self._closing = True
            thread = self._thread
        if thread is None:
            return True
        self._notify()
        thread.join(1.0)
        return not thread.is_alive()


def _spin_count() -> int:
    """How long an idle worker polls for work before it parks.

    Spinning only pays off when another thread can produce work at the same
    time. With the GIL it would merely keep that thread from running.
    """
    gil_enabled = getattr(sys, "_is_gil_enabled", None)
    if gil_enabled is None or gil_enabled():
        return 0
    return 400  # a few tens of microseconds


class _WorkerPool:
    """Thread pool modelled on the .NET ThreadPool.

    * One shared FIFO queue (a ``collections.deque``, whose append/popleft are
      atomic with the GIL and on free-threaded builds).
    * Workers are created on demand: immediately up to ``min_workers``, and
      beyond that by the gate thread when queued work stops making progress
      (starvation), up to the hard limit ``max_workers``.
    * A worker blocked in ``Task.result()`` is reported to the pool, which may
      start a replacement right away (.NET's cooperative blocking detection).
    * Workers above ``min_workers`` retire after being idle for a while.
    * Workers are daemon threads, like .NET background threads: a worker stuck
      in user code never keeps the process from exiting.

    Waking a sleeping thread is by far the most expensive step of handing work
    over, so it is avoided wherever the work would get picked up anyway:

    * A worker that makes exactly one task runnable while finishing its
      current item runs that task next itself (``_ThreadState.slot``).
    * Queuing work wakes a parked worker only if no worker is already
      *searching* (awake and looking for work). A woken worker that finds
      work wakes the next one if more is waiting, so a burst still fans out
      over all workers, while a chain of sequential hand-offs stays on the
      threads that are already running instead of bouncing between sleepers.
    * On free-threaded builds a worker that runs dry keeps looking for a few
      tens of microseconds before it parks, which covers the usual gap until
      the next continuation arrives.

    There is deliberately no per-worker queue and no work stealing: with the
    GIL it cannot help, and one shared queue is enough for Python-level work
    on free-threaded builds.

    ``_count``, ``_searching``, ``_blocked`` and ``_parked`` are only written
    under ``_lock``; the unlocked reads are hints, and every path that could
    lose a wake-up re-checks after publishing its own state.
    """

    _IDLE_TIMEOUT: Final = 20.0  # same order as the .NET worker idle timeout
    _GATE_INTERVAL: Final = 0.5
    _GATE_INTERVAL_BLOCKED: Final = 0.25

    def __init__(self, runtime: "_Runtime", min_workers: int, max_workers: int) -> None:
        self._runtime = runtime
        self._min = min_workers
        self._max = max_workers
        self._items: deque[Callable[[], Any]] = deque()
        self._lock = threading.Lock()
        self._exited = threading.Condition(self._lock)
        self._count = 0       # live workers
        self._searching = 0   # workers awake without work, looking for some
        self._blocked = 0     # workers blocked in Task.result()
        self._parked: list[threading.Lock] = []  # wake handles of sleeping workers
        self._serial = 0
        self._completed = 0   # progress indicator for the gate; approximate
        self._spin = _spin_count()
        self._closed = False
        self._closing = threading.Event()
        self._gate_signal = threading.Event()
        self._gate_thread: threading.Thread | None = None

    def queue(self, item: Callable[[], Any]) -> bool:
        """Queue a work item. False if the pool no longer accepts work."""
        if self._closed:
            return False
        self._items.append(item)
        # Read *after* the append. A searching worker re-checks the queue
        # after it stops searching, so one of the two sides sees the other.
        if self._searching == 0:
            self._wake_one()
        return True

    def _wake_one(self) -> None:
        """Get one more worker to look at the queue, if that is possible."""
        if not self._parked:
            # Unlocked early outs for a busy pool, where this runs per item.
            count = self._count
            if count >= self._max:
                return
            if count >= self._min + min(self._blocked, self._min):
                # Past the on-demand allowance: only starvation adds workers.
                if not self._gate_signal.is_set():
                    self._wake_gate()
                return
        parker = None
        serial = 0
        with self._lock:
            if self._closed or self._searching:
                return
            if self._parked:
                parker = self._parked.pop()  # most recently parked: still warm
                self._searching += 1
            elif (
                    self._count < self._max
                    # Blocked workers do not count against the on-demand
                    # allowance, up to one extra set.
                    and self._count < self._min + min(self._blocked, self._min)
            ):
                self._count += 1
                self._searching += 1
                self._serial += 1
                serial = self._serial
        if parker is not None:
            parker.release()
        elif serial:
            self._spawn(serial)

    def _spawn(self, serial: int) -> None:
        """Start a worker that was already counted as live and searching."""
        try:
            threading.Thread(
                target=self._work,
                name=f"Task-worker-{serial}",
                daemon=True,
                **_fresh_context(),
            ).start()
        except BaseException as error:
            # Out of threads/memory, or the interpreter is finalizing. Queued
            # work stays queued for the workers that do exist.
            with self._lock:
                self._count -= 1
                self._searching -= 1
                self._exited.notify_all()
            self._runtime._report_exception(
                {"message": "Failed to start a Task worker thread"}, error
            )

    def _work(self) -> None:
        state = _thread_state
        state.pool = self
        items = self._items
        lock = self._lock
        report = self._runtime._report_exception
        # Held while awake; released by whoever wakes this worker.
        parker = threading.Lock()
        parker.acquire()
        searching = True  # whoever started this thread counted it as such
        counted = True
        try:
            while True:
                item = state.slot
                if item is not None:
                    state.slot = None
                    state.streak += 1
                else:
                    state.streak = 0
                    while True:
                        if self._closed:
                            return
                        try:
                            item = items.popleft()
                        except IndexError:
                            pass
                        else:
                            if searching:
                                searching = False
                                with lock:
                                    self._searching -= 1
                            if items and self._searching == 0:
                                # More is waiting and nobody is looking.
                                self._wake_one()
                            break

                        if self._spin:
                            if not searching:
                                searching = True
                                with lock:
                                    self._searching += 1
                            for _ in range(self._spin):
                                if items:
                                    break
                            if items:
                                continue

                        # Nothing to do: park. Publish that first, then look
                        # at the queue once more, so that a concurrent queue()
                        # either sees this worker parked or is seen here.
                        with lock:
                            if searching:
                                searching = False
                                self._searching -= 1
                            self._parked.append(parker)
                        if items or self._closed:
                            with lock:
                                try:
                                    self._parked.remove(parker)
                                    continue
                                except ValueError:
                                    pass  # already picked by a waker
                            parker.acquire()
                            searching = True
                            continue

                        while not parker.acquire(timeout=self._IDLE_TIMEOUT):
                            with lock:
                                if parker not in self._parked:
                                    # A waker picked this worker just now.
                                    parker_pending = True
                                elif self._count > self._min and not self._closed:
                                    # Surplus worker: retire. Decided and
                                    # counted atomically, so the pool cannot
                                    # drop below min_workers.
                                    self._parked.remove(parker)
                                    self._count -= 1
                                    self._exited.notify_all()
                                    counted = False
                                    return
                                else:
                                    parker_pending = False
                            if parker_pending:
                                parker.acquire()
                                break
                        searching = True  # the waker counted this worker

                state.tail = False
                try:
                    item()
                except BaseException as error:
                    report(
                        {
                            "message": "Unhandled exception in Task scheduler callback",
                            "callback": item,
                        },
                        error,
                    )
                item = None
                # Unsynchronized on purpose: the gate only needs to see that
                # the number moved, a lost increment is harmless.
                self._completed += 1
        finally:
            state.pool = None
            with lock:
                if searching:
                    self._searching -= 1
                if counted:
                    self._count -= 1
                    self._exited.notify_all()

    def _worker_blocked(self) -> None:
        with self._lock:
            self._blocked += 1
        if self._items and self._searching == 0:
            self._wake_one()

    def _worker_unblocked(self) -> None:
        with self._lock:
            self._blocked -= 1

    def _wake_gate(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._gate_thread is None:
                thread = threading.Thread(
                    target=self._gate, name="Task-gate", daemon=True, **_fresh_context()
                )
                try:
                    thread.start()
                except BaseException:
                    return
                self._gate_thread = thread
        self._gate_signal.set()

    def _gate(self) -> None:
        """Inject a worker when queued work makes no progress (starvation)."""
        _thread_state.internal = True
        items = self._items
        signal = self._gate_signal
        closing = self._closing
        while True:
            signal.wait()
            last = self._completed
            while True:
                if closing.wait(
                        self._GATE_INTERVAL_BLOCKED if self._blocked else self._GATE_INTERVAL
                ):
                    return
                if not items:
                    # Go dormant; re-check after clearing so that a request
                    # arriving in between is not lost.
                    signal.clear()
                    if not items:
                        break
                    signal.set()
                current = self._completed
                if current == last:
                    # Work is waiting and not a single item finished during
                    # the whole interval: every worker is tied up.
                    with self._lock:
                        if self._closed or self._count >= self._max:
                            continue
                        self._count += 1
                        self._searching += 1
                        self._serial += 1
                        serial = self._serial
                    self._spawn(serial)
                last = current

    def close(self) -> None:
        """Stop accepting work, drop queued items and tell workers to exit."""
        with self._lock:
            self._closed = True
            parked = self._parked[:]
            self._parked.clear()
            self._searching += len(parked)  # each one wakes up as a searcher
        self._closing.set()
        self._gate_signal.set()
        self._items.clear()
        for parker in parked:
            parker.release()

    def wait(self, timeout: float) -> int:
        """Wait for workers to exit; returns how many are still running."""
        deadline = time.monotonic() + timeout
        with self._exited:
            while self._count > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._exited.wait(remaining)
            return self._count


class _Runtime:
    """Private singleton runtime: worker pool + socket reactor + task registry."""

    def __init__(self, *, min_workers: int, max_workers: int) -> None:
        self._pool = _WorkerPool(self, min_workers, max_workers)
        self._io = _IOReactor(self)
        # Pending tasks, so shutdown can cancel them. The registry is weak on
        # purpose: a pending task that nothing references can never make
        # progress (anything that can resume it -- the pool queue, a running
        # worker, the timer, the selector, a continuation list -- holds it
        # strongly), so it is garbage, exactly like an abandoned
        # TaskCompletionSource in .NET. A strong registry would keep every
        # such task, and the coroutine parked on it, alive for the life of
        # the process.
        self._tasks: weakref.WeakSet[Task[Any]] = weakref.WeakSet()
        self._state_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shutdown_requested = False
        self._stopping = False
        self._closed = False
        self._drained = threading.Event()
        self._shutdown_tasks_cancelled = 0
        self._report: ShutdownReport | None = None
        self._exception_handler: Callable[[dict[str, Any]], Any] | None = None

    @property
    def closed(self) -> bool:
        return self._closed

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

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def _track(self, task: Task[Any], *, internal: bool = False) -> None:
        """Register a pending task, or reject it if the runtime is stopping.

        Lock-free on purpose (this runs for every task). The order matters:
        the task is added *before* the flags are read, and shutdown sets the
        flags *before* it snapshots the registry. Either this thread sees the
        flag and backs out, or the snapshot sees the task.
        """
        self._tasks.add(task)
        if self._shutdown_requested and (self._stopping or not internal):
            self._tasks.discard(task)
            raise RuntimeShutdownError("Task runtime is shutting down")

    def _post(self, callback: Callable[[], Any], *, internal: bool = False) -> None:
        """Run ``callback`` on a pool worker; failures go to the exception handler."""
        if self._stopping or (self._shutdown_requested and not internal):
            raise RuntimeShutdownError("Task runtime is shutting down")
        if not self._pool.queue(callback):
            raise RuntimeShutdownError("Task runtime is shutting down")

    def _submit(self, task: Task[Any], work: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        task._work = (work, args, kwargs)
        try:
            self._track(task)
        except BaseException:
            task._work = None
            _close_if_coroutine(work)
            raise
        # If the pool closes in between, shutdown's final sweep cancels the task.
        self._pool.queue(task._start)

    def _enqueue_task(self, task: Task[Any]) -> None:
        """Make a claimed task runnable."""
        state = _thread_state
        if (
                state.tail
                and state.slot is None
                and state.pool is self._pool
                and state.streak < _MAX_SLOT_STREAK
        ):
            # The calling worker is about to look for work anyway: let it run
            # this task next instead of waking another thread for it.
            state.slot = task._drive
            return
        self._pool.queue(task._drive)

    def _task_completed(self, task: Task[Any], state: str) -> None:
        self._tasks.discard(task)
        if self._shutdown_requested:
            if state is _CANCELLED:
                with self._state_lock:
                    self._shutdown_tasks_cancelled += 1
            if not self._tasks:
                self._drained.set()

    # ------------------------------------------------------------------
    # Suspension (called by the worker that just ran a coroutine step)
    # ------------------------------------------------------------------

    def _suspend(self, task: Task[Any], operation: Any) -> bool:
        """Act on what a coroutine yielded.

        Returns True if the worker should run the next step right away (the
        value or exception to deliver is already stored on the task), False
        if the task was handed to someone else.
        """
        kind = type(operation)
        if kind is _WaitTask:
            target = operation.task
            if target._state is not _PENDING:
                # Awaiting an already completed task continues synchronously.
                _resume_from(task, target)
                return True
            if operation.runtime is self and target is not task:
                operation.waiter = task
                if not task._park(operation):
                    return True
                if target._add_continuation(operation):
                    return False
                # The target completed between the check and the registration.
                if task._claim(operation):
                    _resume_from(task, target)
                    return True
                return False
            if target is task:
                task._next_exception = RuntimeError("a task cannot await itself")
                return True
        elif kind is _YieldNow:
            if operation.runtime is self:
                with task._lock:
                    task._running = False
                    alive = task._state is _PENDING
                # Always through the shared queue: the point of yielding is to
                # let work that is already queued go first.
                return not (alive and self._pool.queue(task._drive))
        elif kind is _WaitIO:
            if operation.runtime is self:
                return self._suspend_io(task, operation)

        if not isinstance(operation, _Operation):
            task._next_exception = RuntimeError(
                f"{task.name} yielded unsupported object {operation!r}; "
                "this runtime only supports Task awaitables"
            )
        elif operation.runtime is not self:
            task._next_exception = RuntimeError("awaitable belongs to a different runtime")
        else:
            task._next_exception = RuntimeError(f"unsupported operation type: {kind.__name__}")
        return True

    def _suspend_io(self, task: Task[Any], operation: _WaitIO) -> bool:
        token = operation.token
        if token.is_cancellation_requested:
            task._next_exception = OperationCanceledError(
                "Operation token was cancelled", token=token
            )
            return True
        try:
            if operation.sock.fileno() < 0:
                raise ValueError("cannot wait on a closed socket")
        except Exception as error:
            task._next_exception = error
            return True
        operation.waiter = task
        if not task._park(operation):
            return True
        self._io.arm(operation)
        if token.can_be_cancelled:
            # May run the callback inline if the token was cancelled meanwhile.
            registration = token.register(operation._on_cancel)
            operation._token_registration = registration
            if task._waiting_on is not operation:
                # Already resumed: nobody else will dispose the registration.
                operation._token_registration = None
                registration.dispose()
        return False

    def _cancel_wait(self, operation: _Operation) -> None:
        """Token callback: abort the wait and raise in the waiting coroutine."""
        task = operation.waiter
        if task is not None and task._claim(operation):
            self._release_wait(operation)
            task._next_exception = OperationCanceledError(
                "Operation token was cancelled", token=operation.token
            )
            self._enqueue_task(task)

    def _dispose_operation_token(self, operation: _Operation) -> None:
        registration = operation._token_registration
        if registration is not None:
            operation._token_registration = None
            registration.dispose()

    def _release_wait(self, operation: _Operation) -> None:
        """Undo the registrations of a wait that was claimed by cancellation."""
        self._dispose_operation_token(operation)
        if isinstance(operation, _WaitTask):
            operation.task._remove_continuation(operation)
        elif isinstance(operation, _WaitIO):
            self._io.disarm(operation)

    def _close_coroutine(self, task: Task[Any], coroutine: Coroutine[Any, Any, Any]) -> None:
        try:
            _run_with_context(cast(Context, task._execution_context), coroutine.close)
        except BaseException as error:
            self._report_exception(
                {"message": f"Error closing coroutine for {task.name}"}, error
            )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _snapshot_tasks(self) -> list[Task[Any]]:
        while True:
            try:
                return list(self._tasks)
            except RuntimeError:
                # Resized by another thread while being copied.
                continue

    def shutdown(self, *, grace_timeout: float, worker_timeout: float) -> ShutdownReport:
        with self._shutdown_lock:
            if self._closed:
                return cast(ShutdownReport, self._report)

            # 1. Reject new external work and ask every pending task to cancel.
            self._shutdown_requested = True
            deadline = time.monotonic() + grace_timeout
            # Synchronous functions cannot be cancelled and get worker_timeout
            # rather than the coroutine grace period.
            synchronous = [
                task for task in self._snapshot_tasks() if task._cancel_for_shutdown()
            ]
            self._tasks.difference_update(synchronous)

            # 2. Give coroutines the grace period to unwind (they may still
            #    await delays for cleanup).
            while self._tasks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._drained.wait(min(remaining, 0.05))
                self._drained.clear()

            # 3. Stop for good: nothing is accepted any more, whatever is
            #    still pending is completed as cancelled.
            self._stopping = True
            while True:
                leftover = self._snapshot_tasks()
                if not leftover:
                    break
                for task in leftover:
                    task._force_cancel()
                    self._tasks.discard(task)
            self._pool.close()
            io_stopped = self._io.close()

            # 4. Running synchronous functions cannot be stopped; wait a bit.
            workers_still_running = self._pool.wait(worker_timeout)
            for task in synchronous:
                task._force_cancel()

            if not io_stopped:
                self._report_exception(
                    {"message": "Task IO thread did not stop before timeout"},
                    TimeoutError("IO thread shutdown timed out"),
                )
            report = ShutdownReport(
                runtime_stopped=io_stopped,
                tasks_cancelled=self._shutdown_tasks_cancelled,
                workers_still_running=workers_still_running,
                timed_out=(not io_stopped or workers_still_running > 0),
            )
            self._report = report
            self._closed = True
            return report


def _is_async_callable(value: Any) -> bool:
    function = value.__func__ if type(value) is MethodType else value
    if type(function) is FunctionType:
        if function.__code__.co_flags & inspect.CO_COROUTINE:
            return True
        if not function.__dict__:
            # A plain function: nothing (functools.wraps,
            # inspect.markcoroutinefunction, ...) could make it async.
            return False
    if inspect.iscoroutinefunction(value):
        return True
    call = getattr(value, "__call__", None)
    return inspect.iscoroutinefunction(call)


def _default_min_workers() -> int:
    cpus = getattr(os, "process_cpu_count", os.cpu_count)() or 1
    return min(32, cpus + 4)


_runtime_lock = threading.RLock()
_runtime: _Runtime | None = None
_runtime_config: dict[str, int] = {
    # Created on demand without delay; the same size the fixed pool used to have.
    "min_workers": _default_min_workers(),
    # Same default as the .NET thread pool: effectively unbounded, reached only
    # through slow injection while the pool is starved.
    "max_workers": 32767,
}


def _get_runtime() -> _Runtime:
    global _runtime
    runtime = _runtime
    if runtime is not None and not runtime._closed:
        return runtime
    with _runtime_lock:
        if _runtime is None or _runtime.closed:
            _runtime = _Runtime(**_runtime_config)
        return _runtime


def _shutdown_at_exit() -> None:
    try:
        Task.shutdown(grace_timeout=0.2, worker_timeout=0.2)
    except BaseException:
        _LOG.exception("Error during Task interpreter shutdown")


atexit.register(_shutdown_at_exit)


def _reset_after_fork() -> None:
    # Only the forking thread exists in the child: the pool, timer and IO
    # threads are gone and any lock may be held by a thread that no longer
    # exists. Start from scratch; the runtime is recreated lazily.
    global _runtime, _runtime_lock, _timers
    _runtime_lock = threading.RLock()
    _runtime = None
    _timers = _TimerQueue()
    _thread_state.pool = None
    _thread_state.slot = None
    _thread_state.tail = False
    _thread_state.internal = False


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


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