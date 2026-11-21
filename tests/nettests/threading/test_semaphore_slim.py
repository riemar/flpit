"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Behavioral tests for FlpIt's SemaphoreSlim implementation.

Test names and scenarios ported from:
- SemaphoreSlimTests.cs:
  https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading/tests/SemaphoreSlimTests.cs

Every upstream test keeps its name with a ``test_`` prefix; private helpers keep
their upstream names. Mapping to FlpIt's Python API:

- timeouts are float seconds (upstream milliseconds are divided by 1000); a .NET
  ``TimeSpan`` becomes a ``timedelta``; ``Timeout.Infinite`` is ``-1``;
- ``Task.Run`` / ``Task.WaitAll`` / ``Wait()`` are ``Task.run`` / ``Task.wait_all`` / ``wait()``;
  ``Task.Factory.StartNew(..., TaskCreationOptions.LongRunning)`` is ``Task.run(...,
  creation_options=TaskCreationOptions.LONG_RUNNING)``; an ``async Task`` test body runs
  via ``Task.run``;
- ``.Result`` is ``.result()``: no awaited task faults in these tests, so .NET's extra
  AggregateException wrapping of ``.Result`` never comes into play;
- ``ThreadLocal<T>`` is ``flpit.threading.ThreadLocal``; ``Interlocked`` a lock-guarded counter.

FlpIt always runs multithreaded. Upstream cases that only exist on single-threaded
(WASM) or browser JS-interop runtimes run where their assertions still apply and
are skipped, with the reason, where they assert PlatformNotSupportedException.
"""
from __future__ import annotations

import gc
import logging
import threading
import time
from datetime import timedelta
from enum import Enum, auto
from typing import Any, override

import pytest

from flpit.core.linq import ArgumentOutOfRangeError
from flpit.task import CancellationToken, CancellationTokenSource, OperationCanceledError, Task, TaskCreationOptions
from flpit.threading import (
    ManualResetEvent,
    ObjectDisposedError,
    SemaphoreFullError,
    SemaphoreSlim,
    ThreadLocal,
    Timeout,
)

INT_MAX = 2_147_483_647
UINT_MAX = 4_294_967_295


def _run(async_body: Any) -> Any:
    """Run an upstream ``async Task`` test body on the FlpIt runtime and wait for it."""
    return Task.run(async_body).result()


def _ms(milliseconds: int) -> float:
    """Upstream millisecond timeout as FlpIt seconds, keeping Timeout.Infinite."""
    return Timeout.INFINITE if milliseconds == -1 else milliseconds / 1000


class _Interlocked:
    """Thread-safe int counter (Interlocked.Increment / Decrement)."""

    def __init__(self, value: int = 0) -> None:
        self._lock = threading.Lock()
        self.value = value

    def increment(self) -> int:
        with self._lock:
            self.value += 1
            return self.value

    def decrement(self) -> int:
        with self._lock:
            self.value -= 1
            return self.value


@pytest.mark.parametrize("waiterCount", [1, 3])
def test_AsyncWaitersWorkWithoutOtherThreads(waiterCount: int) -> None:
    async def body() -> None:
        with SemaphoreSlim(0, waiterCount) as semaphore:
            handle = semaphore.available_wait_handle
            waiters = []
            for _ in range(waiterCount):
                waiter = semaphore.wait_async(Timeout.INFINITE)
                assert not waiter.done()
                waiters.append(waiter)

            assert semaphore.release(waiterCount) == 0
            for waiter in waiters:
                assert await waiter
            assert semaphore.current_count == 0
            assert not handle.wait_one(0)
            assert not await semaphore.wait_async(0)

            assert semaphore.release() == 0
            assert handle.wait_one(0)
            assert await semaphore.wait_async(0)
            assert not handle.wait_one(0)

    _run(body)


def test_AsyncCancellationDoesNotLosePermits() -> None:
    async def body() -> None:
        with SemaphoreSlim(0, 1) as semaphore, CancellationTokenSource() as cancellation:
            canceled = semaphore.wait_async(Timeout.INFINITE, cancellation.token)
            next_ = semaphore.wait_async(Timeout.INFINITE)
            cancellation.cancel()
            with pytest.raises(OperationCanceledError):
                await canceled
            assert semaphore.release() == 0
            assert await next_
            assert semaphore.current_count == 0
            assert not await semaphore.wait_async(0)

    _run(body)


@pytest.mark.parametrize("millisecondsTimeout", [0, 10])
def test_AsyncTimeoutDoesNotLosePermits(millisecondsTimeout: int) -> None:
    async def body() -> None:
        with SemaphoreSlim(0, 1) as semaphore:
            assert not await semaphore.wait_async(_ms(millisecondsTimeout))
            assert semaphore.release() == 0
            assert semaphore.current_count == 1
            assert await semaphore.wait_async(0)
            assert semaphore.current_count == 0

    _run(body)


@pytest.mark.parametrize(
    "registerReleaseFirst",
    [
        False,
        # Upstream runs this only on single-threaded runtimes (IsCoreCLR && IsNotMultithreadingSupported),
        # where the deferred cancellation step deterministically runs after every cancellation callback.
        # With the release callback registered first it runs last (callbacks are LIFO), so on a
        # multithreaded runtime the pool can resolve the cancellation before release() runs: a race.
        # (registerReleaseFirst=False is deterministic: release() runs first and wins.)
        pytest.param(True, marks=pytest.mark.skip(
            reason="upstream: single-threaded runtimes only; racy on FlpIt's multithreaded runtime")),
    ],
)
def test_SingleThreadedReleaseDuringCancellation(registerReleaseFirst: bool) -> None:
    async def body() -> None:
        with SemaphoreSlim(0, 1) as semaphore, CancellationTokenSource() as cancellation:
            registration = None
            if registerReleaseFirst:
                registration = cancellation.token.register(lambda: semaphore.release())

            waiter = semaphore.wait_async(Timeout.INFINITE, cancellation.token)
            if not registerReleaseFirst:
                registration = cancellation.token.register(lambda: semaphore.release())

            try:
                cancellation.cancel()
                assert await waiter
                assert semaphore.current_count == 0
            finally:
                assert registration is not None
                registration.dispose()

    _run(body)


_PNSE_SKIP = pytest.mark.skip(
    reason="asserts PlatformNotSupportedException for an infinite blocking wait on a "
           "single-threaded runtime; FlpIt is always multithreaded, so the wait would block forever"
)


@pytest.mark.parametrize(
    ("count", "millisecondsTimeout"),
    [
        (0, 0),
        (1, 0),
        (0, 1),
        (1, 1),
        pytest.param(0, -1, marks=_PNSE_SKIP),
        (1, -1),
        (0, 20),
        (1, 20),
    ],
)
def test_SingleThreadedSynchronousWaitHonorsAvailableCount(count: int, millisecondsTimeout: int) -> None:
    # Upstream: IsNotMultithreadingSupported. Apart from the PlatformNotSupportedException
    # branch (skipped above), every assertion holds on a multithreaded runtime too.
    with SemaphoreSlim(count, 1) as semaphore:
        handle = semaphore.available_wait_handle
        if count != 0:
            assert semaphore.wait(_ms(millisecondsTimeout))
            assert semaphore.current_count == 0
            assert not handle.wait_one(0)
            semaphore.release()
            assert handle.wait_one(0)
            assert semaphore.wait(timedelta(milliseconds=millisecondsTimeout))
            assert not handle.wait_one(0)
        elif millisecondsTimeout != Timeout.INFINITE:
            stopwatch = time.perf_counter()
            assert not semaphore.wait(_ms(millisecondsTimeout))
            assert (time.perf_counter() - stopwatch) * 1000 >= max(0, millisecondsTimeout - 1)
            stopwatch = time.perf_counter()
            assert not semaphore.wait(timedelta(milliseconds=millisecondsTimeout))
            assert (time.perf_counter() - stopwatch) * 1000 >= max(0, millisecondsTimeout - 1)
        else:
            raise AssertionError("unreachable: skipped (PlatformNotSupportedException case)")
        assert semaphore.current_count == 0


_JS_INTEROP_SKIP = pytest.mark.skip(
    reason="asserts PlatformNotSupportedException from the browser's JS-interop blocking policy; "
           "FlpIt has no such policy (warnOnly=True cases run)"
)


@pytest.mark.parametrize(
    ("millisecondsTimeout", "queueAsyncWaiter", "warnOnly"),
    [
        pytest.param(0, False, False, marks=_JS_INTEROP_SKIP),
        pytest.param(20, False, False, marks=_JS_INTEROP_SKIP),
        pytest.param(0, True, False, marks=_JS_INTEROP_SKIP),
        pytest.param(20, True, False, marks=_JS_INTEROP_SKIP),
        (0, False, True),
        (20, False, True),
        (0, True, True),
        (20, True, True),
    ],
)
def test_WaitOnJSInteropThreadHonorsFiniteTimeouts(
        millisecondsTimeout: int, queueAsyncWaiter: bool, warnOnly: bool
) -> None:
    # Upstream: IsBrowser && IsWasmThreadingSupported, run under
    # ThreadTestHelpers.RunWithJSInteropBlockingPolicy. With warnOnly the policy only logs,
    # so the scenario is a finite sync wait (optionally queued behind an async waiter).
    async def body() -> None:
        with SemaphoreSlim(0, 1) as semaphore:
            async_waiter = semaphore.wait_async(Timeout.INFINITE) if queueAsyncWaiter else None

            # RunWithJSInteropBlockingPolicy(..., warnOnly) body:
            stopwatch = time.perf_counter()
            assert not semaphore.wait(_ms(millisecondsTimeout))
            assert (time.perf_counter() - stopwatch) * 1000 >= max(0, millisecondsTimeout - 1)
            stopwatch = time.perf_counter()
            assert not semaphore.wait(timedelta(milliseconds=millisecondsTimeout))
            assert (time.perf_counter() - stopwatch) * 1000 >= max(0, millisecondsTimeout - 1)
            # if (!warnOnly) Assert.Throws<PlatformNotSupportedException>(() => semaphore.Wait());
            # -> only in the skipped cases.

            semaphore.release()
            if queueAsyncWaiter:
                assert async_waiter is not None
                assert await async_waiter
                assert semaphore.current_count == 0
            else:
                assert semaphore.wait(0)

    _run(body)


class SemaphoreSlimActions(Enum):
    """SemaphoreSlim public methods and properties to be tested."""

    Constructor = auto()
    Wait = auto()
    WaitAsync = auto()
    Release = auto()
    Dispose = auto()
    CurrentCount = auto()
    AvailableWaitHandle = auto()


def test_RunSemaphoreSlimTest0_Ctor() -> None:
    RunSemaphoreSlimTest0_Helper(0, 10, None)
    RunSemaphoreSlimTest0_Helper(5, 10, None)
    RunSemaphoreSlimTest0_Helper(10, 10, None)


def test_RunSemaphoreSlimTest0_Ctor_Negative() -> None:
    RunSemaphoreSlimTest0_Helper(10, 0, ArgumentOutOfRangeError)
    RunSemaphoreSlimTest0_Helper(10, -1, ArgumentOutOfRangeError)
    RunSemaphoreSlimTest0_Helper(-1, 10, ArgumentOutOfRangeError)


def test_RunSemaphoreSlimTest1_Wait() -> None:
    # Infinite timeout
    RunSemaphoreSlimTest1_Wait_Helper(10, 10, -1, True, None)
    RunSemaphoreSlimTest1_Wait_Helper(1, 10, -1, True, None)

    # Zero timeout
    RunSemaphoreSlimTest1_Wait_Helper(10, 10, 0, True, None)
    RunSemaphoreSlimTest1_Wait_Helper(1, 10, 0, True, None)
    RunSemaphoreSlimTest1_Wait_Helper(0, 10, 0, False, None)

    # Positive timeout
    RunSemaphoreSlimTest1_Wait_Helper(10, 10, 10, True, None)
    RunSemaphoreSlimTest1_Wait_Helper(1, 10, 10, True, None)
    RunSemaphoreSlimTest1_Wait_Helper(0, 10, 10, False, None)
    RunSemaphoreSlimTest1_Wait_Helper(1, 10, timedelta(milliseconds=UINT_MAX), True, None)


def test_Wait_SingleThreaded() -> None:
    # Upstream: IsNotMultithreadingSupported. Every assertion but the last holds on a
    # multithreaded runtime too; the last one is commented out below.
    with SemaphoreSlim(1, 1) as semaphore:
        semaphore.wait()
        semaphore.release()
        semaphore.wait(CancellationToken.none())
        semaphore.release()
        assert semaphore.wait(_ms(1))
        semaphore.release()
        assert semaphore.wait(timedelta(milliseconds=1))
        semaphore.release()
        assert semaphore.wait(0, CancellationToken.none())

        assert not semaphore.wait(0)
        assert not semaphore.wait(_ms(1))
        # Assert.Throws<PlatformNotSupportedException>(() => semaphore.Wait());
        # -> single-threaded runtimes only: on FlpIt this blocks forever, so it is not run.


def test_RunSemaphoreSlimTest1_Wait_NegativeCases() -> None:
    # Invalid timeout
    RunSemaphoreSlimTest1_Wait_Helper(10, 10, -10, False, ArgumentOutOfRangeError)


def test_RunSemaphoreSlimTest1_WaitAsync() -> None:
    # Infinite timeout
    RunSemaphoreSlimTest1_WaitAsync_Helper(10, 10, -1, True, None)
    RunSemaphoreSlimTest1_WaitAsync_Helper(1, 10, -1, True, None)

    # Zero timeout
    RunSemaphoreSlimTest1_WaitAsync_Helper(10, 10, 0, True, None)
    RunSemaphoreSlimTest1_WaitAsync_Helper(1, 10, 0, True, None)
    RunSemaphoreSlimTest1_WaitAsync_Helper(0, 10, 0, False, None)

    # Positive timeout
    RunSemaphoreSlimTest1_WaitAsync_Helper(10, 10, 10, True, None)
    RunSemaphoreSlimTest1_WaitAsync_Helper(1, 10, 10, True, None)
    RunSemaphoreSlimTest1_WaitAsync_Helper(0, 10, 10, False, None)
    RunSemaphoreSlimTest1_WaitAsync_Helper(1, 10, timedelta(milliseconds=UINT_MAX), True, None)
    RunSemaphoreSlimTest1_WaitAsync_Helper(1, 10, timedelta.max, True, None)


def test_RunSemaphoreSlimTest1_WaitAsync_NegativeCases() -> None:
    # Invalid timeout
    RunSemaphoreSlimTest1_WaitAsync_Helper(10, 10, -10, True, ArgumentOutOfRangeError)
    RunSemaphoreSlimTest1_WaitAsync2()


def test_RunSemaphoreSlimTest2_Release() -> None:
    # Valid release count
    RunSemaphoreSlimTest2_Release_Helper(5, 10, 1, None)
    RunSemaphoreSlimTest2_Release_Helper(0, 10, 1, None)
    RunSemaphoreSlimTest2_Release_Helper(5, 10, 5, None)


def test_RunSemaphoreSlimTest2_Release_NegativeCases() -> None:
    # Invalid release count
    RunSemaphoreSlimTest2_Release_Helper(5, 10, 0, ArgumentOutOfRangeError)
    RunSemaphoreSlimTest2_Release_Helper(5, 10, -1, ArgumentOutOfRangeError)

    # Semaphore Full
    RunSemaphoreSlimTest2_Release_Helper(10, 10, 1, SemaphoreFullError)
    RunSemaphoreSlimTest2_Release_Helper(5, 10, 6, SemaphoreFullError)
    RunSemaphoreSlimTest2_Release_Helper(INT_MAX - 1, INT_MAX, 10, SemaphoreFullError)


def test_RunSemaphoreSlimTest4_Dispose() -> None:
    RunSemaphoreSlimTest4_Dispose_Helper(5, 10, None, None)
    RunSemaphoreSlimTest4_Dispose_Helper(5, 10, SemaphoreSlimActions.CurrentCount, None)
    RunSemaphoreSlimTest4_Dispose_Helper(5, 10, SemaphoreSlimActions.Wait, ObjectDisposedError)
    RunSemaphoreSlimTest4_Dispose_Helper(5, 10, SemaphoreSlimActions.WaitAsync, ObjectDisposedError)
    RunSemaphoreSlimTest4_Dispose_Helper(5, 10, SemaphoreSlimActions.Release, ObjectDisposedError)
    RunSemaphoreSlimTest4_Dispose_Helper(5, 10, SemaphoreSlimActions.AvailableWaitHandle, ObjectDisposedError)


def test_RunSemaphoreSlimTest5_CurrentCount() -> None:
    RunSemaphoreSlimTest5_CurrentCount_Helper(5, 10, None)
    RunSemaphoreSlimTest5_CurrentCount_Helper(5, 10, SemaphoreSlimActions.Wait)
    RunSemaphoreSlimTest5_CurrentCount_Helper(5, 10, SemaphoreSlimActions.WaitAsync)
    RunSemaphoreSlimTest5_CurrentCount_Helper(5, 10, SemaphoreSlimActions.Release)


def test_RunSemaphoreSlimTest7_AvailableWaitHandle() -> None:
    RunSemaphoreSlimTest7_AvailableWaitHandle_Helper(5, 10, None, True)
    RunSemaphoreSlimTest7_AvailableWaitHandle_Helper(0, 10, None, False)

    RunSemaphoreSlimTest7_AvailableWaitHandle_Helper(5, 10, SemaphoreSlimActions.Wait, True)
    RunSemaphoreSlimTest7_AvailableWaitHandle_Helper(1, 10, SemaphoreSlimActions.Wait, False)
    RunSemaphoreSlimTest7_AvailableWaitHandle_Helper(5, 10, SemaphoreSlimActions.Wait, True)

    RunSemaphoreSlimTest7_AvailableWaitHandle_Helper(5, 10, SemaphoreSlimActions.WaitAsync, True)
    RunSemaphoreSlimTest7_AvailableWaitHandle_Helper(1, 10, SemaphoreSlimActions.WaitAsync, False)
    RunSemaphoreSlimTest7_AvailableWaitHandle_Helper(5, 10, SemaphoreSlimActions.WaitAsync, True)
    RunSemaphoreSlimTest7_AvailableWaitHandle_Helper(0, 10, SemaphoreSlimActions.Release, True)


# =============================================================================
# Helpers (upstream names)
# =============================================================================

def _check_exception(ex: Exception, exceptionType: type[Exception] | None) -> None:
    # Assert.NotNull(exceptionType); Assert.IsType(exceptionType, ex);
    assert exceptionType is not None, f"unexpected {type(ex).__name__}: {ex}"
    assert type(ex) is exceptionType, f"expected {exceptionType.__name__}, got {type(ex).__name__}: {ex}"


def RunSemaphoreSlimTest0_Helper(initial: int, maximum: int, exceptionType: type[Exception] | None) -> None:
    """Test SemaphoreSlim constructor."""
    try:
        semaphore = SemaphoreSlim(initial, maximum)
        assert semaphore.current_count == initial
    except Exception as ex:
        _check_exception(ex, exceptionType)


def RunSemaphoreSlimTest1_Wait_Helper(
        initial: int, maximum: int, timeout: int | timedelta, returnValue: bool,
        exceptionType: type[Exception] | None,
) -> None:
    """Test SemaphoreSlim Wait; ``timeout`` is upstream int milliseconds or a timedelta."""
    semaphore = SemaphoreSlim(initial, maximum)
    try:
        if isinstance(timeout, timedelta):
            result = semaphore.wait(timeout)
        else:
            result = semaphore.wait(_ms(timeout))
        assert result == returnValue
        if result:
            assert semaphore.current_count == initial - 1
    except Exception as ex:
        _check_exception(ex, exceptionType)


def RunSemaphoreSlimTest1_WaitAsync_Helper(
        initial: int, maximum: int, timeout: int | timedelta, returnValue: bool,
        exceptionType: type[Exception] | None,
) -> None:
    """Test SemaphoreSlim WaitAsync; ``timeout`` is upstream int milliseconds or a timedelta."""
    semaphore = SemaphoreSlim(initial, maximum)
    try:
        if isinstance(timeout, timedelta):
            result = semaphore.wait_async(timeout).result()
        else:
            result = semaphore.wait_async(_ms(timeout)).result()
        assert result == returnValue
        if result:
            assert semaphore.current_count == initial - 1
    except Exception as ex:
        _check_exception(ex, exceptionType)


def RunSemaphoreSlimTest1_WaitAsync2() -> None:
    """Verify that SemaphoreSlim.release() does not execute any user code synchronously."""
    semaphore = SemaphoreSlim(1)
    counter = ThreadLocal(lambda: 0)
    nonZeroObserved = False

    asyncActions = 20
    remAsyncActions = _Interlocked(asyncActions)
    mre = ManualResetEvent(False)

    async def doWorkAsync(i: int) -> None:
        nonlocal nonZeroObserved
        await semaphore.wait_async()
        if counter.value > 0:
            nonZeroObserved = True

        counter.value = counter.value + 1
        semaphore.release()
        counter.value = counter.value - 1

        if remAsyncActions.decrement() == 0:
            mre.set()

    semaphore.wait()
    for i in range(asyncActions):
        Task.run(doWorkAsync, i)  # async void: fire and forget
    semaphore.release()

    mre.wait_one()

    assert not nonZeroObserved, (
        "RunSemaphoreSlimTest1_WaitAsync2:  FAILED.  "
        "SemaphoreSlim.Release() seems to have synchronously invoked a continuation."
    )


def RunSemaphoreSlimTest2_Release_Helper(
        initial: int, maximum: int, releaseCount: int, exceptionType: type[Exception] | None
) -> None:
    """Test SemaphoreSlim Release."""
    semaphore = SemaphoreSlim(initial, maximum)
    try:
        oldCount = semaphore.release(releaseCount)
        assert oldCount == initial
        assert semaphore.current_count == initial + releaseCount
    except Exception as ex:
        _check_exception(ex, exceptionType)


def CallSemaphoreAction(semaphore: SemaphoreSlim, action: SemaphoreSlimActions | None, param: Any) -> Any:
    """Call a specific SemaphoreSlim method or property."""
    if action == SemaphoreSlimActions.Wait:
        if isinstance(param, timedelta):
            return semaphore.wait(param)
        elif isinstance(param, int):
            return semaphore.wait(_ms(param))
        semaphore.wait()
        return None
    elif action == SemaphoreSlimActions.WaitAsync:
        if isinstance(param, timedelta):
            return semaphore.wait_async(param).result()
        elif isinstance(param, int):
            return semaphore.wait_async(_ms(param)).result()
        semaphore.wait_async().wait()
        return None
    elif action == SemaphoreSlimActions.Release:
        if param is not None:
            return semaphore.release(param)
        return semaphore.release()
    elif action == SemaphoreSlimActions.Dispose:
        semaphore.dispose()
        return None
    elif action == SemaphoreSlimActions.CurrentCount:
        return semaphore.current_count
    elif action == SemaphoreSlimActions.AvailableWaitHandle:
        return semaphore.available_wait_handle
    return None


def RunSemaphoreSlimTest4_Dispose_Helper(
        initial: int, maximum: int, action: SemaphoreSlimActions | None,
        exceptionType: type[Exception] | None,
) -> None:
    """Test SemaphoreSlim Dispose."""
    semaphore = SemaphoreSlim(initial, maximum)
    try:
        semaphore.dispose()
        CallSemaphoreAction(semaphore, action, None)
    except Exception as ex:
        _check_exception(ex, exceptionType)


def RunSemaphoreSlimTest5_CurrentCount_Helper(
        initial: int, maximum: int, action: SemaphoreSlimActions | None
) -> None:
    """Test SemaphoreSlim CurrentCount property."""
    semaphore = SemaphoreSlim(initial, maximum)

    CallSemaphoreAction(semaphore, action, None)
    if action is None:
        assert semaphore.current_count == initial
    else:
        assert semaphore.current_count == initial + (1 if action == SemaphoreSlimActions.Release else -1)


def RunSemaphoreSlimTest7_AvailableWaitHandle_Helper(
        initial: int, maximum: int, action: SemaphoreSlimActions | None, state: bool
) -> None:
    """Test SemaphoreSlim AvailableWaitHandle property."""
    semaphore = SemaphoreSlim(initial, maximum)

    CallSemaphoreAction(semaphore, action, None)
    assert semaphore.available_wait_handle is not None
    assert semaphore.available_wait_handle.wait_one(0) == state


# =============================================================================
# Concurrency
# =============================================================================

@pytest.mark.parametrize(
    ("initial", "maximum", "waitThreads", "releaseThreads", "succeededWait", "failedWait", "finalCount", "timeout"),
    [
        (5, 1000, 50, 50, 50, 0, 5, 1000),
        (0, 1000, 50, 25, 25, 25, 0, 500),
        (0, 1000, 50, 0, 0, 50, 0, 100),
    ],
)
def test_RunSemaphoreSlimTest8_ConcWaitAndRelease(
        initial: int, maximum: int, waitThreads: int, releaseThreads: int,
        succeededWait: int, failedWait: int, finalCount: int, timeout: int,
) -> None:
    """Test SemaphoreSlim Wait and Release methods concurrently."""
    semaphore = SemaphoreSlim(initial, maximum)
    succeeded = _Interlocked()
    failed = _Interlocked()
    mre = ManualResetEvent(False)

    def wait_work() -> None:
        mre.wait_one()
        if semaphore.wait(_ms(timeout)):
            succeeded.increment()
        else:
            failed.increment()

    def release_work() -> None:
        mre.wait_one()
        semaphore.release()

    # launch threads
    threads: list[Task[None]] = []
    for i in range(waitThreads + releaseThreads):
        if i < waitThreads:
            # We are creating the Task using TaskCreationOptions.LongRunning to
            # force usage of another thread (which will be the case on the default scheduler
            # with its current implementation).  Without this, the release tasks will likely get
            # queued behind the wait tasks in the pool, making it very likely that the wait tasks
            # will starve the very tasks that when run would unblock them.
            threads.append(Task.run(wait_work, creation_options=TaskCreationOptions.LONG_RUNNING))
        else:
            threads.append(Task.run(release_work))

    mre.set()
    # wait work to be done
    Task.wait_all(threads)
    # check the number of succeeded and failed wait
    assert succeeded.value == succeededWait
    assert failed.value == failedWait
    assert semaphore.current_count == finalCount


@pytest.mark.parametrize(
    ("initial", "maximum", "waitThreads", "releaseThreads", "succeededWait", "failedWait", "finalCount", "timeout"),
    [
        (5, 1000, 50, 50, 50, 0, 5, 500),
        (0, 1000, 50, 25, 25, 25, 0, 500),
        (0, 1000, 50, 0, 0, 50, 0, 100),
    ],
)
def test_RunSemaphoreSlimTest8_ConcWaitAsyncAndRelease(
        initial: int, maximum: int, waitThreads: int, releaseThreads: int,
        succeededWait: int, failedWait: int, finalCount: int, timeout: int,
) -> None:
    """Test SemaphoreSlim WaitAsync and Release methods concurrently."""
    semaphore = SemaphoreSlim(initial, maximum)
    succeeded = _Interlocked()
    failed = _Interlocked()
    mre = ManualResetEvent(False)

    async def wait_work() -> None:
        mre.wait_one()
        if await semaphore.wait_async(_ms(timeout)):
            succeeded.increment()
        else:
            failed.increment()

    def release_work() -> None:
        mre.wait_one()
        semaphore.release()

    tasks = [Task.run(wait_work) if i < waitThreads else Task.run(release_work)
             for i in range(waitThreads + releaseThreads)]

    mre.set()
    # wait work to be done
    Task.wait_all(tasks)

    assert succeeded.value == succeededWait
    assert failed.value == failedWait
    assert semaphore.current_count == finalCount


@pytest.mark.parametrize(("syncWaiters", "asyncWaiters"), [(10, 10), (1, 10), (10, 1)])
def test_TestConcurrentWaitAndWaitAsync(syncWaiters: int, asyncWaiters: int) -> None:
    totalWaiters = syncWaiters + asyncWaiters

    semaphore = SemaphoreSlim(0)
    ITERS = 10

    def sync_work() -> None:
        for _ in range(ITERS):
            semaphore.wait()
            semaphore.release()

    async def async_work() -> None:
        for _ in range(ITERS):
            await semaphore.wait_async()
            semaphore.release()

    tasks = [Task.run(sync_work) for _ in range(syncWaiters)]
    tasks += [Task.run(async_work) for _ in range(syncWaiters, totalWaiters)]

    semaphore.release(totalWaiters // 2)
    Task.wait_all(tasks)


def test_WaitAsync_Timeout_NoUnhandledException() -> None:
    # Upstream runs in a RemoteExecutor child process and watches
    # TaskScheduler.UnobservedTaskException across GCs. FlpIt has no unobserved-task
    # event; its equivalents are the runtime exception handler (continuation and
    # scheduler errors) and the "task" logger (timer callback errors). Both are
    # observed in-process and restored afterwards.
    errors: list[Any] = []

    class _Capture(logging.Handler):
        @override
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.ERROR:
                errors.append(record.getMessage())

    capture = _Capture()
    task_logger = logging.getLogger("task")
    task_logger.addHandler(capture)
    Task.set_exception_handler(lambda context: errors.append(context))
    try:
        async def body() -> None:
            sem = SemaphoreSlim(0)
            for _ in range(2):
                await sem.wait_async(_ms(1))
                gc.collect()

        _run(body)
        time.sleep(0.05)  # let any late timer callback report
    finally:
        Task.set_exception_handler(None)
        task_logger.removeHandler(capture)

    assert errors == []
