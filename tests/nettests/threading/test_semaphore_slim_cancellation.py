"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Cancellation tests for FlpIt's SemaphoreSlim implementation.

Test names and scenarios ported from:
- SemaphoreSlimCancellationTests.cs:
  https://github.com/dotnet/runtime/blob/main/src/libraries/System.Threading/tests/SemaphoreSlimCancellationTests.cs

Upstream class condition: IsMultithreadingSupported (always true for FlpIt).
Timeouts are float seconds; a .NET ``TimeSpan`` becomes a ``timedelta``.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest

from flpit.task import (
    CancellationToken,
    CancellationTokenSource,
    OperationCanceledError,
    Task,
    TaskContinuationOptions,
)
from flpit.threading import SemaphoreSlim, ThreadLocal


def test_CancelBeforeWait() -> None:
    semaphoreSlim = SemaphoreSlim(2)

    cs = CancellationTokenSource()
    cs.cancel()
    ct = cs.token

    millisec = 100
    timeSpan = timedelta(microseconds=10)  # new TimeSpan(100): 100 ticks
    EnsureOperationCanceledExceptionThrown(lambda: semaphoreSlim.wait(ct), ct)
    EnsureOperationCanceledExceptionThrown(lambda: semaphoreSlim.wait(millisec / 1000, ct), ct)
    EnsureOperationCanceledExceptionThrown(lambda: semaphoreSlim.wait(timeSpan, ct), ct)
    semaphoreSlim.dispose()


def test_CancelAfterWait() -> None:
    cancellationTokenSource = CancellationTokenSource()
    cancellationToken = cancellationTokenSource.token

    semaphoreSlim = SemaphoreSlim(0)  # semaphore that will block all waiters

    def cancel_soon() -> None:
        for _ in range(300):
            pass
        cancellationTokenSource.cancel()

    Task.run(cancel_soon)

    # Now wait.. the wait should abort and an exception should be thrown
    EnsureOperationCanceledExceptionThrown(
        lambda: semaphoreSlim.wait(cancellationToken),
        cancellationToken,
    )

    # the token should not have any listeners.
    # currently we don't expose this.. but it was verified manually


@pytest.mark.parametrize("withTimeout", [False, True])
def test_Cancel_WaitAsync_ContinuationInvokedAsynchronously(withTimeout: bool) -> None:
    async def body() -> None:  # await Task.Run(async () => ...): escape xunit's SynchronizationContext
        cts = CancellationTokenSource()
        tl: ThreadLocal[object] = ThreadLocal()

        sentinel = object()

        sem = SemaphoreSlim(0)
        waitTask = (
            sem.wait_async(timedelta(days=1), cts.token)
            if withTimeout
            else sem.wait_async(cts.token)
        )

        def check(prev: Task[bool]) -> None:
            assert prev.status == Task.CANCELLED
            assert tl.value is not sentinel

        continuation = waitTask.continue_with(
            check, token=CancellationToken.none(), options=TaskContinuationOptions.EXECUTE_SYNCHRONOUSLY
        )

        assert not continuation.done()  # TaskStatus.WaitingForActivation
        assert sem.current_count == 0

        tl.value = sentinel
        cts.cancel()
        tl.value = None

        await continuation

    Task.run(body).result()


def EnsureOperationCanceledExceptionThrown(action: Callable[[], Any], token: CancellationToken) -> None:
    with pytest.raises(OperationCanceledError) as info:
        action()
    assert type(info.value) is OperationCanceledError  # Assert.Throws: exact type
    assert info.value.token == token
