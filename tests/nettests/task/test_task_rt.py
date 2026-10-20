"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Pytest migration of tests from current dotnet/runtime TaskRtTests.cs.

Upstream source (current .NET runtime only; no Mono test sources):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/Task/TaskRtTests.cs

Every public test method in that C# file is represented below. The original
PascalCase method names are preserved with a ``test_`` prefix. Unsupported .NET
semantics remain visible as explicit skips; adaptations are documented inline.
"""
from __future__ import annotations

import pytest

from flpit.task import CancellationTokenSource, OperationCanceledError, Task


def _unsupported(feature: str) -> None:
    pytest.skip(f"Upstream .NET test requires unsupported FlpIt API: {feature}")


def test_RunRunTests() -> None:
    """Adapted: Task.run executes synchronous callables and async functions."""
    assert Task.run(lambda: 7).result() == 7

    async def async_value() -> int:
        await Task.delay(0.005)
        return 42

    assert Task.run(async_value).result() == 42


def test_RunRunTests_Cancellation_Negative() -> None:
    source = CancellationTokenSource()
    source.cancel()
    invoked = []

    try:
        task = Task.run(lambda: invoked.append("ran"), token=source.token)
        with pytest.raises(OperationCanceledError):
            task.result()
        assert task.cancelled()
        assert invoked == []
    finally:
        source.dispose()


def test_RunRunTests_FastPathTests() -> None:
    """Adapted: Task.run can await an existing Task handle and relay its outcome."""
    completed = Task.run(lambda: 42)
    assert completed.result() == 42
    wrapper = Task.run(completed)
    assert wrapper.result() == 42

    error = ValueError("faulted source")

    def fail() -> int:
        raise error

    failed = Task.run(fail)
    with pytest.raises(ValueError, match="faulted source"):
        failed.result()
    relay = Task.run(failed)
    with pytest.raises(ValueError, match="faulted source") as caught:
        relay.result()
    assert caught.value is error


def test_RunRunTests_Unwrap_NegativeCases() -> None:
    _unsupported("Task.Run(Func<Task>) automatic unwrapping of a Task returned by a synchronous delegate")


def test_RunFromResult() -> None:
    _unsupported("Task.FromResult immediate-completion factory and object-identity semantics")


def test_FromResult_KnownResults_Cached() -> None:
    _unsupported("Task.FromResult implementation-specific result caching; not part of FlpIt's API")


def test_RunFromResult_FaultedTask() -> None:
    """Adapted: a failed task retains its exception and result() observes it."""
    error = RuntimeError("uh oh")

    def fail() -> object:
        raise error

    task = Task.run(fail)
    with pytest.raises(RuntimeError, match="uh oh") as caught:
        task.result()
    assert caught.value is error


@pytest.mark.parametrize("seconds", [-2.0, -2147483648.0, -0.001])
def test_TaskDelay_OutOfBounds_ThrowsException(seconds: float) -> None:
    """Adapted: negative durations are invalid; .NET's numeric max bounds don't apply to seconds."""
    with pytest.raises(ValueError):
        Task.delay(seconds)


def test_TaskDelay_MaxSupported_Success() -> None:
    """Adapted: a very long timer can be cancelled; Python has no .NET uint-ms cap."""
    source = CancellationTokenSource()
    try:
        task = Task.delay(1_000_000_000.0, token=source.token)
        assert not task.done()
        source.cancel()
        with pytest.raises(OperationCanceledError):
            task.result()
        assert task.cancelled()
    finally:
        source.dispose()


def test_RunDelayTests() -> None:
    zero = Task.delay(0)
    zero.result()
    assert zero.done()

    delayed = Task.delay(0.01)
    assert delayed.result() is None
    assert delayed.done()


def test_RunDelayTests_NegativeCases() -> None:
    with pytest.raises(ValueError):
        Task.delay(-2)
    with pytest.raises(TypeError):
        Task.delay(1, token=object())

    source = CancellationTokenSource()
    try:
        delayed = Task.delay(60, token=source.token)
        source.cancel()
        with pytest.raises(OperationCanceledError):
            delayed.result()
        assert delayed.cancelled()
    finally:
        source.dispose()


def test_TaskDelay_Cancellation_ContinuationsInvokedAsynchronously() -> None:
    _unsupported("ContinueWith, ExecuteSynchronously, thread-local continuation assertions")


def test_RunExceptionWrappingTest() -> None:
    """Adapted: no unnecessary wrapper is added across Task.run/await boundaries."""
    error = ValueError("inner failure")

    async def fail() -> int:
        await Task.delay(0)
        raise error

    task = Task.run(fail)
    with pytest.raises(ValueError, match="inner failure") as caught:
        task.result()
    assert caught.value is error

    aggregate = Task.when_all([Task.run(fail)])
    with pytest.raises(ValueError, match="inner failure") as caught_aggregate:
        aggregate.result()
    assert caught_aggregate.value is error


def test_RunHideSchedulerTests() -> None:
    _unsupported("TaskScheduler.Current, TaskCreationOptions.HideScheduler, and ContinueWith")


def test_RunHideSchedulerTests_Negative() -> None:
    _unsupported("TaskCompletionSource validation of TaskCreationOptions.HideScheduler")


def test_RunDenyChildAttachTests() -> None:
    _unsupported("AttachedToParent/DenyChildAttach task hierarchy semantics")


def test_RunBasicTaskWithResultTest_Negative() -> None:
    """Adapted: Task.run validates the callable/awaitable at the API boundary."""
    with pytest.raises(TypeError):
        Task.run(None)
    with pytest.raises(TypeError):
        Task.run(object())
