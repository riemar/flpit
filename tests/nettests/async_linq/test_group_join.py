"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable GroupJoinTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/GroupJoinTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

IGrouping<TOuter, TInner> (overload without result selector) maps to Grouping(key=outer, items=matches);
the result selector receives the matches as a FlpList. The expected values come from FlpIt.group_join.
"""
import random

import pytest

from flpit import (
    AsyncFlpIt, InnerKeySelectorNoneError, InnerNoneError, OuterKeySelectorNoneError, ResultSelectorNoneError,
    SourceNoneError, flp,
)
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    assert_equal, async_test, consume, create_source, create_sources, fill_random_strings, to_pylist, track,
)


async def _identity(s, ct):
    return s


async def _concat(outer, inner, ct):
    return outer + "".join(inner)


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
    for keys, result in ((lambda s: s, lambda o, i: o + "".join(i)), (_identity, _concat)):
        with pytest.raises(InnerNoneError):
            empty.group_join(None, keys, keys, result)
        with pytest.raises(OuterKeySelectorNoneError):
            empty.group_join(empty, None, keys, result)
        with pytest.raises(InnerKeySelectorNoneError):
            empty.group_join(empty, keys, None, result)
        with pytest.raises(ResultSelectorNoneError):
            empty.group_join(empty, keys, keys, None)


def test_InvalidInputs_WithoutResultSelector_Throws():
    empty = AsyncFlpIt.empty()
    for keys in (lambda s: s, _identity):
        with pytest.raises(OuterKeySelectorNoneError):
            empty.group_join(empty, None, keys)
        with pytest.raises(InnerKeySelectorNoneError):
            empty.group_join(empty, keys, None)


def test_Empty_ProducesEmpty():
    empty = AsyncFlpIt.empty()

    async def first(s, e, ct):
        return s

    async def to_str(i, ct):
        return str(i)

    assert empty.group_join(create_source(1, 2, 3), lambda s: s, str, lambda s, e: s) is empty
    assert empty.group_join(create_source(1, 2, 3), _identity, to_str, first) is empty


def test_Empty_WithoutResultSelector_ProducesEmpty():
    empty = AsyncFlpIt.empty()

    async def to_str(i, ct):
        return str(i)

    assert empty.group_join(create_source(1, 2, 3), lambda s: s, str) is empty
    assert empty.group_join(create_source(1, 2, 3), _identity, to_str) is empty


@async_test
async def test_VariousValues_MatchesEnumerable_String():
    rand = random.Random(42)
    for length in (0, 1, 2, 1000):
        values = fill_random_strings(rand, length)
        expected = list(flp.it(values).group_join(values, _outer_key, _inner_key, lambda o, i: o + "".join(i)))
        for source in create_sources(*values):
            await assert_equal(
                expected, source.group_join(source, _outer_key, _inner_key, lambda o, i: o + "".join(i)))
            await assert_equal(expected, source.group_join(source, _outer_key_async, _inner_key_async, _concat))


@async_test
async def test_VariousValues_WithoutResultSelector_MatchesEnumerable():
    outer = [1, 2, 3]
    inner = [1, 2, 2, 3, 3, 3]
    expected = list(flp.it(outer).group_join(inner, lambda o: o, lambda i: i))

    async def identity(x, ct):
        return x

    for outer_source in create_sources(*outer):
        for inner_source in create_sources(*inner):
            for keys in (lambda x: x, identity):
                result = await to_pylist(outer_source.group_join(inner_source, keys, keys))
                assert len(result) == len(expected)
                for exp, act in zip(expected, result):
                    assert exp.key == act.key
                    assert list(exp) == list(act)


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)

    async def plain(x, ct):
        return x

    async def add(outer, inner, ct):
        return outer + sum(inner)

    def cancelling(cts, result):
        async def f(*args):
            assert args[-1] is cts.token
            await Task.yield_now()
            cts.cancel()
            return args[0] + sum(args[1]) if result else args[0]
        return f

    cts = CancellationTokenSource()

    def cancel_then_key(x):
        cts.cancel()
        return x

    with pytest.raises(OperationCanceledError):
        await consume(source.group_join(
            source, cancel_then_key, lambda x: x, lambda o, i: o + sum(i)).with_cancellation(cts.token))

    for position in range(3):
        cts = CancellationTokenSource()
        callbacks = [plain, plain, add]
        callbacks[position] = cancelling(cts, position == 2)
        with pytest.raises(OperationCanceledError):
            await consume(source.group_join(source, *callbacks).with_cancellation(cts.token))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    async def add(o, i, ct):
        return o + sum(i)

    for factory in (
            lambda o, i: o.group_join(i, lambda x: x, lambda x: x, lambda a, b: a + sum(b)),
            lambda o, i: o.group_join(i, _identity, _identity, add),
    ):
        outer = track(create_source(2, 4, 8, 16))
        inner = track(create_source(1, 2, 3, 4))
        await consume(factory(outer, inner))
        assert (outer.move_next_count, outer.current_count, outer.dispose_count) == (5, 4, 1)
        assert (inner.move_next_count, inner.current_count, inner.dispose_count) == (5, 4, 1)


@async_test
async def test_InterfaceCalls_WithoutResultSelector_ExpectedCounts():
    for keys in (lambda x: x, _identity):
        outer = track(create_source(2, 4, 8, 16))
        inner = track(create_source(1, 2, 3, 4))
        await consume(outer.group_join(inner, keys, keys))
        assert (outer.move_next_count, outer.current_count, outer.dispose_count) == (5, 4, 1)
        assert (inner.move_next_count, inner.current_count, inner.dispose_count) == (5, 4, 1)
