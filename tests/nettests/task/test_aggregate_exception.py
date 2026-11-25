"""
Copyright (c) .NET Foundation and Contributors
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Pytest port of current dotnet/runtime AggregateExceptionTests.

Upstream source (current .NET runtime; no Mono sources):
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Runtime/tests/System.Threading.Tasks.Tests/AggregateExceptionTests.cs

FlpIt's ``AggregateError(exceptions, message)`` is .NET's ``AggregateException(message, innerExceptions)``;
``exceptions`` is ``InnerExceptions``.
"""
from __future__ import annotations

import pytest

from flpit.core.linq import ArgumentError, ArgumentNullError
from flpit.task import AggregateError


def _unsupported(feature: str) -> None:
    pytest.skip(f"Upstream .NET test requires unsupported FlpIt API: {feature}")


@pytest.mark.xfail(strict=True, reason="AggregateError requires at least one exception; .NET allows none")
def test_ConstructorBasic() -> None:
    ex = AggregateError([])
    assert len(ex.exceptions) == 0
    assert str(ex) is not None, (
        "RunAggregateException_Constructor:  FAILED. Message property is null when the default constructor is used, "
        "expected a default message")

    ex = AggregateError([], "message")
    assert len(ex.exceptions) == 0
    assert str(ex) is not None, (
        "RunAggregateException_Constructor:  FAILED. Message property is  null when the default constructor(string) "
        "is used")

    ex = AggregateError([Exception()], "message")
    assert len(ex.exceptions) == 1
    assert str(ex) is not None, (
        "RunAggregateException_Constructor:  FAILED. Message property is  null when the default "
        "constructor(string, Exception) is used")


def test_ConstructorInvalidArguments() -> None:
    # The original starts with `ex = new AggregateException()`, which is only reassigned below; FlpIt has no
    # empty AggregateError (see test_ConstructorBasic). AggregateException("message", (Exception)null) and
    # ("message", (IEnumerable<Exception>)null) are both a None exceptions argument here.
    with pytest.raises(ArgumentNullError):
        AggregateError(None, "message")  # type: ignore[arg-type]

    with pytest.raises(ArgumentError):
        AggregateError([Exception(), None], "message")  # type: ignore[list-item]


def test_BaseExceptions() -> None:
    _unsupported("AggregateException.GetBaseException")


def test_Handle() -> None:
    _unsupported("AggregateException.Handle")


def test_HandleInvalidCases() -> None:
    _unsupported("AggregateException.Handle")


def test_Flatten() -> None:
    # Also checks .NET's message format, "message (A) (B) (C)": FlpIt's message does not list the inner ones.
    _unsupported("AggregateException.Flatten")
