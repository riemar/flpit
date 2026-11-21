"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

ConcurrentDictionary tests, ported from
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Collections.Concurrent/tests/ConcurrentDictionary/ConcurrentDictionaryTests.cs
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Collections.Concurrent/tests/ConcurrentDictionary/ConcurrentDictionary.NonGeneric.Tests.cs

Mapping: ``new ConcurrentDictionary<K, V>(cLevel, capacity)`` is
``ConcurrentDictionary[K, V](concurrency_level=cLevel, capacity=capacity)``; ``foreach (var pair in dict)``
is ``dict.items()``; ``KeyValuePair`` a ``(key, value)`` tuple; ``IDictionary<K, V>.Add`` is
``add``; ``ICollection<KeyValuePair>.Remove`` is ``try_remove_item``; the ``GetOrAdd`` /
``AddOrUpdate`` overloads are called positionally, as in C#; ``Task.Run`` + ``ManualResetEvent``
is ``Task.run`` + ``Task.wait_all``.

Not portable, skipped: the non-generic ``IDictionary`` / ``ICollection`` tests (Python has one,
untyped, mapping protocol: no ``object``-typed indexer that checks key/value types, no
``DictionaryEntry``, ``SyncRoot`` or ``IsSynchronized``), ``TestCapacity`` (reads the bucket array
through reflection), the alternate-lookup tests (``ReadOnlySpan<char>`` keys) and the
``IEquatable<T>``-vs-``Equals(object)`` probe of ``TestNullComparer`` (Python has only ``__eq__``).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import pytest

from flpit.concurrent import ConcurrentDictionary
from flpit.core.comparers import EqualityComparer
from flpit.core.linq import ArgumentError, ArgumentNullError, ArgumentOutOfRangeError, KeyNotFoundError
from flpit.task import CancellationTokenSource, Task, TaskCreationOptions
from flpit.threading import ThreadLocal

from nettests.common.collection_helpers import not_portable

ORDINAL_IGNORE_CASE = EqualityComparer.create(lambda x, y: x.casefold() == y.casefold(), lambda s: hash(s.casefold()))

_NON_GENERIC = "the non-generic IDictionary / ICollection interfaces (typed object indexer, DictionaryEntry, SyncRoot)"
_ALTERNATE_LOOKUP = "alternate lookups with ReadOnlySpan<char> keys"


def _run_all(*actions: Any) -> None:
    """Upstream ``Task.Run`` per thread, then ``mre.WaitOne()`` once the last one is done."""
    Task.wait_all([Task.run(action) for action in actions])


class TestConcurrentDictionaryTests:
    def test_TestBasicScenarios(self) -> None:
        cd = ConcurrentDictionary[int, int]()

        def first() -> None:
            ret = cd.try_add(1, 11)
            if not ret:
                ret = cd.try_update(1, 11, 111)
                assert ret

            ret = cd.try_add(2, 22)
            if not ret:
                ret = cd.try_update(2, 22, 222)
                assert ret

        def second() -> None:
            ret = cd.try_add(2, 222)
            if not ret:
                ret = cd.try_update(2, 222, 22)
                assert ret

            ret = cd.try_add(1, 111)
            if not ret:
                ret = cd.try_update(1, 111, 11)
                assert ret

        _run_all(first, second)

    def test_TestAddNullValue_ConcurrentDictionaryOfString_null(self) -> None:
        # using ConcurrentDictionary<TKey, TValue> class
        dict1 = ConcurrentDictionary[str, str | None]()
        dict1["key"] = None

    def test_TestAddNullValue_IDictionaryOfString_null(self) -> None:
        # using IDictionary<TKey, TValue> interface
        dict2 = ConcurrentDictionary[str, str | None]()
        dict2["key"] = None
        dict2.add("key2", None)

    def test_TestAddNullValue_IDictionary_ReferenceType_null(self) -> None:
        not_portable(_NON_GENERIC)

    def test_TestAddNullValue_IDictionary_ValueType_null_indexer(self) -> None:
        not_portable(_NON_GENERIC)

    def test_TestAddNullValue_IDictionary_ValueType_null_add(self) -> None:
        not_portable(_NON_GENERIC)

    def test_TestAddValueOfDifferentType(self) -> None:
        not_portable(_NON_GENERIC)

    @pytest.mark.parametrize(
        ("c_level", "init_size", "threads", "adds_per_thread"),
        [(1, 1, 1, 10000), (5, 1, 1, 10000), (1, 1, 2, 5000), (1, 1, 5, 2000), (4, 0, 4, 2000),
         (16, 31, 4, 2000), (64, 5, 5, 5000), (5, 5, 5, 2500)],
    )
    def test_TestAdd(self, c_level: int, init_size: int, threads: int, adds_per_thread: int) -> None:
        dict_concurrent = ConcurrentDictionary[int, int](concurrency_level=c_level, capacity=1)
        d = dict_concurrent

        def add(ii: int) -> None:
            for j in range(adds_per_thread):
                d.add(j + ii * adds_per_thread, -(j + ii * adds_per_thread))

        _run_all(*(lambda ii=i: add(ii) for i in range(threads)))

        for key, value in d.items():
            assert key == -value

        got_keys = sorted(key for key, _ in d.items())
        expect_keys = list(range(threads * adds_per_thread))
        assert len(expect_keys) == len(got_keys)
        for i in range(len(expect_keys)):
            assert expect_keys[i] == got_keys[i], (
                "The set of keys in the dictionary is are not the same as the expected\n"
                f"TestAdd1(cLevel={c_level}, initSize={init_size}, threads={threads}, addsPerThread={adds_per_thread})"
            )

        # Finally, let's verify that the count is reported correctly.
        expected_count = threads * adds_per_thread
        assert expected_count == len(d)
        assert expected_count == len(dict_concurrent.to_array())

    @pytest.mark.parametrize(
        ("c_level", "threads", "updates_per_thread"),
        [(1, 1, 10000), (5, 1, 10000), (1, 2, 5000), (1, 5, 2001), (4, 4, 2001), (15, 5, 2001), (64, 5, 5000),
         (5, 5, 25000)],
    )
    def test_TestUpdate(self, c_level: int, threads: int, updates_per_thread: int) -> None:
        d = ConcurrentDictionary[int, int](concurrency_level=c_level, capacity=1)

        for i in range(1, updates_per_thread + 1):
            d[i] = i

        def update(ii: int) -> None:
            for j in range(1, updates_per_thread + 1):
                d[j] = (ii + 2) * j

        _run_all(*(lambda ii=i: update(ii) for i in range(threads)))

        for key, value in d.items():
            div = value // key
            rem = value % key

            assert 0 == rem
            assert 1 < div <= threads + 1, (
                f"* Invalid value={div}! TestUpdate1(cLevel={c_level}, threads={threads}, updatesPerThread={updates_per_thread})"
            )

        got_keys = sorted(key for key, _ in d.items())
        expect_keys = list(range(1, updates_per_thread + 1))
        assert len(expect_keys) == len(got_keys)
        assert expect_keys == got_keys

    @pytest.mark.parametrize(
        ("c_level", "threads", "reads_per_thread"),
        [(1, 1, 10000), (5, 1, 10000), (1, 2, 5000), (1, 5, 2001), (4, 4, 2001), (15, 5, 2001), (64, 5, 5000),
         (5, 5, 25000)],
    )
    def test_TestRead1(self, c_level: int, threads: int, reads_per_thread: int) -> None:
        d = ConcurrentDictionary[int, int](concurrency_level=c_level, capacity=1)

        for i in range(0, reads_per_thread, 2):
            d[i] = i

        def read() -> None:
            for j in range(reads_per_thread):
                ok, val = d.try_get_value(j)
                if ok:
                    assert 0 == j % 2
                    assert j == val
                else:
                    assert 1 == j % 2

        _run_all(*(read for _ in range(threads)))

    @pytest.mark.parametrize(
        ("c_level", "threads", "removes_per_thread"),
        [(1, 1, 10000), (5, 1, 1000), (1, 5, 2001), (4, 4, 2001), (15, 5, 2001), (64, 5, 5000)],
    )
    def test_TestRemove1(self, c_level: int, threads: int, removes_per_thread: int) -> None:
        d = ConcurrentDictionary[int, int](concurrency_level=c_level, capacity=1)
        method_parameters = f"* TestRemove1(cLevel={c_level}, threads={threads}, removesPerThread={removes_per_thread})"
        n = 2 * threads * removes_per_thread

        for i in range(n):
            d[i] = -i

        # The dictionary contains keys [0..N), each key mapped to a value equal to the key.
        # Threads will cooperatively remove all even keys

        def remove(ii: int) -> None:
            for j in range(removes_per_thread):
                key = 2 * (ii + j * threads)
                removed, value = d.try_remove(key)
                assert removed, "Failed to remove an element! " + method_parameters
                assert -key == value

        _run_all(*(lambda ii=i: remove(ii) for i in range(threads)))

        for key, value in d.items():
            assert key == -value

        got_keys = sorted(key for key, _ in d.items())
        expect_keys = [2 * i + 1 for i in range(threads * removes_per_thread)]
        assert len(expect_keys) == len(got_keys)
        assert expect_keys == got_keys, "  > Unexpected key value! " + method_parameters

        # Finally, let's verify that the count is reported correctly.
        assert len(expect_keys) == len(d)
        assert len(expect_keys) == len(d.to_array())

    @pytest.mark.parametrize("removes_per_thread", [1, 10, 5000])
    def test_TestRemove2(self, removes_per_thread: int) -> None:
        d = ConcurrentDictionary[int, int]()

        for i in range(removes_per_thread):
            d[i] = -i

        # The dictionary contains keys [0..N), each key mapped to a value equal to the key.
        # Threads will cooperatively remove all even keys.
        size = 2
        seen = [[False] * removes_per_thread for _ in range(size)]

        def remove(thread: int) -> None:
            for key in range(removes_per_thread):
                removed, value = d.try_remove(key)
                if removed:
                    seen[thread][key] = True
                    assert -key == value

        _run_all(*(lambda t=t: remove(t) for t in range(size)))

        assert 0 == len(d)

        for i in range(removes_per_thread):
            assert seen[0][i] != seen[1][i], (
                f"> FAILED. Two threads appear to have removed the same element. TestRemove2(removesPerThread={removes_per_thread})"
            )

    def test_TestRemove3(self) -> None:
        d = ConcurrentDictionary[int, int]()

        d[99] = -99

        # Make sure we cannot "remove" a key/value pair which is not in the dictionary
        for i in range(200):
            if i != 99:
                assert not d.try_remove_item((i, -99)), "Should not remove not existing a key/value pair - new KeyValuePair<int, int>(i, -99)"
                assert not d.try_remove_item((99, -i)), "Should not remove not existing a key/value pair - new KeyValuePair<int, int>(99, -i)"

        # Can we remove a key/value pair successfully?
        assert d.try_remove_item((99, -99)), "Failed to remove existing key/value pair"

        # Make sure the key/value pair is gone
        assert not d.try_remove_item((99, -99)), "Should not remove the key/value pair which has been removed"

        # And that the dictionary is empty. We will check the count in a few different ways:
        assert 0 == len(d)
        assert 0 == len(d.to_array())

    def test_TryRemove_KeyValuePair_ArgumentValidation(self) -> None:
        with pytest.raises(ArgumentNullError, match="'item'"):
            ConcurrentDictionary[str, int]().try_remove_item((None, 42))  # type: ignore[arg-type]
        ConcurrentDictionary[int, int]().try_remove_item((0, 0))  # no error when using default value type
        ConcurrentDictionary[int | None, int]().try_remove_item((0, 0))  # or nullable

    def test_TryRemove_KeyValuePair_RemovesSuccessfullyAsAppropriate(self) -> None:
        d = ConcurrentDictionary[str, int]()

        for _ in range(2):
            assert not d.try_remove_item(("key", 42))
            assert 0 == len(d)
            assert d.try_add("key", 42)
            assert 1 == len(d)
            assert d.try_remove_item(("key", 42))
            assert 0 == len(d)

        assert d.try_add("key", 42)
        assert not d.try_remove_item(("key", 43))  # value doesn't match

    def test_TryRemove_KeyValuePair_MatchesKeyWithDefaultComparer(self) -> None:
        d = ConcurrentDictionary[str, str](comparer=ORDINAL_IGNORE_CASE)
        d.try_add("key", "value")

        assert not d.try_remove_item(("key", "VALUE"))
        assert d.try_remove_item(("KEY", "value"))

    def test_TestGetOrAdd(self) -> None:
        self._test_get_or_add_or_update(1, 1, 1, 10000, True)
        self._test_get_or_add_or_update(5, 1, 1, 10000, True)
        self._test_get_or_add_or_update(1, 1, 2, 5000, True)
        self._test_get_or_add_or_update(1, 1, 5, 2000, True)
        self._test_get_or_add_or_update(4, 0, 4, 2000, True)
        self._test_get_or_add_or_update(16, 31, 4, 2000, True)
        self._test_get_or_add_or_update(64, 5, 5, 5000, True)
        self._test_get_or_add_or_update(5, 5, 5, 25000, True)

    def test_TestAddOrUpdate(self) -> None:
        self._test_get_or_add_or_update(1, 1, 1, 10000, False)
        self._test_get_or_add_or_update(5, 1, 1, 10000, False)
        self._test_get_or_add_or_update(1, 1, 2, 5000, False)
        self._test_get_or_add_or_update(1, 1, 5, 2000, False)
        self._test_get_or_add_or_update(4, 0, 4, 2000, False)
        self._test_get_or_add_or_update(16, 31, 4, 2000, False)
        self._test_get_or_add_or_update(64, 5, 5, 5000, False)
        self._test_get_or_add_or_update(5, 5, 5, 25000, False)

    @staticmethod
    def _test_get_or_add_or_update(c_level: int, init_size: int, threads: int, adds_per_thread: int, is_add: bool) -> None:
        d = ConcurrentDictionary[int, int](concurrency_level=c_level, capacity=1)

        def work() -> None:
            for j in range(adds_per_thread):
                if is_add:
                    # call one of the overloads of GetOrAdd
                    match j % 3:
                        case 0:
                            d.get_or_add(j, -j)
                        case 1:
                            def factory1(x: int, j: int = j) -> int:
                                assert j == x
                                return -x

                            d.get_or_add(j, factory1)
                        case 2:
                            def factory2(x: int, m: int, j: int = j) -> int:
                                assert j == x
                                assert -1 == m
                                return x * m

                            d.get_or_add(j, factory2, -1)
                else:
                    match j % 3:
                        case 0:
                            def update0(k: int, v: int, j: int = j) -> int:
                                assert j == k
                                assert -j == v
                                return v

                            d.add_or_update(j, -j, update0)
                        case 1:
                            def add1(k: int, j: int = j) -> int:
                                assert j == k
                                return -k

                            def update1(k: int, v: int, j: int = j) -> int:
                                assert j == k
                                assert -j == v
                                return -k

                            d.add_or_update(j, add1, update1)
                        case 2:
                            def add2(k: int, m: int, j: int = j) -> int:
                                assert j == k
                                assert -1 == m
                                return k * m

                            def update2(k: int, v: int, m: int, j: int = j) -> int:
                                assert j == k
                                assert -j == v
                                assert -1 == m
                                return k * m

                            d.add_or_update(j, add2, update2, -1)

        _run_all(*(work for _ in range(threads)))

        for key, value in d.items():
            assert key == -value

        got_keys = sorted(key for key, _ in d.items())
        expect_keys = list(range(adds_per_thread))
        assert len(expect_keys) == len(got_keys)
        assert expect_keys == got_keys, (
            f"* Test '{'GetOrAdd' if is_add else 'GetOrUpdate'}': Level={c_level}, initSize={init_size}, "
            f"threads={threads}, addsPerThread={adds_per_thread})\n"
            "> FAILED.  The set of keys in the dictionary is are not the same as the expected."
        )

        # Finally, let's verify that the count is reported correctly.
        assert adds_per_thread == len(d)
        assert adds_per_thread == len(d.to_array())

    def test_TestBugFix669376(self) -> None:
        cd = ConcurrentDictionary[str, int](
            comparer=EqualityComparer.create(lambda x, y: x.casefold() == y.casefold(), lambda x: 0),
        )
        cd["test"] = 10
        assert cd.contains_key("TEST"), "Customized comparer didn't work"

    def test_TestConstructor(self) -> None:
        dictionary = ConcurrentDictionary[int, int]([(1, 1)])
        assert not dictionary.is_empty
        assert 1 == len(dictionary.keys())
        assert 1 == len(dictionary.values())

    @pytest.mark.parametrize("concurrency_level", [-1, 1, 10])
    def test_TestConstructor_ConcurrencyLevel(self, concurrency_level: int) -> None:
        dictionary = ConcurrentDictionary[int, int](concurrency_level=concurrency_level, capacity=0)
        assert 0 == len(dictionary)
        assert dictionary.try_add(1, 2)
        assert 1 == len(dictionary)

        dictionary = ConcurrentDictionary[Any, Any](comparer=EqualityComparer.default(), concurrency_level=concurrency_level, capacity=10)
        assert 0 == len(dictionary)
        assert dictionary.try_add(3, 4)
        assert 1 == len(dictionary)

        dictionary = ConcurrentDictionary[Any, Any]([(1, 1)], None, concurrency_level=concurrency_level)
        assert 1 == len(dictionary)
        assert dictionary.try_add(5, 6)
        assert 2 == len(dictionary)

    def test_TestNullComparer(self) -> None:
        # The IEquatableApiUsed / ObjectApiUsed probe is not portable (Python has only __eq__);
        # the add / re-add behavior of the default comparer is.
        def assert_default_comparer_behavior(dictionary: ConcurrentDictionary[object, int]) -> None:
            spy_key = object()
            assert dictionary.try_add(spy_key, 1)
            assert not dictionary.try_add(spy_key, 1)

        assert_default_comparer_behavior(ConcurrentDictionary[Any, Any](comparer=None))
        assert_default_comparer_behavior(ConcurrentDictionary[Any, Any]([(object(), 1)], None))
        assert_default_comparer_behavior(ConcurrentDictionary[Any, Any]([(object(), 1)], None, concurrency_level=1))
        assert_default_comparer_behavior(ConcurrentDictionary[Any, Any](comparer=None, concurrency_level=1, capacity=1))

    def test_TestComparerGetter(self) -> None:
        def assert_comparer_behavior(comparer: Any) -> None:
            dc = ConcurrentDictionary[Any, object](comparer=comparer)
            expected = comparer if comparer is not None else EqualityComparer.default()
            assert expected is dc.comparer

        assert_comparer_behavior(None)
        assert_comparer_behavior(EqualityComparer.default())
        assert_comparer_behavior(EqualityComparer.create(lambda x, y: x == y, hash))  # StringComparer.InvariantCulture
        assert_comparer_behavior(ORDINAL_IGNORE_CASE)
        assert_comparer_behavior(EqualityComparer.default())  # EqualityComparer<int>.Default
        assert_comparer_behavior(EqualityComparer.default())  # EqualityComparer<bool>.Default

    def test_TestConstructor_Negative(self) -> None:
        with pytest.raises(ArgumentNullError):
            ConcurrentDictionary[Any, Any](None)
        # "TestConstructor:  FAILED.  Constructor didn't throw ANE when null collection is passed");

        with pytest.raises(ArgumentNullError):
            ConcurrentDictionary[Any, Any](None, EqualityComparer.default())
        # "TestConstructor:  FAILED.  Constructor didn't throw ANE when null collection and non null IEqualityComparer passed");

        with pytest.raises(ArgumentNullError):
            ConcurrentDictionary[Any, Any]([(None, 1)])
        # "TestConstructor:  FAILED.  Constructor didn't throw ANE when collection has null key passed");

        # Duplicate keys.
        with pytest.raises(ArgumentError):
            ConcurrentDictionary[Any, Any]([(1, 1), (1, 2)])

        with pytest.raises(ArgumentNullError):
            ConcurrentDictionary[Any, Any](None, EqualityComparer.default(), concurrency_level=1)
        # "TestConstructor:  FAILED.  Constructor didn't throw ANE when null collection is passed");

        with pytest.raises(ArgumentOutOfRangeError):
            ConcurrentDictionary[Any, Any](concurrency_level=0, capacity=10)
        # "TestConstructor:  FAILED.  Constructor didn't throw AORE when <1 concurrencyLevel passed");

        with pytest.raises(ArgumentOutOfRangeError):
            ConcurrentDictionary[Any, Any](concurrency_level=-2, capacity=0)
        # "TestConstructor:  FAILED.  Constructor didn't throw AORE when < 0 capacity passed");

    def test_TestExceptions(self) -> None:
        dictionary = ConcurrentDictionary[str | None, int]()
        with pytest.raises(ArgumentNullError):
            dictionary.try_add(None, 0)
        #  "TestExceptions:  FAILED.  TryAdd didn't throw ANE when null key is passed");

        with pytest.raises(ArgumentNullError):
            dictionary.contains_key(None)
        # "TestExceptions:  FAILED.  Contains didn't throw ANE when null key is passed");

        with pytest.raises(ArgumentNullError):
            dictionary.try_remove(None)
        #  "TestExceptions:  FAILED.  TryRemove didn't throw ANE when null key is passed");
        with pytest.raises(ArgumentNullError):
            dictionary.try_get_value(None)
        # "TestExceptions:  FAILED.  TryGetValue didn't throw ANE when null key is passed");

        with pytest.raises(ArgumentNullError):
            _ = dictionary[None]
        # "TestExceptions:  FAILED.  this[] didn't throw ANE when null key is passed");

        with pytest.raises(KeyNotFoundError):
            _ = dictionary["1"]
        # "TestExceptions:  FAILED.  this[] TryGetValue didn't throw KeyNotFoundException!");

        with pytest.raises(ArgumentNullError):
            dictionary[None] = 1
        # "TestExceptions:  FAILED.  this[] didn't throw ANE when null key is passed");

        with pytest.raises(ArgumentNullError):
            dictionary.get_or_add(None, value_factory=lambda k, m: 0, factory_argument=0)
        # "TestExceptions:  FAILED.  GetOrAdd didn't throw ANE when null key is passed");
        with pytest.raises(ArgumentNullError):
            dictionary.get_or_add("1", value_factory=None, factory_argument=0)  # type: ignore[call-overload]
        # "TestExceptions:  FAILED.  GetOrAdd didn't throw ANE when null valueFactory is passed");
        with pytest.raises(ArgumentNullError):
            dictionary.get_or_add(None, value_factory=lambda k: 0)
        # "TestExceptions:  FAILED.  GetOrAdd didn't throw ANE when null key is passed");
        with pytest.raises(ArgumentNullError):
            dictionary.get_or_add("1", value_factory=None)  # type: ignore[call-overload]
        # "TestExceptions:  FAILED.  GetOrAdd didn't throw ANE when null valueFactory is passed");
        with pytest.raises(ArgumentNullError):
            dictionary.get_or_add(None, 0)
        # "TestExceptions:  FAILED.  GetOrAdd didn't throw ANE when null key is passed");

        with pytest.raises(ArgumentNullError):
            dictionary.add_or_update(None, add_value_factory=lambda k, m: 0, update_value_factory=lambda k, v, m: 0, factory_argument=42)
        # "TestExceptions:  FAILED.  AddOrUpdate didn't throw ANE when null key is passed");
        with pytest.raises(ArgumentNullError):
            dictionary.add_or_update("1", add_value_factory=lambda k, m: 0, update_value_factory=None, factory_argument=42)  # type: ignore[call-overload]
        # "TestExceptions:  FAILED.  AddOrUpdate didn't throw ANE when null updateFactory is passed");
        with pytest.raises(ArgumentNullError):
            dictionary.add_or_update("1", add_value_factory=None, update_value_factory=lambda k, v, m: 0, factory_argument=42)  # type: ignore[call-overload]
        # "TestExceptions:  FAILED.  AddOrUpdate didn't throw ANE when null addFactory is passed");
        with pytest.raises(ArgumentNullError):
            dictionary.add_or_update(None, add_value_factory=lambda k: 0, update_value_factory=lambda k, v: 0)
        # "TestExceptions:  FAILED.  AddOrUpdate didn't throw ANE when null key is passed");
        with pytest.raises(ArgumentNullError):
            dictionary.add_or_update("1", add_value_factory=None, update_value_factory=lambda k, v: 0)  # type: ignore[call-overload]
        # "TestExceptions:  FAILED.  AddOrUpdate didn't throw ANE when null updateFactory is passed");
        with pytest.raises(ArgumentNullError):
            dictionary.add_or_update(None, add_value_factory=lambda k: 0, update_value_factory=None)  # type: ignore[call-overload]
        # "TestExceptions:  FAILED.  AddOrUpdate didn't throw ANE when null addFactory is passed");

        # Duplicate key.
        dictionary.try_add("1", 1)
        with pytest.raises(ArgumentError):
            dictionary.add("1", 2)

    def test_TestIDictionary(self) -> None:
        not_portable(_NON_GENERIC)

    def test_TestIDictionary_Negative(self) -> None:
        not_portable(_NON_GENERIC)

    def test_IDictionary_Remove_NullKeyInKeyValuePair_ThrowsArgumentNullException(self) -> None:
        dictionary = ConcurrentDictionary[str, int]()
        with pytest.raises(ArgumentNullError):
            dictionary.try_remove_item((None, 0))  # type: ignore[arg-type]

    def test_TestICollection(self) -> None:
        dictionary = ConcurrentDictionary[int, int]()
        # IsSynchronized: not portable.

        key = -1
        value = +1
        # add one item to the dictionary
        dictionary.try_add(key, value)

        object_array: list[Any] = [None]
        dictionary.copy_to(object_array, 0)

        assert key == object_array[0][0]
        assert value == object_array[0][1]

        key_value_array: list[Any] = [None]
        dictionary.copy_to(key_value_array, 0)
        assert key == key_value_array[0][0]
        assert value == key_value_array[0][1]

        # DictionaryEntry[]: not portable (Python has one pair type).

    def test_TestICollection_Negative(self) -> None:
        dictionary = ConcurrentDictionary[int, int]()
        # IsSynchronized / SyncRoot: not portable.

        with pytest.raises(ArgumentNullError):
            dictionary.copy_to(None, 0)  # type: ignore[arg-type]
        # "TestICollection:  FAILED.  CopyTo didn't throw ANE when null Array is passed");
        with pytest.raises(ArgumentOutOfRangeError):
            dictionary.copy_to([], -1)
        # "TestICollection:  FAILED.  CopyTo didn't throw AORE when negative index passed");

        # add one item to the dictionary
        dictionary.try_add(1, 1)
        with pytest.raises(ArgumentError):
            dictionary.copy_to([], 0)
        # "TestICollection:  FAILED.  CopyTo didn't throw AE when the Array size is smaller than the dictionary count");

    def test_TestClear(self) -> None:
        dictionary = ConcurrentDictionary[int, int]()
        for i in range(10):
            dictionary.try_add(i, i)

        assert 10 == len(dictionary)

        dictionary.clear()
        assert 0 == len(dictionary)

        assert not dictionary.try_remove(1)[0], "TestClear: FAILED.  TryRemove succeeded after Clear"
        assert dictionary.is_empty, "TestClear: FAILED.  IsEmpty returned false after Clear"

    @pytest.mark.parametrize("capacity", [3, 1_162_687])
    def test_TestCapacity(self, capacity: int) -> None:
        not_portable("reads the internal bucket array through reflection")

    def test_TestTryUpdate(self) -> None:
        dictionary = ConcurrentDictionary[str, int]()
        with pytest.raises(ArgumentNullError):
            dictionary.try_update(None, 0, 0)  # type: ignore[arg-type]
        # "TestTryUpdate:  FAILED.  TryUpdate didn't throw ANE when null key is passed");

        for i in range(10):
            dictionary.try_add(str(i), i)

        for i in range(10):
            assert dictionary.try_update(str(i), i + 1, i), "TestTryUpdate:  FAILED.  TryUpdate failed!"
            assert i + 1 == dictionary[str(i)]

        # test TryUpdate concurrently
        dictionary.clear()
        for i in range(1000):
            dictionary.try_add(str(i), i)

        mres = threading.Event()
        updated_keys: ThreadLocal[ThreadData] = ThreadLocal(True)

        def update(obj: int) -> None:
            mres.wait()
            index = (obj + 1) + 1000
            updated_keys.value = ThreadData()
            updated_keys.value.thread_index = index

            for j in range(len(dictionary)):
                if dictionary.try_update(str(j), index, j):
                    if dictionary[str(j)] != index:
                        updated_keys.value.succeeded = False
                        return

                    updated_keys.value.keys.append(str(j))

        # LongRunning: each task on a thread of its own, as upstream.
        tasks = [
            Task.run(lambda obj=i: update(obj), creation_options=TaskCreationOptions.LONG_RUNNING)
            for i in range(10)
        ]

        mres.set()
        Task.wait_all(tasks)

        number_succeeded = 0
        total_keys_updated = 0
        for thread_data in updated_keys.values:
            total_keys_updated += len(thread_data.keys)
            if thread_data.succeeded:
                number_succeeded += 1

        assert number_succeeded == len(tasks), "One or more threads failed!"
        assert total_keys_updated == len(dictionary), (
            "TestTryUpdate:  FAILED.  The updated keys count doesn't match the dictionary count, "
            f"expected {len(dictionary)}, actual {total_keys_updated}"
        )
        for value in updated_keys.values:
            for key in value.keys:
                assert dictionary[key] == value.thread_index, (
                    "TestTryUpdate:  FAILED.  The updated value doesn't match the thread index, "
                    f"expected {value.thread_index} actual {dictionary[key]}"
                )

        # test TryUpdate with non atomic values (intPtr > 8)
        d = ConcurrentDictionary[int, Struct16]()
        d.try_add(1, Struct16(1, -1))
        assert d.try_update(1, Struct16(2, -2), Struct16(1, -1)), "TestTryUpdate:  FAILED.  TryUpdate failed for non atomic values ( > 8 bytes)"

    @pytest.mark.stress  # [OuterLoop("Runs for several seconds")]
    def test_ConcurrentWriteRead_NoTornValues(self) -> None:
        cd = ConcurrentDictionary[int, tuple[int, int]]()

        with CancellationTokenSource() as cts:
            cts.cancel_after(3.0)

            def write() -> None:
                i = 0
                while not cts.is_cancellation_requested:
                    cd[0] = (i, i)
                    i += 1

            def read() -> None:
                while not cts.is_cancellation_requested:
                    ok, item = cd.try_get_value(0)
                    if not ok:
                        continue
                    try:
                        assert item[0] == item[1]
                    except BaseException:
                        cts.cancel()
                        raise

            Task.wait_all(Task.run(write), Task.run(read))

    def test_GetAlternateLookup_FailsWhenIncompatible(self) -> None:
        not_portable(_ALTERNATE_LOOKUP)

    def test_GetAlternateLookup_OperationsMatchUnderlyingDictionary(self) -> None:
        not_portable(_ALTERNATE_LOOKUP)

    def test_Dictionary_NotCorruptedByThrowingComparer(self) -> None:
        not_portable(_ALTERNATE_LOOKUP)

    def test_Dictionary_NotCorruptedByNullReturningComparer(self) -> None:
        not_portable(_ALTERNATE_LOOKUP)


class ThreadData:
    def __init__(self) -> None:
        self.thread_index = 0
        self.succeeded = True
        self.keys: list[str] = []


@dataclass(frozen=True)
class Struct16:
    """Upstream ``struct Struct16``: compared by value."""

    l1: int
    l2: int


class TestConcurrentDictionary_NonGeneric_Tests:
    """Upstream runs the non-generic IDictionary / ICollection / IEnumerable suites here."""

    def test_IDictionary_NonGeneric_Tests(self) -> None:
        not_portable(_NON_GENERIC + "; the generic suites cover the Python mapping protocol")
