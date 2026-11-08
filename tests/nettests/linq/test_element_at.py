"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq ElementAtTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ElementAtTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

.NET's ElementAt has three overloads that the original tests interleave:
    ElementAt(int index)        -> element_at(index)
    ElementAt(new Index(index)) -> not implemented yet
    ElementAt(^indexFromEnd)    -> not implemented yet
Because the second and third overload do not exist, every test is parametrized by
`overload` ("int", "Index", "from_end"): the "int" case runs live and the other two are
skipped individually, so the working overload stays covered. The skipped cases assume
the future API element_at(flp.index(k)) and element_at(flp.from_end(k)) (see _at).

.NET source-type helpers are mapped to Python sources as follows:
    int[] / List<int>              -> flp_type(list)
    NumberRangeGuaranteedNotCollectionType(start, count) -> flp.it(range)
    ForceNotCollection(source)     -> flp_type(_ForceNotCollection(list))
    ListPartitionOrEmpty(source)   -> flp_type(list).skip(0)
    EnumerablePartitionOrEmpty(..) -> flp_type(_ForceNotCollection(list)).skip(0)
    TestCollection<int>            -> flp.it(deque)
    TestNonGenericCollection<int>  -> flp.it(tuple)
    DelegateIterator<int>          -> generator counting how often it is advanced
.NET's RunOnce() is replaced by a one-shot generator (see _run_once).

Not portable (skipped with a reason):
    * ImmutableArray<T>-specific IndexOutOfRangeException tests (the *_ThrowsIListIndexerException
      tests): there is no Python counterpart for that IList indexer behaviour.
"""

from collections import deque

import pytest

from flpit import (
    flp,
    ArgumentOutOfRangeError,
    SourceNoneError,
)

INT_MAX = 2147483647
INT_MIN = -2147483648

_OOR = ArgumentOutOfRangeError  # ArgumentOutOfRangeException("index")

_OVERLOADS = [
    "int",
    pytest.param("Index", marks=pytest.mark.skip("Index not implemented yet")),
    pytest.param("from_end", marks=pytest.mark.skip("from-end index not implemented yet")),
]

_OVERLOAD_POSITION = {"int": 0, "Index": 1, "from_end": 2}


def _run_once(source):
    """One-shot generator replacing .NET's RunOnce()."""
    for item in source:
        yield item


class _ForceNotCollection:
    """Lazy, re-enumerable iterable over a live list; not a collection."""

    def __init__(self, source):
        self._source = source

    def __iter__(self):
        for item in self._source:
            yield item


def _at(overload, source, value):
    """ElementAt(...) for the given overload; `value` is the index or the from-end amount."""
    if overload == "int":
        return source.element_at(value)
    if overload == "Index":
        return source.element_at(flp.index(value))  # assumed future API: new Index(value)
    return source.element_at(flp.from_end(value))  # assumed future API: ^value


def _run(overload, make_source, steps):
    """Runs the steps (kind, value, expected) that belong to `overload`.

    `expected` is either the expected element or an exception type.
    `make_source` creates a fresh source for every step, like the original tests do.
    """
    for kind, value, expected in steps:
        if kind != overload:
            continue
        if isinstance(expected, type) and issubclass(expected, Exception):
            with pytest.raises(expected):
                _at(overload, make_source(), value)
        else:
            assert expected == _at(overload, make_source(), value)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_SameResultsRepeatCallsIntQuery(flp_type, overload):
    q = [
        flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > INT_MIN)
        for _ in range(3)
    ]
    value = {"int": 3, "Index": 3, "from_end": 6}[overload]
    query = q[_OVERLOAD_POSITION[overload]]

    assert _at(overload, query, value) == _at(overload, query, value)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_SameResultsRepeatCallsStringQuery(flp_type, overload):
    q = [
        flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]).where(lambda x: bool(x))
        for _ in range(3)
    ]
    value = {"int": 4, "Index": 4, "from_end": 2}[overload]
    query = q[_OVERLOAD_POSITION[overload]]

    assert _at(overload, query, value) == _at(overload, query, value)


_TEST_DATA = [
    (lambda: flp.it(range(9, 10)), 0, 1, 9),
    (lambda: flp.it(range(9, 19)), 9, 1, 18),
    (lambda: flp.it(range(-4, 6)), 3, 7, -1),
    (lambda: flp.it([-4]), 0, 1, -4),
    (lambda: flp.it([9, 8, 0, -5, 10]), 4, 1, 10),
]
_TEST_DATA_IDS = ["range_9_1", "range_9_10", "range_-4_10", "array_one", "array_five"]


@pytest.mark.parametrize("overload", _OVERLOADS)
@pytest.mark.parametrize("make_source, index, index_from_end, expected", _TEST_DATA, ids=_TEST_DATA_IDS)
def test_ElementAt(make_source, index, index_from_end, expected, overload):
    source = make_source()
    value = index_from_end if overload == "from_end" else index

    assert expected == _at(overload, source, value)


@pytest.mark.parametrize("overload", _OVERLOADS)
@pytest.mark.parametrize("make_source, index, index_from_end, expected", _TEST_DATA, ids=_TEST_DATA_IDS)
def test_ElementAtRunOnce(make_source, index, index_from_end, expected, overload):
    items = list(make_source())
    value = index_from_end if overload == "from_end" else index

    assert expected == _at(overload, flp.it(_run_once(items)), value)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_InvalidIndex_ThrowsArgumentOutOfRangeException(flp_type, overload):
    cases = [
        (lambda: flp_type([9, 8]), [
            ("int", -1), ("from_end", 3), ("int", INT_MAX), ("int", INT_MIN),
            ("Index", INT_MAX), ("from_end", INT_MAX),
        ]),
        (lambda: flp_type([1, 2, 3, 4]), [
            ("int", 4), ("Index", 4), ("from_end", 0), ("from_end", 5),
        ]),
        (lambda: flp_type([]), [
            ("int", 0), ("Index", 0), ("from_end", 0), ("from_end", 1),
        ]),
        (lambda: flp_type(range(-4, 1)), [
            ("int", -1), ("int", INT_MIN), ("int", INT_MAX), ("from_end", 6),
            ("Index", INT_MAX), ("from_end", INT_MAX),
        ]),
        (lambda: flp_type(range(5, 5)), [
            ("int", 5), ("Index", 5), ("from_end", 0),
        ]),
        (lambda: flp_type(range(0, 0)), [
            ("int", 0), ("Index", 0), ("from_end", 0), ("from_end", 1),
        ]),
    ]

    for make_source, throws in cases:
        _run(overload, make_source, [(kind, value, _OOR) for kind, value in throws])


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_NullableArray_ValidIndex_ReturnsCorrectObject(flp_type, overload):
    make_source = lambda: flp_type([9, 8, None, -5, 10])

    _run(overload, make_source, [
        ("int", 2, None),
        ("int", 3, -5),
        ("Index", 2, None),
        ("Index", 3, -5),
        ("from_end", 3, None),
        ("from_end", 2, -5),
    ])


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_NullSource_ThrowsArgumentNullException(flp_type, overload):
    # .NET has a distinct null-source ArgumentNullException contract.
    # Python's corresponding invalid-source case is SourceNoneError, raised by
    # the FlpIt/FlpList constructor before element_at() can be invoked.
    _run(overload, lambda: flp_type(None), [
        ("int", 2, SourceNoneError),
        ("Index", 2, SourceNoneError),
        ("from_end", 2, SourceNoneError),
    ])


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_MutableSource(overload):
    source = flp.lst([0, 1, 2, 3, 4])
    make_source = lambda: source

    _run(overload, make_source, [
        ("int", 2, 2),
        ("Index", 2, 2),
        ("from_end", 3, 2),
    ])

    source.insert_range(3, [-1, -2])
    source.remove_at(0)

    _run(overload, make_source, [
        ("int", 2, -1),
        ("Index", 2, -1),
        ("from_end", 4, -1),
    ])


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_MutableSourceNotList(overload):
    source = [0, 1, 2, 3, 4]
    position = _OVERLOAD_POSITION[overload]

    query1 = [flp.it(_ForceNotCollection(source)).select(lambda i: i) for _ in range(3)]
    _run(overload, lambda: query1[position], [
        ("int", 2, 2),
        ("Index", 2, 2),
        ("from_end", 3, 2),
    ])

    query2 = [flp.it(_ForceNotCollection(source)).select(lambda i: i) for _ in range(3)]
    source[3:3] = [-1, -2]  # InsertRange(3, [-1, -2])
    del source[0]           # RemoveAt(0)

    _run(overload, lambda: query2[position], [
        ("int", 2, -1),
        ("Index", 2, -1),
        ("from_end", 4, -1),
    ])


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_EnumerateElements(overload):
    ELEMENT_COUNT = 10
    state = -1
    move_next_call_count = 0

    def source():
        nonlocal state, move_next_call_count
        state = -1
        move_next_call_count = 0

        def iterator():
            nonlocal state, move_next_call_count
            try:
                while True:
                    move_next_call_count += 1  # MoveNext()
                    state += 1
                    if not state < ELEMENT_COUNT:
                        return
                    yield state  # Current
            finally:
                state = -1  # Dispose()

        return flp.it(iterator())

    # (kind, value, expected element or exception, expected MoveNext call count)
    steps = [
        ("int", 0, 0, 1),
        ("Index", 0, 0, 1),
        ("int", 5, 5, 6),
        ("Index", 5, 5, 6),
        ("from_end", ELEMENT_COUNT, 0, ELEMENT_COUNT + 1),
        ("from_end", 5, 5, ELEMENT_COUNT + 1),
        ("int", ELEMENT_COUNT, _OOR, ELEMENT_COUNT + 1),
        ("Index", ELEMENT_COUNT, _OOR, ELEMENT_COUNT + 1),
        ("from_end", 0, _OOR, 0),
    ]

    for kind, value, expected, expected_count in steps:
        if kind != overload:
            continue
        if isinstance(expected, type) and issubclass(expected, Exception):
            with pytest.raises(expected):
                _at(overload, source(), value)
        else:
            assert expected == _at(overload, source(), value)
        assert move_next_call_count == expected_count


_NON_EMPTY_STEPS = [
    ("int", 5, 5), ("Index", 5, 5), ("from_end", 5, 5),
    ("int", 0, 0), ("Index", 0, 0), ("from_end", 10, 0),
    ("int", 9, 9), ("Index", 9, 9), ("from_end", 1, 9),
    ("int", -1, _OOR),
    ("from_end", 11, _OOR),
    ("int", 10, _OOR),
    ("Index", 10, _OOR),
    ("from_end", 0, _OOR),
    ("int", INT_MIN, _OOR),
    ("from_end", INT_MAX, _OOR),
    ("int", INT_MAX, _OOR),
    ("Index", INT_MAX, _OOR),
]

_EMPTY_STEPS = [
    ("int", 1, _OOR),
    ("int", -1, _OOR),
    ("Index", 1, _OOR),
    ("from_end", 1, _OOR),
    ("int", 0, _OOR),
    ("Index", 0, _OOR),
    ("from_end", 0, _OOR),
    ("int", INT_MIN, _OOR),
    ("from_end", INT_MAX, _OOR),
    ("int", INT_MAX, _OOR),
    ("Index", INT_MAX, _OOR),
]

_SOURCE = list(range(10))


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_NonEmptySource_Consistency(flp_type, overload):
    _run(overload, lambda: flp_type(list(_SOURCE)), _NON_EMPTY_STEPS)


@pytest.mark.skip(".NET ImmutableArray IList indexer exception has no Python counterpart")
def test_NonEmptySource_Consistency_ThrowsIListIndexerException():
    # .NET: ImmutableArray<T> implements IList<T>; ElementAt calls its indexer, which
    # throws IndexOutOfRangeException instead of ArgumentOutOfRangeException.
    pass


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_NonEmptySource_Consistency_NotList(flp_type, overload):
    _run(overload, lambda: flp_type(_ForceNotCollection(list(_SOURCE))), _NON_EMPTY_STEPS)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_NonEmptySource_Consistency_ListPartition(flp_type, overload):
    _run(overload, lambda: flp_type(list(_SOURCE)).skip(0), _NON_EMPTY_STEPS)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_NonEmptySource_Consistency_EnumerablePartition(flp_type, overload):
    _run(overload, lambda: flp_type(_ForceNotCollection(list(_SOURCE))).skip(0), _NON_EMPTY_STEPS)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_NonEmptySource_Consistency_Collection(overload):
    _run(overload, lambda: flp.it(deque(_SOURCE)), _NON_EMPTY_STEPS)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_NonEmptySource_Consistency_NonGenericCollection(overload):
    _run(overload, lambda: flp.it(tuple(_SOURCE)), _NON_EMPTY_STEPS)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_EmptySource_Consistency(flp_type, overload):
    _run(overload, lambda: flp_type([]), _EMPTY_STEPS)


@pytest.mark.skip(".NET ImmutableArray IList indexer exception has no Python counterpart")
def test_EmptySource_Consistency_ThrowsIListIndexerException():
    # .NET: ImmutableArray<T> implements IList<T>; ElementAt calls its indexer, which
    # throws IndexOutOfRangeException instead of ArgumentOutOfRangeException.
    pass


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_EmptySource_Consistency_NotList(flp_type, overload):
    _run(overload, lambda: flp_type(_ForceNotCollection([])), _EMPTY_STEPS)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_EmptySource_Consistency_ListPartition(flp_type, overload):
    _run(overload, lambda: flp_type([]).skip(0), _EMPTY_STEPS)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_EmptySource_Consistency_EnumerablePartition(flp_type, overload):
    _run(overload, lambda: flp_type(_ForceNotCollection([])).skip(0), _EMPTY_STEPS)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_EmptySource_Consistency_Collection(overload):
    _run(overload, lambda: flp.it(deque()), _EMPTY_STEPS)


@pytest.mark.parametrize("overload", _OVERLOADS)
def test_EmptySource_Consistency_NonGenericCollection(overload):
    _run(overload, lambda: flp.it(()), _EMPTY_STEPS)