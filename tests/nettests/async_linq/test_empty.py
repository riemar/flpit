"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable EmptyTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/EmptyTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * Empty<int>() vs Empty<long>(): Python has no runtime generics, so there is one shared empty sequence.
    * ValueTask.IsCompleted: the awaitable returned by __anext__ / aclose is driven by hand (send(None)); it
      finishing without suspending is the synchronous completion. Current has no Python equivalent.
"""
import pytest

from flpit import AsyncFlpIt
from nettests.async_linq.async_helpers import canceled_token


def test_Empty_Idempotent():
    ae = AsyncFlpIt.empty()
    assert ae is not None
    assert ae is AsyncFlpIt.empty()
    e = ae.get_async_enumerator(None)
    assert e is ae.get_async_enumerator(None)
    assert e is ae.get_async_enumerator(canceled_token())


def test_Empty_ContainsZeroElements():
    e = AsyncFlpIt.empty().get_async_enumerator(None)
    for _ in range(2):
        move_next = e.__anext__()
        with pytest.raises(StopAsyncIteration):
            move_next.send(None)  # completes synchronously with "no element"
    dispose = e.aclose()
    with pytest.raises(StopIteration):
        dispose.send(None)  # completes synchronously
