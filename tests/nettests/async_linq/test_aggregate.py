"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable AggregateAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/AggregateAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * The string theory seeds with (string)null; C# concatenation treats null as "", Python's None + str
      raises, so the seed is "" (both runtimes then build the same strings).
    * Callbacks_InvokedOnOriginalContext: SynchronizationContext has no Python equivalent (skipped).
"""
import pytest

from flpit import AsyncFlpIt, FuncNoneError, InvalidOperationError, ResultSelectorNoneError, SourceNoneError, flp
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    TRUE_FALSE_BOOLS, async_test, create_source, create_sources, not_portable, track,
)


async def _add(x, y, ct):
    return x + y


async def _double(x, ct):
    return x * 2


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    empty = AsyncFlpIt.empty()
    with pytest.raises(FuncNoneError):
        empty.aggregate(None)
    with pytest.raises(FuncNoneError):
        empty.aggregate(42, None)
    with pytest.raises(FuncNoneError):
        empty.aggregate(42, None, lambda x: x * 2)
    with pytest.raises(FuncNoneError):
        empty.aggregate(42, None, _double)
    with pytest.raises(ResultSelectorNoneError):
        empty.aggregate(42, lambda x, y: x + y, None)
    with pytest.raises(ResultSelectorNoneError):
        empty.aggregate(42, _add, None)


@pytest.mark.parametrize("values", [[], [1], [2, 4, 8], [-1, 2, 5, 6, 7, 8]])
@async_test
async def test_VariousValues_MatchesEnumerable_Int32(values):
    def func(x, y):
        return x + (2 * y)

    async def func_async(x, y, ct):
        await Task.yield_now()
        return func(x, y)

    async def result_async(x, ct):
        await Task.yield_now()
        return x * 2

    expected = flp.it(values)
    for source in create_sources(*values):
        if values:
            assert await source.aggregate(func) == expected.aggregate(func)
            assert await source.aggregate(func_async) == expected.aggregate(func)
        else:
            with pytest.raises(InvalidOperationError):
                expected.aggregate(func)
            with pytest.raises(InvalidOperationError):
                await source.aggregate(func)
            with pytest.raises(InvalidOperationError):
                await source.aggregate(func_async)
        assert await source.aggregate(42, func) == expected.aggregate(42, func)
        assert await source.aggregate(42, func_async) == expected.aggregate(42, func)
        assert await source.aggregate(42, func, lambda x: x * 2) == expected.aggregate(42, func, lambda x: x * 2)
        assert await source.aggregate(42, func_async, result_async) == expected.aggregate(42, func, lambda x: x * 2)


@pytest.mark.parametrize("values", [[], ["1"], ["2", "4", "8"], ["-1", "2", "5", "6", "7", "8"]])
@async_test
async def test_VariousValues_MatchesEnumerable_String(values):
    def func(x, y):
        return x + y + y

    async def func_async(x, y, ct):
        await Task.yield_now()
        return func(x, y)

    async def result_async(x, ct):
        await Task.yield_now()
        return x + x

    expected = flp.it(values)
    for source in create_sources(*values):
        if values:
            assert await source.aggregate(func) == expected.aggregate(func)
            assert await source.aggregate(func_async) == expected.aggregate(func)
        else:
            with pytest.raises(InvalidOperationError):
                expected.aggregate(func)
            with pytest.raises(InvalidOperationError):
                await source.aggregate(func)
        assert await source.aggregate("", func) == expected.aggregate("", func)
        assert await source.aggregate("", func_async) == expected.aggregate("", func)
        assert await source.aggregate("", func, lambda x: x + x) == expected.aggregate("", func, lambda x: x + x)
        assert await source.aggregate("", func_async, result_async) == expected.aggregate("", func, lambda x: x + x)


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)

    def cancelling(cts):
        def func(x, y):
            cts.cancel()
            return x + y
        return func

    def cancelling_async(cts):
        async def func(x, y, ct):
            assert ct is cts.token
            await Task.yield_now()
            cts.cancel()
            return x + y
        return func

    async def identity(x, ct):
        return x

    for call in (
            lambda cts: source.aggregate(cancelling(cts), token=cts.token),
            lambda cts: source.aggregate(cancelling_async(cts), token=cts.token),
            lambda cts: source.aggregate(42, cancelling(cts), token=cts.token),
            lambda cts: source.aggregate(42, cancelling_async(cts), token=cts.token),
            lambda cts: source.aggregate(42, cancelling(cts), lambda x: x, token=cts.token),
            lambda cts: source.aggregate(42, cancelling_async(cts), identity, token=cts.token),
    ):
        with pytest.raises(OperationCanceledError):
            await call(CancellationTokenSource())


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    for use_async in TRUE_FALSE_BOOLS:
        func_count = result_count = 0

        def func(x, y):
            nonlocal func_count
            func_count += 1
            return x + y

        def throwing_func(x, y):
            nonlocal func_count
            func_count += 1
            raise Exception()

        def result(x):
            nonlocal result_count
            result_count += 1
            return x * 2

        def throwing_result(x):
            nonlocal result_count
            result_count += 1
            raise Exception()

        def two(f):
            if not use_async:
                return f

            async def g(x, y, ct):
                return f(x, y)
            return g

        def one(f):
            if not use_async:
                return f

            async def g(x, ct):
                return f(x)
            return g

        def check(counts, funcs, results=None):
            assert (source.move_next_count, source.current_count, source.dispose_count) == counts
            assert func_count == funcs
            if results is not None:
                assert result_count == results

        func_count = 0
        source = track(create_source(2, 4, 8, 16))
        assert await source.aggregate(two(func)) == 30
        check((5, 4, 1), 3)

        func_count = 0
        source = track(create_source(2, 4, 8, 16))
        with pytest.raises(Exception):
            await source.aggregate(two(throwing_func))
        check((2, 2, 1), 1)

        func_count = 0
        source = track(create_source(2, 4, 8, 16))
        assert await source.aggregate(42, two(func)) == 72
        check((5, 4, 1), 4)

        func_count = 0
        source = track(create_source(2, 4, 8, 16))
        with pytest.raises(Exception):
            await source.aggregate(42, two(throwing_func))
        check((1, 1, 1), 1)

        func_count = result_count = 0
        source = track(create_source(2, 4, 8, 16))
        assert await source.aggregate(42, two(func), one(result)) == 144
        check((5, 4, 1), 4, 1)

        func_count = result_count = 0
        source = track(create_source(2, 4, 8, 16))
        with pytest.raises(Exception):
            await source.aggregate(42, two(throwing_func), one(result))
        check((1, 1, 1), 1, 0)

        func_count = result_count = 0
        source = track(create_source(2, 4, 8, 16))
        with pytest.raises(Exception):
            await source.aggregate(42, two(func), one(throwing_result))
        check((5, 4, 1), 4, 1)


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")
