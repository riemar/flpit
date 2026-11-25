"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Pytest port of current dotnet/runtime OperationCanceledExceptionTests.

Upstream source (current .NET runtime; no Mono sources):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/OperationCanceledExceptionTests.cs
"""
from __future__ import annotations

import pytest

from flpit.task import CancellationTokenSource, OperationCanceledError


@pytest.mark.xfail(strict=True, reason="OperationCanceledError has no (message, innerException, token) constructor")
def test_BasicConstructors() -> None:
    ct1 = CancellationTokenSource().token
    ex1 = OperationCanceledError(token=ct1)  # OperationCanceledException(token): FlpIt's first argument is the message
    assert ex1.token == ct1

    ct2 = CancellationTokenSource().token
    ex2 = OperationCanceledError("message", ct2)
    assert ex2.token == ct2

    ct3 = CancellationTokenSource().token
    ex3 = OperationCanceledError("message", Exception("inner"), ct3)  # type: ignore[call-arg]
    assert ex3.token == ct3
