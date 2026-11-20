"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Behavioral tests for FlpIt's ThreadLocal[T] implementation.

Test names and scenarios ported from:
- ThreadLocalTests.cs:
  https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading/tests/ThreadLocalTests.cs

Every upstream test keeps its name with a ``test_`` prefix; private helpers keep their
upstream names. Mapping to FlpIt's Python API:

- ``default(T)`` for a value type is passed as ``default=`` (``ThreadLocal[int](default=0)``);
- ``Task.Factory.StartNew(..., TaskCreationOptions.LongRunning, TaskScheduler.Default)`` is
  ``Task.run(..., creation_options=TaskCreationOptions.LONG_RUNNING)``;
- finalizers (``~SetMreOnFinalize``) are ``__del__``; ``GC.Collect()`` is ``gc.collect()``;
  ``WeakReference`` is ``weakref.ref``. CPython's reference counting is a precise GC, so
  the ``IsPreciseGcSupported`` tests run.
"""
from __future__ import annotations

import gc
import os
import threading
import time
import weakref
from collections.abc import Callable
from enum import Enum
from typing import Any

import pytest

from flpit.core.linq import InvalidOperationError
from flpit.task import Task, TaskCreationOptions
from flpit.threading import ManualResetEvent, ObjectDisposedError, ThreadLocal

UNEXPECTED_TIMEOUT = 30.0  # ThreadTestHelpers.UnexpectedTimeoutMilliseconds, in seconds

LONG_RUNNING = TaskCreationOptions.LONG_RUNNING


def test_RunThreadLocalTest1_Ctor() -> None:
    testObject: ThreadLocal[object]
    testObject = ThreadLocal()
    testObject = ThreadLocal(True)
    testObject = ThreadLocal(lambda: object())
    testObject = ThreadLocal(lambda: object(), True)
    assert testObject is not None


def test_RunThreadLocalTest1_Ctor_Negative() -> None:
    try:
        ThreadLocal(None)  # type: ignore[arg-type]
    except TypeError:  # ArgumentNullError
        # No other exception should be thrown.
        # With a previous issue, if the constructor threw an exception, the finalizer would throw an exception as well.
        pass


def test_RunThreadLocalTest2_ToString() -> None:
    tlocal: ThreadLocal[object] = ThreadLocal(lambda: 1)
    assert str(1) == str(tlocal)


def test_RunThreadLocalTest3_IsValueCreated() -> None:
    tlocal = ThreadLocal(lambda: "Test")
    assert not tlocal.is_value_created
    temp = tlocal.value
    assert tlocal.is_value_created
    assert temp == "Test"


def test_RunThreadLocalTest4_Value() -> None:
    # different threads call Value
    numOfThreads = 10
    seenValuesFromAllThreads: list[str] = []
    counter = 0

    def next_value() -> str:
        nonlocal counter
        counter += 1
        return str(counter)

    tlocal = ThreadLocal(next_value)

    def work() -> None:
        value = tlocal.value
        seenValuesFromAllThreads.append(value)

    for _ in range(numOfThreads):
        # LongRunning: upstream wants each task on another (new) thread.
        Task.run(work, creation_options=LONG_RUNNING).wait()
    assert seenValuesFromAllThreads == [str(x) for x in range(1, numOfThreads + 1)]


def test_RunThreadLocalTest4_Value_NegativeCases() -> None:
    tlocal: ThreadLocal[str] | None = None

    def body() -> None:
        nonlocal tlocal
        x = 0

        def factory() -> str:
            nonlocal x
            x += 1
            if x - 1 < 5:
                assert tlocal is not None
                return tlocal.value
            return "Test"

        tlocal = ThreadLocal(factory)
        _ = tlocal.value

    with pytest.raises(InvalidOperationError):
        body()


def test_RunThreadLocalTest5_Dispose() -> None:
    # test recycling the combination index;
    tl: ThreadLocal[str | None] = ThreadLocal(lambda: None)
    assert not tl.is_value_created
    assert tl.value is None

    # Test that a value is not kept alive by a departed thread
    threadLocal: ThreadLocal[SetMreOnFinalize] = ThreadLocal()
    mres = ManualResetEvent(False)

    def store() -> None:
        threadLocal.value = SetMreOnFinalize(mres)

    # LongRunning: a dedicated thread that exits when the task is done.
    Task.run(store, creation_options=LONG_RUNNING)

    def collect() -> None:
        time.sleep(0.001)
        gc.collect()

    WaitForConditionWithCustomDelay(lambda: mres.wait_one(0), collect)


def test_RunThreadLocalTest5_Dispose_Negative() -> None:
    tl = ThreadLocal(lambda: "dispose test")
    value = tl.value
    assert value == "dispose test"

    tl.dispose()

    with pytest.raises(ObjectDisposedError):
        _ = tl.value
    # Failure Case: The Value property of the disposed ThreadLocal object should throw ODE

    with pytest.raises(ObjectDisposedError):
        _ = tl.is_value_created
    # Failure Case: The IsValueCreated property of the disposed ThreadLocal object should throw ODE

    with pytest.raises(ObjectDisposedError):
        _ = str(tl)
    # Failure Case: The ToString method of the disposed ThreadLocal object should throw ODE


def test_RunThreadLocalTest6_SlowPath() -> None:
    # Upstream exercises .NET's fast-path/slow-path slot tables; FlpIt has one path,
    # the observable behavior (independent instances, lazily created values) is the same.
    MaximumFastPathPerInstance = 4096
    locals_int: list[ThreadLocal[int]] = []
    for i in range(MaximumFastPathPerInstance + 10):
        locals_int.append(ThreadLocal(lambda i=i: i))
        _ = locals_int[i].value
    assert [x.value for x in locals_int] == list(range(len(locals_int)))

    # The maximum slowpath for all Ts is MaximumFastPathPerInstance * 4;
    locals_int = [ThreadLocal(lambda i=i: i) for i in range(4096)]
    locals_long = [ThreadLocal(lambda i=i: i) for i in range(4096)]
    locals_float = [ThreadLocal(lambda i=i: float(i)) for i in range(4096)]
    locals_double = [ThreadLocal(lambda i=i: float(i)) for i in range(4096)]
    assert len(locals_int) == len(locals_long) == len(locals_float) == len(locals_double)

    local = ThreadLocal(lambda: "slow path")
    assert local.value == "slow path"


class _Foo:
    """``new object()``: Python's plain ``object()`` cannot be weakly referenced."""


class ThreadLocalWeakReferenceTest:
    def __init__(self) -> None:
        self._foo: _Foo | None = None
        self._wFoo: weakref.ref[_Foo] | None = None

    def Method(self) -> None:
        self._foo = _Foo()
        self._wFoo = weakref.ref(self._foo)

        tl: ThreadLocal[object] = ThreadLocal()
        tl.value = self._foo
        tl.dispose()

    def Run(self) -> None:
        self.Method()
        self._foo = None

        gc.collect()

        # s_foo should have been garbage collected
        assert self._wFoo is not None
        assert self._wFoo() is None


def test_RunThreadLocalTest7_WeakReference() -> None:
    threadLocalWeakReferenceTest = ThreadLocalWeakReferenceTest()
    threadLocalWeakReferenceTest.Run()


def test_RunThreadLocalTest8_Values() -> None:
    # Test adding values and updating values
    threadLocal: ThreadLocal[int] = ThreadLocal(True, default=0)
    assert len(threadLocal.values) == 0, "RunThreadLocalTest8_Values: Expected thread local to initially have 0 values"
    assert threadLocal.value == 0, "RunThreadLocalTest8_Values: Expected initial value of 0"
    assert len(threadLocal.values) == 1, "RunThreadLocalTest8_Values: Expected values count to now be 1 from initialized value"
    assert threadLocal.values[0] == 0, "RunThreadLocalTest8_Values: Expected values to contain initialized value"

    threadLocal.value = 1000
    assert len(threadLocal.values) == 1, "RunThreadLocalTest8_Values: Expected values count to still be 1 after updating existing value"
    assert threadLocal.values[0] == 1000, "RunThreadLocalTest8_Values: Expected values to contain updated value"

    def set_1001() -> None:
        threadLocal.value = 1001

    # ((IAsyncResult)Task.Run(...)).AsyncWaitHandle.WaitOne(): the test thread is not a pool worker.
    Task.run(set_1001).wait()
    assert len(threadLocal.values) == 2, "RunThreadLocalTest8_Values: Expected values count to be 2 now that another thread stored a value"
    assert 1000 in threadLocal.values and 1001 in threadLocal.values, "RunThreadLocalTest8_Values: Expected values to contain both thread's values"

    numTasks = 1000
    for i in range(numTasks):
        def set_i(i: int = i) -> None:
            threadLocal.value = i

        # LongRunning: a new thread per task.
        Task.run(set_i, creation_options=LONG_RUNNING).wait()

    values = threadLocal.values
    if len(values) != 1002:
        message = (
            "RunThreadLocalTest8_Values: Expected values to contain both previous values and 1000 new values. "
            f"Actual count: {len(values)}."
        )
        if values:
            message += " Missing items:" + "".join(f" {i}" for i in range(1002) if i not in values)
        pytest.fail(message)
    for i in range(1000):
        assert i in values, f"RunThreadLocalTest8_Values: Expected values to contain value for thread #: {i}"

    threadLocal.dispose()

    # Test that thread values remain after threads depart
    tl: ThreadLocal[str] = ThreadLocal(True)

    def set_parallel() -> None:
        tl.value = "Parallel"

    t: Task[None] | None = Task.run(set_parallel)
    assert t is not None
    t.wait()
    t = None
    gc.collect()
    assert len(tl.values) == 1, "RunThreadLocalTest8_Values: Expected values count to be 1 from other thread's initialization"
    assert "Parallel" in tl.values, "RunThreadLocalTest8_Values: Expected values to contain 'Parallel'"


def RunThreadLocalTest8Helper(mres: ManualResetEvent) -> None:
    tl: ThreadLocal[object] = ThreadLocal(True)

    def store() -> None:
        tl.value = SetMreOnFinalize(mres)

    t: Task[None] | None = Task.run(store)
    assert t is not None
    t.wait()
    t = None
    gc.collect()
    assert len(tl.values) == 1, "RunThreadLocalTest8_Values: Expected other thread to have set value"
    assert isinstance(tl.values[0], SetMreOnFinalize), "RunThreadLocalTest8_Values: Expected other thread's value to be of the right type"
    tl.dispose()

    with pytest.raises(ObjectDisposedError):
        _ = tl.values


def test_RunThreadLocalTest8_Values_NegativeCases() -> None:
    # Test that Dispose works and that objects are released on dispose
    mres = ManualResetEvent(False)
    RunThreadLocalTest8Helper(mres)

    deadline = time.monotonic() + UNEXPECTED_TIMEOUT  # SpinWait.SpinUntil(..., UnexpectedTimeoutMilliseconds)
    while True:
        gc.collect()
        if mres.wait_one(0) or time.monotonic() >= deadline:
            break

    assert mres.wait_one(0), "RunThreadLocalTest8_Values: Expected thread local to release the object and for it to be finalized"

    # Test that Values property throws an exception unless true was passed into the constructor
    t: ThreadLocal[int] = ThreadLocal()
    t.value = 5
    exceptionCaught: Exception | None = None
    try:
        _ = len(t.values)
    except Exception as ex:
        exceptionCaught = ex

    assert exceptionCaught is not None, "RunThreadLocalTest8_Values: Expected Values to throw an InvalidOperationException. No exception was thrown."
    assert isinstance(exceptionCaught, InvalidOperationError), (
        "RunThreadLocalTest8_Values: Expected Values to throw an InvalidOperationException. "
        f"Wrong exception was thrown: {type(exceptionCaught).__name__}"
    )


def test_RunThreadLocalTest9_Uninitialized() -> None:
    for _ in range(10):
        t1: ThreadLocal[int] = ThreadLocal(default=0)
        t1.value = 177
        t2: ThreadLocal[int] = ThreadLocal(default=0)
        assert not t2.is_value_created, "RunThreadLocalTest9_Uninitialized: The ThreadLocal instance should have been uninitialized."


# upstream: [OuterLoop] (about 0.5s here, so it runs with the normal suite)
def test_ValuesGetterDoesNotThrowUnexpectedExceptionWhenDisposed() -> None:
    startTest = ManualResetEvent(False)
    gotUnexpectedException = ManualResetEvent(False)
    threadLocal: ThreadLocal[int] | None = None
    stop = False

    def creator_disposer() -> None:
        nonlocal threadLocal
        assert startTest.wait_one(UNEXPECTED_TIMEOUT)  # CheckedWait
        while True:
            tl: ThreadLocal[int] = ThreadLocal(track_all_values=True, default=0)
            threadLocal = tl
            tl.value = 1
            tl.dispose()
            if stop:
                break

    waitForCreatorDisposer = CreateGuardedThread(creator_disposer)

    def reader() -> None:
        assert startTest.wait_one(UNEXPECTED_TIMEOUT)  # CheckedWait
        while True:
            tl = threadLocal
            if tl is not None:
                try:
                    _ = tl.values
                except ObjectDisposedError:
                    pass
                except BaseException:
                    gotUnexpectedException.set()
                    raise
            if stop:
                break

    readerCount = max(1, (os.cpu_count() or 1) - 1)
    waitsForReader = [CreateGuardedThread(reader) for _ in range(readerCount)]

    startTest.set()
    failed = gotUnexpectedException.wait_one(0.5)
    stop = True
    for waitForReader in waitsForReader:
        waitForReader()
    waitForCreatorDisposer()
    assert not failed


class UniqueEnumUsedOnlyWithNonInterferenceTest(Enum):
    TRUE = True
    FALSE = False


def test_TestUnrelatedThreadLocalDoesNotInterfereWithTrackAllValues() -> None:
    localThatDoesNotTrackValues: ThreadLocal[UniqueEnumUsedOnlyWithNonInterferenceTest] = ThreadLocal(False)
    localThatDoesTrackValues: ThreadLocal[UniqueEnumUsedOnlyWithNonInterferenceTest] = ThreadLocal(True)

    def Work() -> None:
        localThatDoesNotTrackValues.value = UniqueEnumUsedOnlyWithNonInterferenceTest.TRUE
        localThatDoesTrackValues.value = UniqueEnumUsedOnlyWithNonInterferenceTest.TRUE

    for _ in range(10):
        t = threading.Thread(target=Work)
        t.start()
        t.join()
    gc.collect()
    count = sum(1 for x in localThatDoesTrackValues.values if x == UniqueEnumUsedOnlyWithNonInterferenceTest.TRUE)

    assert count == 10


class SetMreOnFinalize:
    def __init__(self, mres: ManualResetEvent) -> None:
        self._mres = mres

    def __del__(self) -> None:
        self._mres.set()


# =============================================================================
# ThreadTestHelpers
# =============================================================================

def WaitForConditionWithCustomDelay(condition: Callable[[], bool], delay: Callable[[], Any]) -> None:
    deadline = time.monotonic() + UNEXPECTED_TIMEOUT
    while not condition():
        assert time.monotonic() < deadline, "condition not met within UnexpectedTimeoutMilliseconds"
        delay()


def CreateGuardedThread(target: Callable[[], None]) -> Callable[[], None]:
    """Start a background thread; the returned callable joins it and re-raises its exception."""
    errors: list[BaseException] = []

    def guarded() -> None:
        try:
            target()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=guarded, daemon=True)
    thread.start()

    def wait_for_thread() -> None:
        thread.join(UNEXPECTED_TIMEOUT)
        assert not thread.is_alive(), "guarded thread did not finish"
        if errors:
            raise errors[0]

    return wait_for_thread
