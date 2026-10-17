"""
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Behavioral tests for FlpIt's CancellationTokenSource implementation.

Test names and scenarios adapted from:
- Mono CancellationTokenSourceTest.cs:
  https://github.com/mono/mono/blob/bf5947a0fd2b523c30833605ee69b2b041aa43f4/mcs/class/corlib/Test/System.Threading/CancellationTokenSourceTest.cs

  Upstream test-file attribution: Copyright (c) 2011 Xamarin, Inc.
  The upstream file is MIT-licensed; see its license notice.

Behavioral references consulted (implementation code not copied):
- .NET CancellationTokenSource:
  https://github.com/dotnet/runtime/blob/main/src/libraries/System.Private.CoreLib/src/System/Threading/CancellationTokenSource.cs
- .NET CancellationToken:
  https://github.com/dotnet/runtime/blob/main/src/libraries/System.Private.CoreLib/src/System/Threading/CancellationToken.cs

These tests are adapted to FlpIt's Python API and semantics, not
a line-for-line port of the upstream tests.
"""

import pytest

from flpit.task import AggregateError, CancellationTokenSource


def test_Token():
    source = CancellationTokenSource()
    try:
        token = source.token

        assert token.can_be_cancelled
        assert not token.is_cancellation_requested
    finally:
        source.dispose()


def test_Cancel_NoRegistration():
    source = CancellationTokenSource()
    try:
        source.cancel()
        assert source.is_cancellation_requested
    finally:
        source.dispose()


def test_Cancel():
    source = CancellationTokenSource()
    try:
        calls: list[int] = []
        source.token.register(lambda: calls.append(1))

        source.cancel()
        assert calls == [1]

        # Registering after cancellation invokes the callback immediately.
        source.token.register(lambda: calls.append(12))
        assert calls == [1, 12]

        # A second cancellation must not invoke callbacks again.
        source.cancel()
        assert calls == [1, 12]
    finally:
        source.dispose()


def test_Cancel_Order():
    source = CancellationTokenSource()
    try:
        calls: list[int] = []
        source.token.register(lambda: calls.append(2))
        source.token.register(lambda: calls.append(1))
        source.token.register(lambda: calls.append(0))

        source.cancel()

        # .NET-style cancellation callback order is last-in, first-out.
        assert calls == [0, 1, 2]
    finally:
        source.dispose()


def test_CancelWithDispose():
    source = CancellationTokenSource()
    token = source.token
    calls: list[str] = []

    def dispose_source():
        source.dispose()

    # First registered, so this callback runs last under LIFO ordering.
    token.register(dispose_source)
    token.register(lambda: calls.append("called"))

    source.cancel()

    assert calls == ["called"]
    # Disposal is idempotent, including after disposal during cancellation.
    source.dispose()


def test_Cancel_SingleException():
    source = CancellationTokenSource()
    try:
        source.token.register(lambda: (_ for _ in ()).throw(ValueError("boom")))

        with pytest.raises(AggregateError) as caught:
            source.cancel()

        assert len(caught.value.exceptions) == 1
        assert isinstance(caught.value.exceptions[0], ValueError)
        assert str(caught.value.exceptions[0]) == "boom"

        # The source is cancelled even though the callback failed.
        assert source.is_cancellation_requested
        assert source.cancel() is False
    finally:
        source.dispose()


def test_Cancel_MultipleExceptions():
    source = CancellationTokenSource()
    try:
        def fail(message: str) -> None:
            raise ValueError(message)

        source.token.register(lambda: fail("1"))
        source.token.register(lambda: fail("2"))
        source.token.register(lambda: fail("3"))

        with pytest.raises(AggregateError) as caught:
            source.cancel()

        assert len(caught.value.exceptions) == 3
        assert {str(exc) for exc in caught.value.exceptions} == {"1", "2", "3"}

        # A callback registered after cancellation runs immediately; its own
        # exception is propagated directly rather than aggregated by cancel().
        with pytest.raises(ValueError, match="late registration"):
            source.token.register(lambda: fail("late registration"))

        assert source.cancel() is False
    finally:
        source.dispose()


def test_Cancel_ExceptionOrder():
    source = CancellationTokenSource()
    try:
        def fail(message: str) -> None:
            raise ValueError(message)

        source.token.register(lambda: fail("1"))
        source.token.register(lambda: fail("2"))
        source.token.register(lambda: fail("3"))

        with pytest.raises(AggregateError) as caught:
            source.cancel()

        assert [str(exc) for exc in caught.value.exceptions] == ["3", "2", "1"]
    finally:
        source.dispose()


def test_Cancel_MultipleException_Recursive():
    source = CancellationTokenSource()
    try:
        token = source.token
        token.register(lambda: source.cancel())

        def fail(error: Exception) -> None:
            raise error

        token.register(lambda: fail(RuntimeError("application failure")))
        token.register(lambda: fail(NotImplementedError("unsupported")))

        with pytest.raises(AggregateError) as caught:
            source.cancel()

        assert len(caught.value.exceptions) == 2
        assert isinstance(caught.value.exceptions[0], NotImplementedError)
        assert isinstance(caught.value.exceptions[1], RuntimeError)
        assert source.is_cancellation_requested
    finally:
        source.dispose()
