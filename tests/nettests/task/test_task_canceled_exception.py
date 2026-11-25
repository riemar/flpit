"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Pytest port of current dotnet/runtime TaskCanceledExceptionTests.

Upstream source (current .NET runtime; no Mono sources):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/Task/TaskCanceledExceptionTests.cs

``Message`` is ``str(exception)``; ``InnerException`` is ``inner_exception`` (also set as ``__cause__``).
"""
from __future__ import annotations

from flpit.task import CancellationTokenSource, TaskCanceledError


def test_TaskCanceledException_Ctor_StringExceptionToken() -> None:
    message = "my exception message"
    ioe = RuntimeError()  # InvalidOperationException
    cts = CancellationTokenSource()
    cts.cancel()

    tce = TaskCanceledError(message, ioe, token=cts.token)
    assert str(tce) == message
    assert tce.task is None
    assert tce.inner_exception is ioe
    assert tce.token == cts.token
