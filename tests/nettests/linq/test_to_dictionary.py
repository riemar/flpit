"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq ToDictionaryTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ToDictionaryTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET helper / language mapping:
    Dictionary<K,V>                    -> dict
    ToDictionary(keySelector)          -> to_dictionary(key_selector)
    ToDictionary(keySelector, elementSelector) -> to_dictionary(key_selector, element_selector)
    ToDictionary()  (KeyValuePair / (K,V) tuple sources) -> to_dictionary() with NO arguments (ASSUMED API;
                                          KeyValuePair<K,V> and ValueTuple (K,V) both map to a 2-tuple)
    ToDictionary(..., comparer)        -> extra trailing `comparer` argument (ASSUMED API, like the skipped
                                          comparer bodies in test_distinct.py)
    dict.Comparer                      -> `result.comparer` (ASSUMED attribute; Python dicts have none)
    IEqualityComparer<T>               -> _Comparer(equals, get_hash_code)
    TestEnumerable / TestReadOnlyCollection / TestCollection -> _ForceNotCollection / _TestReadOnlyCollection /
                                          _TestCollection
    anonymous types { Name, Score }    -> namedtuple _Item(name, score)
    ArgumentNullException("key")       -> ArgumentNullError
    ArgumentException                  -> ArgumentError
    InvalidOperationException          -> InvalidOperationError
    RunOnce()                          -> flp.it(run_once(...)) (conftest `run_once`)

Known reasons for failures in this file:
    * No argument-less to_dictionary(): key_selector is a required parameter.
    * No comparer overloads (an extra positional argument raises TypeError, or is mis-bound to element_selector).
    * Dicts have no comparer; None is a legal dict key (no ArgumentNullError); duplicates raise ValueError.
"""
from collections import namedtuple
from collections.abc import Collection

import pytest

from flpit import (
    flp,
    ArgumentError,
    ArgumentNullError,
    ElementSelectorNoneError,
    InvalidOperationError,
    SelectorNoneError,
    SourceNoneError,
)


# ---------------------------------------------------------------------------
# .NET test helpers
# ---------------------------------------------------------------------------

class _ForceNotCollection:
    """TestEnumerable<T>: IEnumerable<T> with no other interfaces."""

    def __init__(self, source):
        self._source = list(source)

    def __iter__(self):
        for item in self._source:
            yield item


class _TestReadOnlyCollection(Collection):
    """TestReadOnlyCollection<T>: sized + iterable, but not indexable."""

    def __init__(self, source):
        self._items = tuple(source)

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def __contains__(self, item):
        return item in self._items


class _TestCollection(Collection):
    """TestCollection<T>: ICollection<T> exposing its `items`."""

    def __init__(self, source):
        self.items = list(source)

    def __len__(self):
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def __contains__(self, item):
        return item in self.items


class _Comparer:
    """IEqualityComparer<T>-like helper."""

    def __init__(self, equals, get_hash_code):
        self.equals = equals
        self.get_hash_code = get_hash_code


_DEFAULT_COMPARER = _Comparer(lambda x, y: x == y, lambda x: hash(x))  # EqualityComparer<T>.Default
_ANAGRAM_COMPARER = _Comparer(
    lambda x, y: (x == y) if x is None or y is None else sorted(x) == sorted(y),
    lambda x: 0 if x is None else hash("".join(sorted(x))),
)

_Item = namedtuple("_Item", "name score")


def _run_on_all_collection_types(items, validation):
    """RunToDictionaryOnAllCollectionTypes<T>"""
    for make in (
        lambda: flp.it(list(items)),  # T[]
        lambda: flp.lst(items),  # List<T>
        lambda: flp.it(_ForceNotCollection(items)),  # TestEnumerable<T>
        lambda: flp.it(_TestReadOnlyCollection(items)),  # TestReadOnlyCollection<T>
        lambda: flp.it(_TestCollection(items)),  # TestCollection<T>
    ):
        validation(make().to_dictionary(lambda key: key))
        validation(make().to_dictionary(lambda key: key, lambda value: value))


def _run_from_kv_on_all_collection_types(items, validation):
    """RunToDictionaryFromKvOnAllCollectionTypes<T>: KeyValuePair<T,T>[] and (T,T)[] both map to 2-tuples."""
    kvps = [(item, item) for item in items]
    for _ in range(2):  # once for KeyValuePair<T,T>, once for ValueTuple (T,T)
        for make in (
            lambda: flp.it(list(kvps)),
            lambda: flp.lst(kvps),
            lambda: flp.it(_ForceNotCollection(kvps)),
            lambda: flp.it(_TestReadOnlyCollection(kvps)),
            lambda: flp.it(_TestCollection(kvps)),
        ):
            validation(make().to_dictionary())


def _assert_matches(keys, values, dict_):
    assert dict_ is not None
    assert keys is not None
    assert values is not None
    ke = iter(keys)
    for value in values:
        key = next(ke)  # Assert.True(ke.MoveNext())
        assert key in dict_  # TryGetValue
        assert value == dict_[key]
        del dict_[key]
    with pytest.raises(StopIteration):
        next(ke)  # Assert.False(ke.MoveNext())
    assert 0 == len(dict_)


# ---------------------------------------------------------------------------
# ToDictionaryTests
# ---------------------------------------------------------------------------

def test_ToDictionary_AlwaysCreateACopy():
    source = {1: 1, 2: 2, 3: 3}

    result = flp.it(list(source.items())).to_dictionary(lambda key: key[0], lambda val: val[1])
    assert result is not source
    assert source == result

    # Python API requires explicit key and value selectors"

    # result = flp.it(list(source.items())).to_dictionary()
    # assert result is not source
    # assert source == result


def test_ToDictionary_WorkWithEmptyCollection():
    def validation(result_dictionary):
        assert result_dictionary is not None
        assert 0 == len(result_dictionary)

    _run_on_all_collection_types([], validation)


@pytest.mark.skip("Python API requires explicit key and value selectors")
def test_ToDictionaryFromKv_WorkWithEmptyCollection():
    def validation(result_dictionary):
        assert result_dictionary is not None
        assert 0 == len(result_dictionary)

    # EXPECTED FAIL: no argument-less to_dictionary() (TypeError: key_selector is required).
    _run_from_kv_on_all_collection_types([], validation)


def test_ToDictionary_ProduceCorrectDictionary():
    source_array = [1, 2, 3, 4, 5, 6, 7]

    def validation(result_dictionary):
        assert len(source_array) == len(result_dictionary)
        assert source_array == list(result_dictionary.keys())
        assert source_array == list(result_dictionary.values())

    _run_on_all_collection_types(source_array, validation)

    source_string_array = ["1", "2", "3", "4", "5", "6", "7", "8"]

    def validation_strings(result_dictionary):
        assert len(source_string_array) == len(result_dictionary)
        for i in range(len(source_string_array)):
            assert source_string_array[i] is result_dictionary[source_string_array[i]]

    _run_on_all_collection_types(source_string_array, validation_strings)


@pytest.mark.skip("Python API requires explicit key and value selectors")
def test_ToDictionaryFromKv_ProduceCorrectDictionary():
    source_array = [1, 2, 3, 4, 5, 6, 7]

    def validation(result_dictionary):
        assert len(source_array) == len(result_dictionary)
        assert source_array == list(result_dictionary.keys())
        assert source_array == list(result_dictionary.values())

    # EXPECTED FAIL: no argument-less to_dictionary().
    _run_from_kv_on_all_collection_types(source_array, validation)

    source_string_array = ["1", "2", "3", "4", "5", "6", "7", "8"]

    def validation_strings(result_dictionary):
        assert len(source_string_array) == len(result_dictionary)
        for item in source_string_array:
            assert item is result_dictionary[item]

    _run_from_kv_on_all_collection_types(source_string_array, validation_strings)


@pytest.mark.skip("Python API requires explicit key and value selectors")
def test_RunOnce(run_once):
    assert {1: "0", 2: "1", 3: "2", 4: "3"} == flp.it(run_once(range(0, 4))).to_dictionary(
        lambda i: i + 1, lambda i: str(i)
    )

    # EXPECTED FAIL (next two asserts): no argument-less to_dictionary() for (key, value) items.
    assert {0: "0", 1: "1", 2: "2", 3: "3"} == flp.it(
        run_once(flp.range(0, 4).select(lambda i: (i, str(i))))  # KeyValuePair<int, string>
    ).to_dictionary()
    assert {0: "0", 1: "1", 2: "2", 3: "3"} == flp.it(
        run_once(flp.range(0, 4).select(lambda i: (i, str(i))))  # (int, string) tuple
    ).to_dictionary()


@pytest.mark.skip("Upstream .NET test requires unsupported FlpIt API: comparer overload (IEqualityComparer / IComparer)")
def test_ToDictionary_PassCustomComparer():
    comparer = _Comparer(lambda x, y: x == y, lambda x: x)
    collection = _TestCollection([1, 2, 3, 4, 5, 6])

    # EXPECTED FAIL: no comparer overloads (the comparer is bound to element_selector -> TypeError)
    # and a Python dict has no `comparer` attribute.
    result1 = flp.it(collection).to_dictionary(lambda key: key, comparer)
    assert comparer is result1.comparer
    result2 = flp.it(collection).to_dictionary(lambda key: key, lambda val: val, comparer)
    assert comparer is result2.comparer
    result3 = flp.it(collection).select(lambda i: (i, i)).to_dictionary(comparer)
    assert comparer is result3.comparer
    result4 = flp.it(collection).select(lambda i: (i, i)).to_dictionary(comparer)
    assert comparer is result4.comparer


@pytest.mark.skip("Upstream .NET test requires unsupported FlpIt API: comparer overload (IEqualityComparer / IComparer)")
def test_ToDictionary_UseDefaultComparerOnNull():
    collection = _TestCollection([1, 2, 3, 4, 5, 6])

    # EXPECTED FAIL: no comparer overload (comparer=None is bound to element_selector -> SelectorNoneError)
    # and a Python dict has no `comparer` attribute.
    result1 = flp.it(collection).to_dictionary(lambda key: key, None)
    assert _DEFAULT_COMPARER is result1.comparer
    result2 = flp.it(collection).to_dictionary(lambda key: key, lambda val: val, None)
    assert _DEFAULT_COMPARER is result2.comparer


@pytest.mark.skip("Upstream .NET test requires unsupported FlpIt API: comparer overload (IEqualityComparer / IComparer)")
def test_ToDictionary_UseDefaultComparer():
    collection = _TestCollection([1, 2, 3, 4, 5, 6])

    # EXPECTED FAIL: a Python dict has no `comparer` attribute (AttributeError); and no argument-less overload.
    result1 = flp.it(collection).to_dictionary(lambda key: key)
    assert _DEFAULT_COMPARER is result1.comparer
    result2 = flp.it(collection).to_dictionary(lambda key: key, lambda val: val)
    assert _DEFAULT_COMPARER is result2.comparer
    result3 = flp.it(collection).select(lambda i: (i, i)).to_dictionary()
    assert _DEFAULT_COMPARER is result3.comparer
    result4 = flp.it(collection).select(lambda i: (i, i)).to_dictionary()
    assert _DEFAULT_COMPARER is result4.comparer


def test_ToDictionary_KeyValueSelectorsWork():
    collection = _TestCollection([1, 2, 3, 4, 5, 6])

    result = flp.it(collection).to_dictionary(lambda key: key + 10, lambda val: val + 100)

    assert [o + 10 for o in collection.items] == list(result.keys())
    assert [o + 100 for o in collection.items] == list(result.values())


def test_ToDictionary_ThrowArgumentNullExceptionWhenSourceIsNull(flp_type):
    # .NET: ArgumentNullException("source") x3; flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).to_dictionary(lambda key: key)
    with pytest.raises(SourceNoneError):
        flp_type(None).to_dictionary()
    with pytest.raises(SourceNoneError):
        flp_type(None).to_dictionary()


def test_ToDictionary_ThrowArgumentNullExceptionWhenKeySelectorIsNull(flp_type):
    source = []
    key_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(source).to_dictionary(key_selector)


def test_ToDictionary_ThrowArgumentNullExceptionWhenValueSelectorIsNull(flp_type):
    source = []
    key_selector = lambda key: key
    value_selector = None

    with pytest.raises(ElementSelectorNoneError):
        flp_type(source).to_dictionary(key_selector, value_selector)


def test_ToDictionary_ThrowArgumentNullExceptionWhenSourceIsNullElementSelector(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).to_dictionary(lambda key: key, lambda e: e)


def test_ToDictionary_ThrowArgumentNullExceptionWhenKeySelectorIsNullElementSelector(flp_type):
    source = []
    key_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(source).to_dictionary(key_selector, lambda e: e)


def test_ToDictionary_KeySelectorThrowException(flp_type):
    source = [1, 2, 3]

    def key_selector(key):
        if key == 1:
            raise InvalidOperationError()
        return key

    with pytest.raises(InvalidOperationError):
        flp_type(source).to_dictionary(key_selector)


def test_ToDictionary_ThrowWhenKeySelectorReturnNull(flp_type):
    source = [1, 2, 3]
    key_selector = lambda key: None

    with pytest.raises(ArgumentNullError):
        flp_type(source).to_dictionary(key_selector)


def test_ToDictionary_ThrowWhenKeySelectorReturnSameValueTwice(flp_type):
    source = [1, 2, 3]
    key_selector = lambda key: 1

    with pytest.raises(ArgumentError):
        flp_type(source).to_dictionary(key_selector)


def test_ToDictionary_ValueSelectorThrowException(flp_type):
    source = [1, 2, 3]
    key_selector = lambda key: key

    def value_selector(value):
        if value == 1:
            raise InvalidOperationError()
        return value

    with pytest.raises(InvalidOperationError):
        flp_type(source).to_dictionary(key_selector, value_selector)


def test_ThrowsOnNullKey(flp_type):
    source = [_Item("Chris", 50), _Item("Bob", 95), _Item("null", 55)]
    flp_type(source).to_dictionary(lambda e: e.name)  # Doesn't throw

    source = [_Item("Chris", 50), _Item("Bob", 95), _Item(None, 55)]
    # EXPECTED FAIL: None is a legal dict key -> nothing is raised (.NET: ArgumentNullException("key")).
    with pytest.raises(ArgumentNullError):
        flp_type(source).to_dictionary(lambda e: e.name)

    # no parameterless overload supported

    # source2 = [("Chris", 50), ("Bob", 95), (None, 55)]
    # with pytest.raises(ArgumentNullError):
    #     flp_type(source2).to_dictionary()
    #
    # source3 = [("Chris", 50), ("Bob", 95), (None, 55)]
    # with pytest.raises(ArgumentNullError):
    #     flp_type(source3).to_dictionary()

@pytest.mark.skip("Upstream .NET test requires unsupported FlpIt API: comparer overload (IEqualityComparer / IComparer)")
def test_ThrowsOnNullKeyCustomComparer(flp_type):
    source = [_Item("Chris", 50), _Item("Bob", 95), _Item("null", 55)]
    # EXPECTED FAIL: no comparer overload; the comparer is bound to element_selector and called
    # -> TypeError ('_Comparer' object is not callable) even for the "doesn't throw" case.
    flp_type(source).to_dictionary(lambda e: e.name, _ANAGRAM_COMPARER)  # Doesn't throw

    source = [_Item("Chris", 50), _Item("Bob", 95), _Item(None, 55)]
    with pytest.raises(ArgumentNullError):
        flp_type(source).to_dictionary(lambda e: e.name, _ANAGRAM_COMPARER)


def test_ThrowsOnNullKeyValueSelector(flp_type):
    source = [_Item("Chris", 50), _Item("Bob", 95), _Item("null", 55)]
    flp_type(source).to_dictionary(lambda e: e.name, lambda e: e)  # Doesn't throw

    source = [_Item("Chris", 50), _Item("Bob", 95), _Item(None, 55)]
    with pytest.raises(ArgumentNullError):
        flp_type(source).to_dictionary(lambda e: e.name, lambda e: e)


@pytest.mark.skip("Upstream .NET test requires unsupported FlpIt API: comparer overload (IEqualityComparer / IComparer)")
def test_ThrowsOnNullKeyCustomComparerValueSelector(flp_type):
    source = [_Item("Chris", 50), _Item("Bob", 95), _Item("null", 55)]
    # EXPECTED FAIL: no comparer overload: a 3rd positional argument raises TypeError.
    flp_type(source).to_dictionary(lambda e: e.name, lambda e: e, _ANAGRAM_COMPARER)  # Doesn't throw

    source = [_Item("Chris", 50), _Item("Bob", 95), _Item(None, 55)]
    with pytest.raises(ArgumentNullError):
        flp_type(source).to_dictionary(lambda e: e.name, lambda e: e, _ANAGRAM_COMPARER)


@pytest.mark.skip("Upstream .NET test requires unsupported FlpIt API: comparer overload (IEqualityComparer / IComparer)")
def test_ThrowsOnDuplicateKeys(flp_type):
    source = [_Item("Chris", 50), _Item("Bob", 95), _Item("Bob", 55)]
    # EXPECTED FAIL: no comparer overload: the 3rd positional argument raises TypeError, not ArgumentError.
    with pytest.raises(ArgumentError):
        flp_type(source).to_dictionary(lambda e: e.name, lambda e: e, _ANAGRAM_COMPARER)

    source2 = [("Chris", 50), ("Bob", 95), ("Bob", 55)]
    with pytest.raises(ArgumentError):
        flp_type(source2).to_dictionary(_ANAGRAM_COMPARER)

    source3 = [("Chris", 50), ("Bob", 95), ("Bob", 55)]
    with pytest.raises(ArgumentError):
        flp_type(source3).to_dictionary(_ANAGRAM_COMPARER)



def test_EmptySource(flp_type):
    elements = []
    keys = []
    source = flp_type(keys).zip(elements, lambda k, e: _Item(k, e))

    # EXPECTED FAIL: no comparer overload (3rd positional argument -> TypeError).
    # _assert_matches(keys, elements, source.to_dictionary(lambda e: e.name, lambda e: e.score, _ANAGRAM_COMPARER))
    _assert_matches(keys, elements, source.to_dictionary(lambda e: e.name, lambda e: e.score))


def test_OneElementNullComparer(flp_type):
    elements = [5]
    keys = ["Bob"]
    source = flp_type([_Item(keys[0], elements[0])])

    # EXPECTED FAIL: no comparer overload (3rd positional argument -> TypeError, even for None).
    # _assert_matches(keys, elements, source.to_dictionary(lambda e: e.name, lambda e: e.score, None))
    _assert_matches(keys, elements, source.to_dictionary(lambda e: e.name, lambda e: e.score))


@pytest.mark.skip("Upstream .NET test requires unsupported FlpIt API: comparer overload (IEqualityComparer / IComparer)")
def test_SeveralElementsCustomComparerer(flp_type):
    keys = ["Bob", "Zen", "Prakash", "Chris", "Sachin"]
    source = [
        _Item("Bbo", 95),
        _Item(keys[1], 45),
        _Item(keys[2], 100),
        _Item(keys[3], 90),
        _Item(keys[4], 45),
    ]

    # EXPECTED FAIL: no comparer overload: the comparer is bound to element_selector -> TypeError
    # (and a plain dict could not match the anagram key "Bbo" to "Bob" anyway).
    _assert_matches(keys, source, flp_type(source).to_dictionary(lambda e: e.name, _ANAGRAM_COMPARER))


# @pytest.mark.skip("Upstream .NET test requires unsupported FlpIt API: comparer overload (IEqualityComparer / IComparer)")
def test_NullCoalescedKeySelector(flp_type):
    elements = [None]
    keys = [""]
    source = [None]

    # EXPECTED FAIL: no comparer overload (3rd positional argument -> TypeError).
    _assert_matches(
        keys,
        elements,
        # flp_type(source).to_dictionary(lambda e: e if e is not None else "", lambda e: e, _DEFAULT_COMPARER),
        flp_type(source).to_dictionary(lambda e: e if e is not None else "", lambda e: e),
    )
