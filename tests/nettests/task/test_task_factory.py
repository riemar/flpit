"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Pytest migration of tests from current dotnet/runtime TaskFactoryTests.cs.

Upstream source (current .NET runtime only; no Mono test sources):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/TaskFactory/TaskFactoryTests.cs

All public test-method names are retained with the ``test_`` prefix. Where the
source tests .NET TaskFactory-specific options/schedulers/APM overloads, those
scenarios are explicitly skipped. The applicable Task.run callable and token
semantics are tested rather than implying TaskFactory exists in FlpIt.
"""
from __future__ import annotations

import pytest

from flpit.task import CancellationTokenSource, OperationCanceledError, Task


def _unsupported(feature: str) -> None:
    pytest.skip(f"Upstream .NET test requires unsupported FlpIt API: {feature}")


def test_RunTaskFactoryTests() -> None:
    _unsupported("full TaskFactory configuration, StartNew overload matrix, continuation options, and scheduler selection")


def test_FlpIt_Task_run_basic_callable_and_coroutine_subset() -> None:
    """Local analogue for the subset that maps to FlpIt's Task.run API."""
    assert Task.run(lambda: None).result() is None
    assert Task.run(lambda: 10).result() == 10

    async def async_value() -> int:
        await Task.delay(0)
        return 11

    assert Task.run(async_value).result() == 11


def test_RunTaskFactoryTests_Cancellation_Negative() -> None:
    source = CancellationTokenSource()
    source.cancel()
    invoked = []
    try:
        task = Task.run(lambda: invoked.append(True), token=source.token)
        with pytest.raises(OperationCanceledError):
            task.result()
        assert task.cancelled()
        assert invoked == []
    finally:
        source.dispose()


def test_RunTaskFactoryExceptionTests() -> None:
    _unsupported("full TaskFactory argument/option validation and FromAsync exceptions")


def test_FlpIt_Task_run_rejects_invalid_callable() -> None:
    """Local analogue for callable validation at the Task.run API boundary."""
    with pytest.raises(TypeError):
        Task.run(None)
    with pytest.raises(TypeError):
        Task.run(object())


def test_RunTaskFactoryFromAsyncExceptionTests() -> None:
    _unsupported("APM FromAsync, IAsyncResult, and TaskFactory<T>.FromAsync overloads")
