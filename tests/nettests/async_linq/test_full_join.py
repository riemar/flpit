"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable FullJoinTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/FullJoinTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

The tuple overloads (FullJoin(inner, outerKey, innerKey) -> (Outer, Inner)) map to JoinTuple(outer, inner).
ArgumentNullException("outer") is the None source (SourceNoneError).

Adapted:
    * The expected values come from the sync FlpIt.full_join (itself migrated against System.Linq).
    * C# string concatenation treats null as "" and default(int) is 0; the projections spell that out
      with `or ''` / `or 0` (Python has no default(T): unmatched sides are None).
    * The null-key tests use StringComparer.OrdinalIgnoreCase; comparers are not implemented, so the
      keys are lower-cased instead (the same matches, the original elements are kept).
"""
import random

import pytest

from flpit import (
    AsyncFlpIt, InnerKeySelectorNoneError, InnerNoneError, OuterKeySelectorNoneError, ResultSelectorNoneError,
    SourceNoneError, flp,
)
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    assert_equal, async_test, consume, create_source, create_sources, fill_random_strings, track,
)


async def _identity(s, ct):
    return s


async def _first(a, b, ct):
    return a


async def _concat(a, b, ct):
    return a + b


_KEY_OVERLOADS = (lambda s: s, _identity)


def _outer_key(s):
    return s[0] if len(s) > 0 else " "


def _inner_key(s):
    return s[1] if len(s) > 1 else " "


async def _outer_key_async(s, ct):
    return _outer_key(s)


async def _inner_key_async(s, ct):
    return _inner_key(s)


def test_InvalidInputs_Throws():
    empty = AsyncFlpIt.empty()
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    for keys, result in ((lambda s: s, lambda a, b: (a or 0) + (b or 0)), (_identity, _concat)):
        with pytest.raises(InnerNoneError):
            empty.full_join(None, keys, keys, result)
        with pytest.raises(OuterKeySelectorNoneError):
            empty.full_join(empty, None, keys, result)
        with pytest.raises(InnerKeySelectorNoneError):
            empty.full_join(empty, keys, None, result)
        with pytest.raises(ResultSelectorNoneError):
            empty.full_join(empty, keys, keys, None)


def test_TupleFullJoin_InvalidInputs_Throws():
    empty = AsyncFlpIt.empty()
    for keys in _KEY_OVERLOADS:
        with pytest.raises(InnerNoneError):
            empty.full_join(None, keys, keys)
        with pytest.raises(OuterKeySelectorNoneError):
            empty.full_join(empty, None, keys)
        with pytest.raises(InnerKeySelectorNoneError):
            empty.full_join(empty, keys, None)


def test_Empty_ProducesExpectedBehavior():
    empty = AsyncFlpIt.empty()
    non_empty = create_source("1", "2", "3")
    for keys in _KEY_OVERLOADS:
        for result in (lambda a, b: a, _first):
            assert empty.full_join(empty, keys, keys, result) is empty
            assert non_empty.full_join(empty, keys, keys, result) is not empty
            assert empty.full_join(non_empty, keys, keys, result) is not empty


def test_TupleFullJoin_Empty_ProducesExpectedBehavior():
    empty = AsyncFlpIt.empty()
    non_empty = create_source("1", "2", "3")
    for keys in _KEY_OVERLOADS:
        assert empty.full_join(empty, keys, keys) is empty
        assert non_empty.full_join(empty, keys, keys) is not empty
        assert empty.full_join(non_empty, keys, keys) is not empty


def _null_key(s):
    return None if s[0] == "#" else s.lower()


async def _null_key_async(s, ct):
    return _null_key(s)


@async_test
async def test_NullKeysAreUnmatchedButPreserved():
    expected = ["#o1:<null>", "a:A", "#o2:<null>", "<null>:#i1", "<null>:#i2", "<null>:b"]

    def result(outer, inner):
        return f"{'<null>' if outer is None else outer}:{'<null>' if inner is None else inner}"

    async def result_async(outer, inner, ct):
        return result(outer, inner)

    assert list(await create_source("#o1", "a", "#o2").full_join(
        create_source("#i1", "A", "#i2", "b"), _null_key, _null_key, result).to_list()) == expected
    assert list(await create_source("#o1", "a", "#o2").full_join(
        create_source("#i1", "A", "#i2", "b"), _null_key_async, _null_key_async, result_async).to_list()) == expected


@async_test
async def test_TupleOverloads_PreserveNullKeyRows():
    expected = [("#o1", None), ("a", "A"), ("#o2", None), (None, "#i1"), (None, "#i2"), (None, "b")]
    for key in (_null_key, _null_key_async):
        assert list(await create_source("#o1", "a", "#o2").full_join(
            create_source("#i1", "A", "#i2", "b"), key, key).to_list()) == expected


@async_test
async def test_VariousValues_MatchesEnumerable_String():
    rand = random.Random(42)
    for length in (0, 1, 2, 1000):
        values = fill_random_strings(rand, length)
        expected = list(flp.it(values).full_join(values, _outer_key, _inner_key, lambda o, i: (o or "") + (i or "")))
        for source in create_sources(*values):
            await assert_equal(expected, source.full_join(source, _outer_key, _inner_key, lambda o, i: (o or "") + (i or "")))

            async def concat(o, i, ct):
                return (o or "") + (i or "")

            await assert_equal(expected, source.full_join(source, _outer_key_async, _inner_key_async, concat))


@async_test
async def test_TupleFullJoin_VariousValues_MatchesEnumerable_String():
    rand = random.Random(42)
    for length in (0, 1, 2, 1000):
        values = fill_random_strings(rand, length)
        expected = [(t.outer or '') + (t.inner or '') for t in flp.it(values).full_join(values, _outer_key, _inner_key)]
        for source in create_sources(*values):
            await assert_equal(expected, source.full_join(source, _outer_key, _inner_key).select(lambda t: (t.outer or '') + (t.inner or '')))
            await assert_equal(
                expected, source.full_join(source, _outer_key_async, _inner_key_async).select(lambda t: (t.outer or '') + (t.inner or '')))


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)

    async def plain(x, ct):
        return x

    async def add(a, b, ct):
        return (a or 0) + (b or 0)

    def cancelling(cts):
        async def f(*args):
            assert args[-1] is cts.token
            await Task.yield_now()
            cts.cancel()
            return args[0] if len(args) == 2 else (args[0] or 0) + (args[1] or 0)
        return f

    cts = CancellationTokenSource()

    def cancel_then_key(x):
        cts.cancel()
        return x

    with pytest.raises(OperationCanceledError):
        await consume(source.full_join(source, cancel_then_key, lambda x: x, lambda a, b: (a or 0) + (b or 0)).with_cancellation(cts.token))

    for position in range(3):
        cts = CancellationTokenSource()
        callbacks = [plain, plain, add]
        callbacks[position] = cancelling(cts)
        with pytest.raises(OperationCanceledError):
            await consume(source.full_join(source, *callbacks).with_cancellation(cts.token))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    async def add(a, b, ct):
        return (a or 0) + (b or 0)

    for factory in (
            lambda o, i: o.full_join(i, lambda x: x, lambda x: x, lambda a, b: (a or 0) + (b or 0)),
            lambda o, i: o.full_join(i, _identity, _identity, add),
    ):
        outer = track(create_source(2, 4, 8, 16))
        inner = track(create_source(1, 2, 3, 4))
        await consume(factory(outer, inner))
        assert (outer.move_next_count, outer.current_count, outer.dispose_count) == (5, 4, 1)
        assert (inner.move_next_count, inner.current_count, inner.dispose_count) == (5, 4, 1)


@async_test
async def test_TupleFullJoin_InterfaceCalls_ExpectedCounts():
    for keys in _KEY_OVERLOADS:
        outer = track(create_source(2, 4, 8, 16))
        inner = track(create_source(1, 2, 3, 4))
        await consume(outer.full_join(inner, keys, keys))
        assert (outer.move_next_count, outer.current_count, outer.dispose_count) == (5, 4, 1)
        assert (inner.move_next_count, inner.current_count, inner.dispose_count) == (5, 4, 1)
