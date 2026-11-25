"""asyncio libraries on the flpit runtime: a pool of standard asyncio event loops.

Provisional: the API of this module may change in 0.5. Prefer a library's sync client where one
exists (``httpx.Client``, psycopg's ``ConnectionPool``): it is written for threads and can be shared.

asyncio libraries (httpx, asyncpg, redis.asyncio, aiohttp, ...) need two things: a running
event loop on the thread that runs their code, and loop affinity (a connection pool, lock or
future created on one loop is only used on that loop). This module provides both without
giving up flpit's threads:

* **Strand loops** (Linux, the default there): each loop is an ordinary
  ``asyncio.SelectorEventLoop`` - asyncio's own transports, sockets, timers and executor
  hooks - but nobody calls ``run_forever()``. When a loop has work, one flpit work item runs
  its iterations; iterations of the same loop never overlap, so each loop is a serialized
  queue on the flpit pool (Kestrel's IOQueue model). One reactor thread waits on a master
  epoll holding every loop's own epoll descriptor and wakes the loop that has I/O; timers go
  to flpit's timer queue. A loop costs no thread, and loops run in parallel on the pool.
* **Thread loops** (other platforms, or ``configure(backend="threads")``): one dedicated
  thread per loop running ``run_forever()``. Public asyncio API only.

Work goes to the loop already running on the calling thread when there is one (asyncio code
calling more asyncio code stays on its loop), otherwise to the least busy of the pool's loops
("power of two choices"). Loops are created on demand, up to ``configure(loops=...)``.

Loop-bound objects that should outlive one call (an ``httpx.AsyncClient``, an asyncpg pool)
are kept one per loop and closed with the loop. Register them with ``provide()`` and take them as
a ``Loop[T]`` parameter of an ``@asyncio_task`` function, or hold a ``PerLoop[T]`` in an object that
lives longer than a call (a singleton) and read ``.current`` on the loop. ``warm=True`` creates the
value on every pool loop before the loop takes work.

Strand loops drive asyncio's ``BaseEventLoop._run_once`` and replace two private hooks
(``_write_to_self``, the selector's wait); the thread backend needs none of that and is the
fallback if a Python release changes those internals.
"""
from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import contextvars
import inspect
import os
import random
import select
import selectors
import sys
import threading
import typing
import weakref
from asyncio import events
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine
from typing import Annotated, Any, Final, Generic, TypeAlias, TypeVar, cast, get_args, get_origin, override

from . import task as _task
from .task import CancellationToken, OperationCanceledError, Task, TaskCompletionSource
from .threading import ThreadPool

__all__ = ["Loop", "LoopLocal", "LoopStartError", "PerLoop", "configure", "injected", "provide", "run_asyncio", "shutdown"]

T = TypeVar("T")

#: Iterations one drive runs before it yields its pool worker to other work.
_MAX_ITERATIONS_PER_DRIVE = 64


# ---------------------------------------------------------------------------
# Default executor: run_in_executor(None, ...) and getaddrinfo on the flpit pool
# ---------------------------------------------------------------------------

class _PoolExecutor(concurrent.futures.ThreadPoolExecutor):
    """``concurrent.futures`` interface over the flpit pool (asyncio's default executor here).

    A ``ThreadPoolExecutor`` subclass only because ``set_default_executor`` requires one; it
    never starts threads of its own.
    """

    def __init__(self) -> None:
        super().__init__(max_workers=1, thread_name_prefix="unused")

    @override
    def submit[**P, R](
            self, fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs
    ) -> concurrent.futures.Future[R]:
        future: concurrent.futures.Future[R] = concurrent.futures.Future()

        def run(_state: Any) -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                result = fn(*args, **kwargs)
            except BaseException as error:  # noqa: BLE001 - delivered to the waiter
                future.set_exception(error)
            else:
                future.set_result(result)

        ThreadPool.queue(run, None)
        return future

    @override
    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        pass  # the flpit pool outlives the loops


_POOL_EXECUTOR = _PoolExecutor()


# ---------------------------------------------------------------------------
# Strand loops
# ---------------------------------------------------------------------------

if hasattr(selectors, "EpollSelector"):
    class _NonBlockingSelector(selectors.EpollSelector):
        """The loop's own selector never waits: the reactor thread does the waiting."""

        @override
        def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
            return super().select(0)


class _Reactor:
    """One thread for every strand loop: waits on a master epoll of the loops' epoll descriptors.

    Each loop is registered one-shot (EPOLLONESHOT) and re-armed after the loop's iterations
    ran, so a loop with pending I/O is woken once, not on every poll.
    """

    def __init__(self) -> None:
        self._epoll = select.epoll()
        self._loops: dict[int, _StrandLoop] = {}
        self._lock = threading.Lock()
        self._wakeup_read, self._wakeup_write = os.pipe()
        os.set_blocking(self._wakeup_read, False)
        self._epoll.register(self._wakeup_read, select.EPOLLIN)
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="Task-asyncio-reactor", daemon=True)
        self._thread.start()

    def add(self, loop: _StrandLoop) -> None:
        fd = loop._selector.fileno()
        with self._lock:
            self._loops[fd] = loop
        self._epoll.register(fd, select.EPOLLIN | select.EPOLLONESHOT)

    def rearm(self, loop: _StrandLoop) -> None:
        try:
            self._epoll.modify(loop._selector.fileno(), select.EPOLLIN | select.EPOLLONESHOT)
        except (OSError, ValueError):
            pass  # closed meanwhile

    def remove(self, loop: _StrandLoop) -> None:
        fd = loop._selector.fileno()
        with self._lock:
            self._loops.pop(fd, None)
        try:
            self._epoll.unregister(fd)
        except (OSError, ValueError):
            pass

    def stop(self) -> None:
        self._stopping = True
        os.write(self._wakeup_write, b"x")
        self._thread.join(5)
        self._epoll.close()
        os.close(self._wakeup_read)
        os.close(self._wakeup_write)

    def _run(self) -> None:
        poll = self._epoll.poll
        while not self._stopping:
            try:
                ready = poll()
            except InterruptedError:
                continue
            for fd, _events in ready:
                if fd == self._wakeup_read:
                    try:
                        os.read(self._wakeup_read, 64)
                    except BlockingIOError:
                        pass
                    continue
                with self._lock:
                    loop = self._loops.get(fd)
                if loop is not None:
                    loop._wake()


class _StrandLoop(asyncio.SelectorEventLoop):
    """A standard selector event loop whose iterations run as flpit work items, never two at once."""

    # asyncio internals this backend uses (CPython's BaseEventLoop / BaseSelectorEventLoop; not in
    # typeshed). Kept to this one class; the threads backend needs none of them.
    _selector: selectors.EpollSelector  # always a _NonBlockingSelector
    _ready: deque[asyncio.Handle]
    _scheduled: list[asyncio.TimerHandle]
    _thread_id: int | None
    _run_once: Callable[[], None]
    _asyncgen_firstiter_hook: Callable[[AsyncGenerator[Any, Any]], None]
    _asyncgen_finalizer_hook: Callable[[AsyncGenerator[Any, Any]], None]

    def __init__(self, reactor: _Reactor) -> None:
        # Set before BaseEventLoop.__init__, which already calls overridden methods.
        self._reactor = reactor
        self._guard = threading.Lock()
        self._queued = False  # a drive is queued or running
        self._again = False  # woken while driving: iterate once more
        self._timer: Any = None
        self._timer_at: float | None = None
        self._loop_closing = True  # not running (and never driven) until fully set up
        super().__init__(_NonBlockingSelector())
        self.set_default_executor(_POOL_EXECUTOR)
        reactor.add(self)
        self._loop_closing = False
        if self._ready:
            self._wake()

    # -- waking ----------------------------------------------------------------------------------

    def _wake(self) -> None:
        with self._guard:
            if self._loop_closing:
                return
            if self._queued:
                self._again = True
                return
            self._queued = True
        ThreadPool.queue(self._drive, None)

    def _write_to_self(self) -> None:
        # call_soon_threadsafe from another thread. A strand isn't blocked in select(), so
        # schedule it directly instead of writing to the self-pipe (and going through the reactor).
        self._wake()

    @override
    def call_soon(self, callback: Callable[..., Any], *args: Any, context: contextvars.Context | None = None) -> Any:
        handle = super().call_soon(callback, *args, context=context)
        if events._get_running_loop() is not self:
            self._wake()  # scheduled outside an iteration (setup code on this loop's behalf)
        return handle

    @override
    def is_running(self) -> bool:
        # Logically running while it accepts work, although nobody calls run_forever().
        return not (self._loop_closing or self.is_closed())

    # -- driving ---------------------------------------------------------------------------------

    def _drive(self, _state: Any) -> None:
        hooks = sys.get_asyncgen_hooks()
        previous = events._get_running_loop()
        # asyncio's async-generator hooks for this loop while its code runs (pool workers carry
        # flpit's; an abandoned asyncio generator must be closed on its loop, not by flpit).
        sys.set_asyncgen_hooks(firstiter=self._asyncgen_firstiter_hook, finalizer=self._asyncgen_finalizer_hook)
        events._set_running_loop(self)
        self._thread_id = threading.get_ident()
        requeue = False
        next_timer: float | None = None
        try:
            iterations = 0
            while not self.is_closed():
                try:
                    self._run_once()
                except (KeyboardInterrupt, SystemExit):
                    # asyncio re-raises these from the task that raised them, to stop run_forever().
                    # The task has already failed with it and its Task reports it to whoever waits;
                    # the loop serves its other work on.
                    pass
                iterations += 1
                with self._guard:
                    if not (self._ready or self._again):
                        # Read while this is still the only drive; the next may start right after.
                        scheduled = self._scheduled
                        next_timer = scheduled[0].when() if scheduled else None
                        self._queued = False
                        break
                    self._again = False
                if iterations >= _MAX_ITERATIONS_PER_DRIVE:
                    requeue = True  # yield the worker; continue in a fresh work item
                    break
        finally:
            self._thread_id = None
            events._set_running_loop(previous)
            sys.set_asyncgen_hooks(*hooks)
        if self.is_closed():
            return
        if requeue:
            ThreadPool.queue(self._drive, None)
            return
        self._reactor.rearm(self)
        if next_timer is not None:
            self._arm_timer(next_timer)

    def _arm_timer(self, when: float) -> None:
        with self._guard:
            if self._loop_closing or (self._timer_at is not None and self._timer_at <= when):
                return  # an earlier (or the same) wake-up is already armed
            if self._timer is not None:
                self._timer.cancel()
            self._timer_at = when
            self._timer = _task._timers.schedule(max(0.0, when - self.time()), self._on_timer)

    def _on_timer(self) -> None:
        with self._guard:
            self._timer = None
            self._timer_at = None
        self._wake()

    @override
    def close(self) -> None:
        if self.is_closed():
            return
        with self._guard:
            self._loop_closing = True  # no more drives get queued
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        # A drive may still be finishing on a pool worker (it completed the last task).
        deadline = self.time() + 5.0
        while True:
            with self._guard:
                if not self._queued:
                    break
            if self.time() > deadline:
                break
            threading.Event().wait(0.001)
        self._reactor.remove(self)
        super().close()


# ---------------------------------------------------------------------------
# Thread loops (fallback backend)
# ---------------------------------------------------------------------------

class _ThreadLoop:
    """A standard event loop on a dedicated thread (public asyncio API only)."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.loop.set_default_executor(_POOL_EXECUTOR)
        self.thread = threading.Thread(target=self._serve, name="Task-asyncio-loop", daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while True:
            try:
                self.loop.run_forever()
                return  # stopped by stop()
            except (KeyboardInterrupt, SystemExit):
                continue  # raised out of one task (which failed with it); serve on, as strands do

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


# ---------------------------------------------------------------------------
# The pool of loops
# ---------------------------------------------------------------------------

def _default_count() -> int:
    counter = getattr(os, "process_cpu_count", None) or os.cpu_count
    return max(1, counter() or 1)


class _LoopPool:
    def __init__(self, count: int, backend: str) -> None:
        self.count = count
        self.backend = backend
        self.loops: list[asyncio.AbstractEventLoop] = []
        self.load: dict[asyncio.AbstractEventLoop, int] = {}
        self.lock = threading.Lock()
        self.reactor: _Reactor | None = None
        self.threads: list[_ThreadLoop] = []

    def acquire(self) -> asyncio.AbstractEventLoop:
        """The loop for a new piece of work: two random loops, the less busy one, or a new loop."""
        with self.lock:
            loops = self.loops
            if loops:
                a, b = (random.choice(loops), random.choice(loops)) if len(loops) > 1 else (loops[0], loops[0])
                loop = a if self.load[a] <= self.load[b] else b
                if self.load[loop] == 0 or len(loops) >= self.count:
                    self.load[loop] += 1
                    return loop
            loop = self._new_loop()
            loops.append(loop)
            self.load[loop] = 1
            # Queued before the caller queues its work, so the warm-up gate exists first.
            loop.call_soon_threadsafe(_begin_warm, loop, self, None)
            return loop

    def release(self, loop: asyncio.AbstractEventLoop) -> None:
        with self.lock:
            if loop in self.load:
                self.load[loop] -= 1

    def retire(self, loop: asyncio.AbstractEventLoop) -> None:
        """Take ``loop`` out of service (its start failed) and close it once its work has ended."""
        with self.lock:
            if loop not in self.load:
                return
            self.loops.remove(loop)
            del self.load[loop]
            runner = next((r for r in self.threads if r.loop is loop), None)
            if runner is not None:
                self.threads.remove(runner)

        def close(_state: Any) -> None:
            _close_loop(loop, 1.0)
            if runner is not None:
                runner.stop()
                runner.loop.close()

        ThreadPool.queue(close, None)

    def _new_loop(self) -> asyncio.AbstractEventLoop:
        if self.backend == "strands":
            if self.reactor is None:
                self.reactor = _Reactor()
            return _StrandLoop(self.reactor)
        runner = _ThreadLoop()
        self.threads.append(runner)
        return runner.loop

    def close(self, timeout: float) -> None:
        empty: list[asyncio.AbstractEventLoop] = []
        with self.lock:
            loops, self.loops = self.loops, empty
            self.load.clear()
        for loop in loops:
            _close_loop(loop, timeout)
        for runner in self.threads:
            runner.stop()
            runner.loop.close()
        self.threads.clear()
        if self.reactor is not None:
            self.reactor.stop()
            self.reactor = None


def _close_loop(loop: asyncio.AbstractEventLoop, timeout: float) -> None:
    """Cancel what still runs on ``loop``, close its LoopLocal values and async generators, close it."""

    async def wind_down() -> None:
        current = asyncio.current_task()
        tasks = [t for t in asyncio.all_tasks(loop) if t is not current]
        for running in tasks:
            running.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)
        await _dispose_loop_locals(loop)
        await loop.shutdown_asyncgens()

    if loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(wind_down(), loop).result(timeout + 1)
    except BaseException:  # noqa: BLE001 - shutting down regardless
        pass
    if isinstance(loop, _StrandLoop):
        loop.close()


_DEFAULT_BACKEND = "strands" if hasattr(select, "epoll") else "threads"
_config: dict[str, Any] = {"loops": None, "backend": _DEFAULT_BACKEND}
_pool: _LoopPool | None = None
_pool_lock = threading.Lock()


def configure(*, loops: int | None = None, backend: str | None = None) -> None:
    """Set the number of loops (default: the CPU count) and the backend before first use.

    ``backend`` is ``"strands"`` (loops as serialized queues on the flpit pool; Linux) or
    ``"threads"`` (one thread per loop; any platform). Changing either after loops exist
    takes effect after ``shutdown()``.
    """
    if loops is not None and loops < 1:
        raise ValueError("loops must be at least 1")
    if backend is not None:
        if backend not in ("strands", "threads"):
            raise ValueError("backend must be 'strands' or 'threads'")
        if backend == "strands" and not hasattr(select, "epoll"):
            raise ValueError("the strands backend needs epoll (Linux); use 'threads'")
    with _pool_lock:
        if loops is not None:
            _config["loops"] = loops
        if backend is not None:
            _config["backend"] = backend


def _get_pool() -> _LoopPool:
    global _pool
    pool = _pool
    if pool is None:
        with _pool_lock:
            pool = _pool
            if pool is None:
                pool = _pool = _LoopPool(_config["loops"] or _default_count(), _config["backend"])
    return pool


def shutdown(timeout: float = 5.0) -> None:
    """Cancel work still running on the loops, close their LoopLocal values and the loops.

    Called by ``Task.shutdown`` and at interpreter exit. Later work creates new loops.
    """
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close(timeout)


# ---------------------------------------------------------------------------
# Running asyncio code as a flpit Task
# ---------------------------------------------------------------------------

def run_asyncio(awaitable: Awaitable[T], *, token: CancellationToken | None = None) -> Task[T]:
    """Run asyncio code on an event loop and return a flpit Task for its outcome.

    The loop is the one already running on this thread, if any; otherwise a loop of the pool.
    The coroutine starts in a copy of the caller's context (``AsyncLocal`` values flow in).

    ``token`` cancels it: a cancelled token cancels the asyncio task (its ``finally`` blocks
    run) and the returned Task ends cancelled; an already cancelled token starts nothing.
    asyncio code that catches the cancellation and returns normally completes normally.
    """
    source: TaskCompletionSource[T] = TaskCompletionSource()
    if token is not None and token.is_cancellation_requested:
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        source.set_canceled(token)
        return source.task
    coroutine = awaitable if asyncio.iscoroutine(awaitable) else _await(awaitable)
    context = contextvars.copy_context()
    running = events._get_running_loop()
    if running is not None:
        _start(running, None, coroutine, context, source, token)
    else:
        pool = _get_pool()
        loop = pool.acquire()
        loop.call_soon_threadsafe(_start, loop, pool, coroutine, context, source, token)
    return source.task


async def _await(awaitable: Awaitable[T]) -> T:
    return await awaitable


class _Run:
    """One asyncio task started for run_asyncio: its token registration and completion."""

    __slots__ = ("loop", "pool", "source", "token", "registration", "task", "cancel_requested")

    def __init__(self, loop: asyncio.AbstractEventLoop, pool: _LoopPool | None,
                 source: TaskCompletionSource[Any], token: CancellationToken | None) -> None:
        self.loop = loop
        self.pool = pool
        self.source = source
        self.token = token
        self.registration: Any = None
        self.task: asyncio.Task[Any] | None = None
        self.cancel_requested = False

    def on_cancel(self) -> None:
        try:
            self.loop.call_soon_threadsafe(self._cancel)
        except RuntimeError:
            pass  # the loop is closed

    def _cancel(self) -> None:
        if self.task is None:
            self.cancel_requested = True
        else:
            self.task.cancel()

    def finish(self, task: asyncio.Task[Any]) -> None:
        registration, self.registration = self.registration, None
        if registration is not None:
            registration.dispose()
        if self.pool is not None:
            self.pool.release(self.loop)
        source, token = self.source, self.token
        if task.cancelled():
            source.try_set_canceled(token)
            return
        error = task.exception()
        if error is None:
            source.try_set_result(task.result())
        elif isinstance(error, OperationCanceledError):
            source.try_set_canceled(token if token is not None and token.is_cancellation_requested else None)
        elif isinstance(error, Exception):
            source.try_set_exception(error)
        else:
            # KeyboardInterrupt, SystemExit or another BaseException: the Task fails with it, as a
            # flpit coroutine that raises it does (TaskCompletionSource only accepts Exceptions).
            source._try_complete(Task.FAILED, exception=error)


def _start(loop: asyncio.AbstractEventLoop, pool: _LoopPool | None, coroutine: Coroutine[Any, Any, Any],
           context: contextvars.Context, source: TaskCompletionSource[Any], token: CancellationToken | None) -> None:
    run = _Run(loop, pool, source, token)
    if token is not None:
        run.registration = token.register(run.on_cancel)
    gate: asyncio.Task[None] | None = getattr(loop, _GATE, None)
    if gate is not None:
        if gate.done() and not gate.cancelled() and gate.exception() is None:
            if getattr(loop, _GATE, None) is gate:
                setattr(loop, _GATE, None)
        else:
            coroutine = _after_gate(gate, coroutine)
    task = loop.create_task(coroutine, context=context)
    run.task = task
    task.add_done_callback(run.finish)
    if run.cancel_requested:
        task.cancel()


# ---------------------------------------------------------------------------
# LoopLocal
# ---------------------------------------------------------------------------

_loop_locals: weakref.WeakSet[LoopLocal[Any]] = weakref.WeakSet()


class LoopLocal(Generic[T]):
    """One value per asyncio event loop, created on first use on that loop.

    For loop-bound objects that should outlive one call: an ``httpx.AsyncClient``, an asyncpg
    pool, an asyncio lock. ``factory`` may be a plain function or an ``async def``; read the
    value with ``await local.get()`` (works for both) or ``local.value`` (plain factories, or
    once created). When the bridge closes one of its loops, the loop's value is closed too:
    ``await value.aclose()`` if it has one, else ``value.close()``.

    Example:
        ```python
        clients = LoopLocal(httpx.AsyncClient)

        @asyncio_task
        async def fetch(url: str) -> dict:
            client = await clients.get()
            return (await client.get(url)).json()
        ```
    """

    def __init__(self, factory: Callable[[], T | Awaitable[T]]) -> None:
        self._factory = factory
        self._values: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, T] = weakref.WeakKeyDictionary()
        _loop_locals.add(self)

    @staticmethod
    def _loop() -> asyncio.AbstractEventLoop:
        loop = events._get_running_loop()
        if loop is None:
            raise RuntimeError("LoopLocal is only available in code running on an asyncio event loop")
        return loop

    @property
    def value(self) -> T:
        loop = self._loop()
        values = self._values
        if loop in values:
            return values[loop]
        created = self._factory()
        if asyncio.iscoroutine(created):
            created.close()
            raise TypeError("this LoopLocal has an async factory: use 'await local.get()'")
        value = cast(T, created)
        values[loop] = value
        return value

    async def get(self) -> T:
        loop = self._loop()
        values = self._values
        if loop in values:
            return values[loop]
        created = self._factory()
        if asyncio.iscoroutine(created) or isinstance(created, asyncio.Future):
            value = cast(T, await created)
        else:
            value = cast(T, created)
        if loop in values:  # created by another task of this loop meanwhile
            await _close_value(value)
            return values[loop]
        values[loop] = value
        return value

    def has_value(self) -> bool:
        """Whether a value exists for the loop running on this thread."""
        loop = events._get_running_loop()
        return loop is not None and loop in self._values


async def _close_value(value: object) -> None:
    """``await value.aclose()`` if it has one, else ``value.close()`` (awaited if it returns a coroutine)."""
    closer = getattr(value, "aclose", None) or getattr(value, "close", None)
    if closer is None:
        return
    result = closer()
    if asyncio.iscoroutine(result):
        await result


async def _dispose_loop_locals(loop: asyncio.AbstractEventLoop) -> None:
    for local in list(_loop_locals):
        if loop not in local._values:
            continue
        value = local._values.pop(loop)
        try:
            await _close_value(value)
        except Exception:  # noqa: BLE001 - one value's close must not keep the others open
            _task._LOG.exception("closing a LoopLocal value failed")


# ---------------------------------------------------------------------------
# PerLoop, provide() and Loop[T] parameters
# ---------------------------------------------------------------------------

class LoopStartError(RuntimeError):
    """A ``warm=True`` value could not be created on a new loop; the loop was taken out of service."""


#: Attribute of a pool loop holding the asyncio task that warms it (None once warm).
_GATE: Final = "_flpit_warm_gate"
_warm_per_loops: weakref.WeakSet[PerLoop[Any]] = weakref.WeakSet()
_warm_lock = threading.Lock()


def _begin_warm(loop: asyncio.AbstractEventLoop, pool: _LoopPool, per_loops: list[PerLoop[Any]] | None) -> None:
    """On ``loop``: start creating the warm values; work started meanwhile waits for them."""
    if per_loops is None:
        with _warm_lock:
            per_loops = list(_warm_per_loops)
    if not per_loops:
        return
    previous: asyncio.Task[None] | None = getattr(loop, _GATE, None)
    setattr(loop, _GATE, loop.create_task(_warm(loop, pool, per_loops, previous)))


async def _warm(loop: asyncio.AbstractEventLoop, pool: _LoopPool, per_loops: list[PerLoop[Any]],
                previous: asyncio.Task[None] | None) -> None:
    if previous is not None:
        await previous
    for per_loop in per_loops:
        if per_loop._closed:
            continue
        try:
            await per_loop.get()
        except Exception as error:
            pool.retire(loop)
            raise LoopStartError(f"creating the per-loop value {per_loop!r} on a new asyncio loop failed") from error


async def _after_gate(gate: asyncio.Task[None], coroutine: Coroutine[Any, Any, T]) -> T:
    try:
        await asyncio.shield(gate)
    except BaseException:
        coroutine.close()
        raise
    return await coroutine


class PerLoop(LoopLocal[T]):
    """One ``T`` per asyncio event loop, for objects that live longer than a call.

    Hold a ``PerLoop`` where the object itself must not be held: a singleton built once cannot
    keep a loop-bound client (it would use the client of the loop it was built on), but it can
    keep the ``PerLoop`` and read ``current`` in each call:

    ```python
    clients = PerLoop(lambda: httpx.AsyncClient(timeout=10), warm=True)

    class GitHubApi:
        def __init__(self, clients: PerLoop[httpx.AsyncClient]) -> None:
            self._clients = clients

        @asyncio_task
        async def repo(self, name: str) -> dict:
            return (await self._clients.current.get(f"/repos/{name}")).json()
    ```

    ``factory`` may be a plain function or an ``async def``. With ``warm=True`` the value is created
    on each pool loop when the loop starts, before it takes work, so ``current`` never creates one
    during a call; a factory that fails there fails the work waiting for that loop with
    ``LoopStartError`` and the loop is replaced. ``close()`` closes the values on every loop.
    """

    def __init__(self, factory: Callable[[], T | Awaitable[T]], *, warm: bool = False) -> None:
        super().__init__(factory)
        self.warm = warm
        self._closed = False
        if warm:
            with _warm_lock:
                _warm_per_loops.add(self)
            pool = _pool
            if pool is not None:
                with pool.lock:
                    loops = list(pool.loops)
                only: list[PerLoop[Any]] = [self]
                for loop in loops:
                    try:
                        loop.call_soon_threadsafe(_begin_warm, loop, pool, only)
                    except RuntimeError:
                        pass  # closed meanwhile

    @property
    def current(self) -> T:
        """The value of the loop running on this thread; created now if it does not exist yet.

        Raises ``RuntimeError`` outside asyncio code. An async factory cannot run here: with
        ``warm=True`` the value exists on every pool loop; elsewhere use ``await per_loop.get()``.
        """
        if self._closed:
            raise RuntimeError(f"{self!r} is closed")
        loop = self._loop()
        values = self._values
        if loop in values:
            return values[loop]
        created = self._factory()
        if asyncio.iscoroutine(created) or isinstance(created, asyncio.Future):
            if asyncio.iscoroutine(created):
                created.close()
            raise RuntimeError(f"{self!r} has an async factory and no value on this loop yet: "
                               "create it with warm=True, or use 'await per_loop.get()'")
        value = cast(T, created)
        values[loop] = value
        return value

    @override
    async def get(self) -> T:
        if self._closed:
            raise RuntimeError(f"{self!r} is closed")
        return await super().get()

    def close(self, timeout: float = 5.0) -> None:
        """Close the value of every loop (``aclose()`` or ``close()``, on its loop) and stop creating new ones."""
        self._closed = True
        with _warm_lock:
            _warm_per_loops.discard(self)
        with _providers_lock:
            for service_type, registered in list(_providers.items()):
                if registered is self:
                    del _providers[service_type]
        running = events._get_running_loop()
        pending: list[concurrent.futures.Future[None]] = []
        for loop, value in list(self._values.items()):
            self._values.pop(loop, None)
            if loop.is_closed():
                continue
            if loop is running:
                loop.create_task(_close_value(value))  # cannot wait for our own loop
                continue
            try:
                pending.append(asyncio.run_coroutine_threadsafe(_close_value(value), loop))
            except RuntimeError:
                pass  # the loop closed meanwhile
        if pending:
            done, _ = concurrent.futures.wait(pending, timeout=timeout)
            for future in done:
                if future.exception() is not None:
                    _task._LOG.error("closing a PerLoop value failed", exc_info=future.exception())

    async def aclose(self) -> None:
        """``close()`` without blocking the awaiting coroutine's thread."""
        await Task.run(self.close)

    @override
    def __repr__(self) -> str:
        name = getattr(self._factory, "__qualname__", None) or repr(self._factory)
        return f"PerLoop({name})"


class _LoopParameter:
    __slots__ = ()

    @override
    def __repr__(self) -> str:
        return "Loop"


_LOOP_PARAMETER: Final = _LoopParameter()

Loop: TypeAlias = Annotated[T, _LOOP_PARAMETER]
"""A parameter of an ``@asyncio_task`` function that receives the ``provide()``-d ``T`` of the loop the call runs on.

```python
asyncio_bridge.provide(httpx.AsyncClient, lambda: httpx.AsyncClient(timeout=10), warm=True)

@asyncio_task
async def fetch(url: str, client: Loop[httpx.AsyncClient] = injected) -> dict:
    return (await client.get(url)).json()

data = await fetch("https://...")
```

The caller does not pass it (``= injected`` tells type checkers so); a value the caller does pass wins.
"""


class _Injected:
    __slots__ = ()

    @override
    def __repr__(self) -> str:
        return "injected"


injected: Final[Any] = _Injected()
"""Default for a ``Loop[T]`` parameter: the bridge fills it in, the caller does not pass it."""

_providers: dict[Any, PerLoop[Any]] = {}
_owned_providers: weakref.WeakSet[PerLoop[Any]] = weakref.WeakSet()
_providers_lock = threading.Lock()


def provide(service_type: type[T], source: Callable[[], T | Awaitable[T]] | PerLoop[T], *,
            warm: bool = False) -> PerLoop[T]:
    """Make ``Loop[service_type]`` parameters of ``@asyncio_task`` functions receive one value per loop.

    ``source`` is a factory (plain or ``async def``; ``warm`` as for ``PerLoop``) or an existing
    ``PerLoop``, which stays the caller's to close. Providing a type again replaces the provider;
    values created by a replaced factory are closed. Returns the ``PerLoop`` in use.
    """
    if isinstance(source, PerLoop):
        per_loop = cast(PerLoop[T], source)
    else:
        per_loop = PerLoop(source, warm=warm)
        _owned_providers.add(per_loop)
    with _providers_lock:
        replaced = _providers.get(service_type)
        _providers[service_type] = per_loop
    if replaced is not None and replaced is not per_loop and replaced in _owned_providers:
        ThreadPool.queue(lambda: replaced.close())
    return per_loop


def _provider(service_type: Any) -> PerLoop[Any]:
    per_loop = _providers.get(service_type)
    if per_loop is None:
        name = getattr(service_type, "__qualname__", repr(service_type))
        raise LookupError(f"no per-loop value is provided for {name}: "
                          f"call asyncio_bridge.provide({name}, factory) at startup")
    return per_loop


def _loop_parameters(function: Callable[..., Any]) -> tuple[inspect.Signature, tuple[tuple[str, Any], ...]] | None:
    """The signature and the ``Loop[T]`` parameters of ``function``, or None if it has none."""
    try:
        hints = typing.get_type_hints(function, include_extras=True)
    except Exception as error:
        raw = getattr(function, "__annotations__", {})
        if not any("Loop[" in str(annotation) for annotation in raw.values()):
            return None
        raise TypeError(f"cannot read the annotations of {function.__qualname__} "
                        f"to find its Loop[...] parameters: {error}") from error
    found = tuple(
        (name, get_args(hint)[0]) for name, hint in hints.items()
        if get_origin(hint) is Annotated and any(m is _LOOP_PARAMETER for m in hint.__metadata__)
    )
    return (inspect.signature(function), found) if found else None


def _call_asyncio_task(function: Callable[..., Awaitable[T]], args: tuple[Any, ...], kwargs: dict[str, Any],
                       token: CancellationToken | None, cache: list[Any]) -> Task[T]:
    """One call of an ``@asyncio_task`` function: fill its ``Loop[T]`` parameters on the loop, run it."""
    if not cache:
        cache.append(_loop_parameters(function))
    plan = cache[0]
    if plan is None:
        return run_asyncio(function(*args, **kwargs), token=token)
    signature, parameters = plan
    bound = signature.bind_partial(*args, **kwargs)  # wrong arguments fail here, in the caller
    missing = [(name, service_type) for name, service_type in parameters
               if bound.arguments.get(name, injected) is injected]
    return run_asyncio(_with_loop_values(function, bound, missing), token=token)


async def _with_loop_values(function: Callable[..., Awaitable[T]], bound: inspect.BoundArguments,
                            missing: list[tuple[str, Any]]) -> T:
    for name, service_type in missing:
        bound.arguments[name] = await _provider(service_type).get()
    return await function(*bound.args, **bound.kwargs)


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------

def _reset_after_fork() -> None:
    # Only the forking thread exists in the child: the reactor and loop threads are gone.
    global _pool
    _pool = None


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


def _shutdown_at_exit() -> None:
    try:
        shutdown(timeout=0.5)
    except BaseException:  # noqa: BLE001 - interpreter exit goes on
        _task._LOG.exception("Error during asyncio bridge shutdown")


# Registered after flpit.task's handler (this module imports it first), so it runs before the
# runtime stops: the loops' remaining work still needs the pool.
atexit.register(_shutdown_at_exit)
