"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq GroupByTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/GroupByTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for flp's API.

.NET's Record struct is mapped to a frozen dataclass, IGrouping<TKey, TElement> to Grouping.
.NET's RunOnce() is replaced by a one-shot generator (see _run_once).

group_by() currently implements only the GroupBy(keySelector) overload. The other seven
.NET overloads differ by the *type* of their second and third argument (comparer, element
selector, result selector), which positional arity can not tell apart, so the skipped bodies
assume keyword-only parameters:

    group_by(key_selector, *, element_selector=None, result_selector=None, comparer=None)

with result_selector(key, elements) and a comparer object offering equals(x, y) and
get_hash_code(x), like IEqualityComparer<T>.

Skip reasons (the first missing feature wins when several are missing):
    element selector not implemented yet > result selector not implemented yet >
    comparer not implemented yet
"""

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest

from flpit import (
    flp,
    ArgumentOutOfRangeError,
    SourceNoneError,
    SelectorNoneError,
)

_SKIP_ELEMENT = pytest.mark.skip("element selector not implemented yet")
_SKIP_RESULT = pytest.mark.skip("result selector not implemented yet")
_SKIP_COMPARER = pytest.mark.skip("comparer not implemented yet")


def _run_once(source):
    """One-shot generator replacing .NET's RunOnce()."""
    for item in source:
        yield item


@dataclass(frozen=True)
class Record:
    name: str | None
    score: int


class _Comparer:
    """IEqualityComparer<T>-like helper for the skipped comparer tests."""

    def __init__(self, equals, get_hash_code):
        self.equals = equals
        self.get_hash_code = get_hash_code


_DEFAULT_COMPARER = _Comparer(lambda x, y: x == y, lambda x: hash(x))


def _anagram_equals(x, y):
    if x is None or y is None:
        return x == y
    return sorted(x) == sorted(y)


def _anagram_hash(obj):
    if obj is None:
        return 0
    result = len(obj)
    for c in obj:
        result ^= ord(c)
    return result


_ANAGRAM_COMPARER = _Comparer(_anagram_equals, _anagram_hash)


def _records():
    return [
        Record("Tim", 55),
        Record("Chris", 49),
        Record("Robert", -100),
        Record("Chris", 24),
        Record("Prakash", 9),
        Record("Tim", 25),
    ]


def _assert_grouping_correct(keys, elements, grouping, key_comparer=None):
    if grouping is None:
        assert elements is None
        assert keys is None
        return

    assert elements is not None
    assert keys is not None

    def same(a, b):
        return key_comparer.equals(a, b) if key_comparer is not None else a == b

    groups = []  # [key, elements] pairs; looked up with the key comparer
    grouping_for_null_keys = []

    el_it = iter(elements)
    for key in keys:
        element = next(el_it)  # Assert.True(elEn.MoveNext())
        if key is None:
            grouping_for_null_keys.append(element)
        else:
            for entry in groups:
                if same(entry[0], key):
                    entry[1].append(element)
                    break
            else:
                groups.append([key, [element]])
    assert next(el_it, _MISSING) is _MISSING  # Assert.False(elEn.MoveNext())

    for group in grouping:
        assert group.any()  # Assert.NotEmpty(group)
        key = group.key
        if key is None:
            assert grouping_for_null_keys == list(group)
            grouping_for_null_keys.clear()
        else:
            for entry in groups:
                if same(entry[0], key):
                    assert entry[1] == list(group)
                    groups.remove(entry)
                    break
            else:
                pytest.fail(f"key {key!r} not found")

    assert groups == []
    assert grouping_for_null_keys == []


_MISSING = object()


@_SKIP_ELEMENT
def test_SameResultsRepeatCallsStringQuery():
    q1 = flp.it(["Alen", "Felix", None, None, "X", "Have Space", "Clinton", ""]).select(lambda x1: x1)
    q2 = flp.it([55, 49, 9, -100, 24, 25, -1, 0]).select(lambda x2: x2)

    # from x3 in q1 from x4 in q2 select new { a1 = x3, a2 = x4 }
    q = q1.select_many(lambda x3: q2.select(lambda x4: SimpleNamespace(a1=x3, a2=x4)))

    assert q.group_by(lambda e: e.a1, element_selector=lambda e: e.a2) is not None
    assert list(q.group_by(lambda e: e.a1, element_selector=lambda e: e.a2)) == list(
        q.group_by(lambda e: e.a1, element_selector=lambda e: e.a2)
    )


@pytest.mark.skip("Grouping is not an IList: there is no IsReadOnly in Python")
def test_Grouping_IList_IsReadOnly():
    # .NET asserts IList.IsReadOnly for every grouping.
    pass


@pytest.mark.skip("Grouping is not an IList: its mutators do not exist")
def test_Grouping_IList_NotSupported():
    # .NET expects NotSupportedException from Add, Clear, Insert, Remove, RemoveAt and the
    # indexer setter. A Grouping simply has none of these members.
    pass


@pytest.mark.skip("Grouping indexer not implemented yet")
def test_Grouping_IList_IndexerGetter():
    odds_evens = flp.it([1, 2, 3, 4]).group_by(lambda i: i % 2 == 0)

    e = iter(odds_evens)
    odds = next(e)
    assert odds[0] == 1
    assert odds[1] == 3

    evens = next(e)
    assert evens[0] == 2
    assert evens[1] == 4


@pytest.mark.skip("Grouping indexer not implemented yet")
def test_Grouping_IList_IndexGetterOutOfRange():
    odds_evens = flp.it([1, 2, 3, 4]).group_by(lambda i: i % 2 == 0)

    e = iter(odds_evens)
    odds = next(e)

    # Python negative indices conflict with .NET's ArgumentOutOfRangeException("index").
    with pytest.raises(ArgumentOutOfRangeError):
        odds[-1]
    with pytest.raises(ArgumentOutOfRangeError):
        odds[23]


def test_Grouping_ICollection_Contains(flp_type):
    odds_evens = flp_type([1, 2, 3, 4]).group_by(lambda i: i % 2 == 0)

    e = iter(odds_evens)
    odds = next(e)
    assert 1 in odds
    assert 3 in odds
    assert 2 not in odds
    assert 4 not in odds

    evens = next(e)
    assert 2 in evens
    assert 4 in evens
    assert 1 not in evens
    assert 3 not in evens


@pytest.mark.skip("index_of not implemented yet")
def test_Grouping_IList_IndexOf():
    odds_evens = flp.it([1, 2, 3, 4]).group_by(lambda i: i % 2 == 0)

    e = iter(odds_evens)
    odds = next(e)
    assert odds.index_of(1) == 0
    assert odds.index_of(3) == 1
    assert odds.index_of(2) == -1
    assert odds.index_of(4) == -1

    evens = next(e)
    assert evens.index_of(2) == 0
    assert evens.index_of(4) == 1
    assert evens.index_of(1) == -1
    assert evens.index_of(3) == -1


@_SKIP_ELEMENT
def test_SingleNullKeySingleNullElement():
    key = [None]
    element = [None]

    _assert_grouping_correct(
        key,
        element,
        flp.it([None]).group_by(lambda e: e, element_selector=lambda e: e, comparer=_DEFAULT_COMPARER),
        _DEFAULT_COMPARER,
    )


@_SKIP_ELEMENT
def test_EmptySource():
    assert list(
        flp.it([]).group_by(lambda e: e.name, element_selector=lambda e: e.score, comparer=_ANAGRAM_COMPARER)
    ) == []


@_SKIP_ELEMENT
def test_EmptySourceRunOnce():
    assert list(
        flp.it(_run_once([])).group_by(
            lambda e: e.name, element_selector=lambda e: e.score, comparer=_ANAGRAM_COMPARER
        )
    ) == []


@_SKIP_ELEMENT
def test_SourceIsNull(flp_type):
    source = None

    with pytest.raises(SourceNoneError):
        flp_type(source).group_by(
            lambda e: e.name, element_selector=lambda e: e.score, comparer=_ANAGRAM_COMPARER
        )

    with pytest.raises(SourceNoneError):
        flp_type(source).group_by(lambda e: e.name, comparer=_ANAGRAM_COMPARER)


@_SKIP_ELEMENT
def test_SourceIsNullResultSelectorUsed(flp_type):
    source = None

    with pytest.raises(SourceNoneError):
        flp_type(source).group_by(
            lambda e: e.name,
            element_selector=lambda e: e.score,
            result_selector=lambda k, es: sum(es),
            comparer=_ANAGRAM_COMPARER,
        )


@_SKIP_ELEMENT
def test_SourceIsNullResultSelectorUsedNoComparer(flp_type):
    source = None

    with pytest.raises(SourceNoneError):
        flp_type(source).group_by(
            lambda e: e.name,
            element_selector=lambda e: e.score,
            result_selector=lambda k, es: sum(es),
        )


@_SKIP_RESULT
def test_SourceIsNullResultSelectorUsedNoComparerOrElementSelector(flp_type):
    source = None

    with pytest.raises(SourceNoneError):
        flp_type(source).group_by(
            lambda e: e.name, result_selector=lambda k, es: sum(e.score for e in es)
        )


@_SKIP_ELEMENT
def test_KeySelectorNull(flp_type):
    source = _records()

    with pytest.raises(SelectorNoneError):
        flp_type(source).group_by(None, element_selector=lambda e: e.score, comparer=_ANAGRAM_COMPARER)

    with pytest.raises(SelectorNoneError):
        flp_type(source).group_by(None, comparer=_ANAGRAM_COMPARER)


@_SKIP_ELEMENT
def test_KeySelectorNullResultSelectorUsed(flp_type):
    source = _records()

    with pytest.raises(SelectorNoneError):
        flp_type(source).group_by(
            None,
            element_selector=lambda e: e.score,
            result_selector=lambda k, es: sum(es),
            comparer=_ANAGRAM_COMPARER,
        )


@_SKIP_ELEMENT
def test_KeySelectorNullResultSelectorUsedNoComparer(flp_type):
    source = _records()
    key_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(source).group_by(
            key_selector, element_selector=lambda e: e.score, result_selector=lambda k, es: sum(es)
        )


@_SKIP_RESULT
def test_KeySelectorNullResultSelectorUsedNoElementSelector(flp_type):
    key = ["Tim", "Tim", "Tim", "Tim"]
    element = [60, -10, 40, 100]
    source = [Record(k, e) for k, e in zip(key, element)]

    with pytest.raises(SelectorNoneError):
        flp_type(source).group_by(
            None,
            result_selector=lambda k, es: sum(e.score for e in es),
            comparer=_ANAGRAM_COMPARER,
        )


@_SKIP_ELEMENT
def test_ElementSelectorNull(flp_type):
    source = _records()
    element_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(source).group_by(
            lambda e: e.name, element_selector=element_selector, comparer=_ANAGRAM_COMPARER
        )


@_SKIP_ELEMENT
def test_ElementSelectorNullResultSelectorUsedNoComparer(flp_type):
    source = _records()
    element_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(source).group_by(
            lambda e: e.name, element_selector=element_selector, result_selector=lambda k, es: sum(es)
        )


@_SKIP_ELEMENT
def test_ResultSelectorNull(flp_type):
    source = _records()
    result_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(source).group_by(
            lambda e: e.name,
            element_selector=lambda e: e.score,
            result_selector=result_selector,
            comparer=_ANAGRAM_COMPARER,
        )


@_SKIP_ELEMENT
def test_ResultSelectorNullNoComparer(flp_type):
    source = _records()
    result_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(source).group_by(
            lambda e: e.name, element_selector=lambda e: e.score, result_selector=result_selector
        )


@_SKIP_RESULT
def test_ResultSelectorNullNoElementSelector(flp_type):
    source = _records()
    result_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(source).group_by(lambda e: e.name, result_selector=result_selector)


@_SKIP_RESULT
def test_ResultSelectorNullNoElementSelectorCustomComparer(flp_type):
    key = ["Tim", "Tim", "Tim", "Tim"]
    element = [60, -10, 40, 100]
    source = [Record(k, e) for k, e in zip(key, element)]
    result_selector = None

    with pytest.raises(SelectorNoneError):
        flp_type(source).group_by(
            lambda e: e.name, result_selector=result_selector, comparer=_ANAGRAM_COMPARER
        )


@_SKIP_ELEMENT
def test_EmptySourceWithResultSelector():
    assert list(
        flp.it([]).group_by(
            lambda e: e.name,
            element_selector=lambda e: e.score,
            result_selector=lambda k, es: len(k if k is not None else " ") * sum(es),
            comparer=_ANAGRAM_COMPARER,
        )
    ) == []


@_SKIP_ELEMENT
def test_DuplicateKeysCustomComparer():
    source = [
        Record("Tim", 55),
        Record("Chris", 49),
        Record("Robert", -100),
        Record("Chris", 24),
        Record("Prakash", 9),
        Record("miT", 25),
    ]
    expected = [240, 365, -600, 63]

    assert expected == list(
        flp.it(source).group_by(
            lambda e: e.name,
            element_selector=lambda e: e.score,
            result_selector=lambda k, es: len(k if k is not None else " ") * sum(es),
            comparer=_ANAGRAM_COMPARER,
        )
    )


@_SKIP_ELEMENT
def test_DuplicateKeysCustomComparerRunOnce():
    source = [
        Record("Tim", 55),
        Record("Chris", 49),
        Record("Robert", -100),
        Record("Chris", 24),
        Record("Prakash", 9),
        Record("miT", 25),
    ]
    expected = [240, 365, -600, 63]

    assert expected == list(
        flp.it(_run_once(source)).group_by(
            lambda e: e.name,
            element_selector=lambda e: e.score,
            result_selector=lambda k, es: len(k if k is not None else " ") * sum(es),
            comparer=_ANAGRAM_COMPARER,
        )
    )


@_SKIP_ELEMENT
def test_NullComparer():
    source = [
        Record("Tim", 55),
        Record(None, 49),
        Record("Robert", -100),
        Record("Chris", 24),
        Record(None, 9),
        Record("miT", 25),
    ]
    expected = [165, 58, -600, 120, 75]

    assert expected == list(
        flp.it(source).group_by(
            lambda e: e.name,
            element_selector=lambda e: e.score,
            result_selector=lambda k, es: len(k if k is not None else " ") * sum(es),
            comparer=None,
        )
    )


@_SKIP_ELEMENT
def test_NullComparerRunOnce():
    source = [
        Record("Tim", 55),
        Record(None, 49),
        Record("Robert", -100),
        Record("Chris", 24),
        Record(None, 9),
        Record("miT", 25),
    ]
    expected = [165, 58, -600, 120, 75]

    assert expected == list(
        flp.it(_run_once(source)).group_by(
            lambda e: e.name,
            element_selector=lambda e: e.score,
            result_selector=lambda k, es: len(k if k is not None else " ") * sum(es),
            comparer=None,
        )
    )


def test_SingleNonNullElement(flp_type):
    key = ["Tim"]
    source = [Record(key[0], 60)]

    _assert_grouping_correct(key, source, flp_type(source).group_by(lambda e: e.name))


@_SKIP_COMPARER
def test_AllElementsSameKey():
    key = ["Tim", "Tim", "Tim", "Tim"]
    scores = [60, -10, 40, 100]
    source = [Record(k, e) for k, e in zip(key, scores)]

    _assert_grouping_correct(
        key,
        source,
        flp.it(source).group_by(lambda e: e.name, comparer=_ANAGRAM_COMPARER),
        _ANAGRAM_COMPARER,
    )


@_SKIP_ELEMENT
def test_AllElementsDifferentKeyElementSelectorUsed():
    key = ["Tim", "Chris", "Robert", "Prakash"]
    element = [60, -10, 40, 100]
    source = [Record(k, e) for k, e in zip(key, element)]

    _assert_grouping_correct(
        key, element, flp.it(source).group_by(lambda e: e.name, element_selector=lambda e: e.score)
    )


@_SKIP_ELEMENT
def test_SomeDuplicateKeys():
    key = ["Tim", "Tim", "Chris", "Chris", "Robert", "Prakash"]
    element = [55, 25, 49, 24, -100, 9]
    source = [Record(k, e) for k, e in zip(key, element)]

    _assert_grouping_correct(
        key, element, flp.it(source).group_by(lambda e: e.name, element_selector=lambda e: e.score)
    )


@_SKIP_ELEMENT
def test_SomeDuplicateKeysIncludingNulls():
    key = [None, None, "Chris", "Chris", "Prakash", "Prakash"]
    element = [55, 25, 49, 24, 9, 9]
    source = [Record(k, e) for k, e in zip(key, element)]

    _assert_grouping_correct(
        key, element, flp.it(source).group_by(lambda e: e.name, element_selector=lambda e: e.score)
    )


@_SKIP_RESULT
def test_SingleElementResultSelectorUsed():
    key = ["Tim"]
    element = [60]
    expected = [180]
    source = [Record(k, e) for k, e in zip(key, element)]

    assert expected == list(
        flp.it(source).group_by(
            lambda e: e.name,
            result_selector=lambda k, es: len(k if k is not None else " ") * sum(e.score for e in es),
        )
    )


@_SKIP_RESULT
def test_GroupedResultCorrectSize():
    elements = ["q"] * 5
    result = flp.it(elements).group_by(
        lambda e: e, result_selector=lambda e, f: SimpleNamespace(key=e, element=flp.it(f))
    )

    assert result.count() == 1
    grouping = result.first()
    assert grouping.element.count() == 5
    assert grouping.key == "q"
    assert grouping.element.all(lambda e: e == "q")


@_SKIP_ELEMENT
def test_AllElementsDifferentKeyElementSelectorUsedResultSelector():
    key = ["Tim", "Chris", "Robert", "Prakash"]
    element = [60, -10, 40, 100]
    source = [Record(k, e) for k, e in zip(key, element)]
    expected = [180, -50, 240, 700]

    assert expected == list(
        flp.it(source).group_by(
            lambda e: e.name,
            element_selector=lambda e: e.score,
            result_selector=lambda k, es: len(k if k is not None else " ") * sum(es),
        )
    )


@_SKIP_RESULT
def test_AllElementsSameKeyResultSelectorUsed():
    element = [60, -10, 40, 100]
    expected = [570]
    source = [
        Record("Tim", element[0]),
        Record("Tim", element[1]),
        Record("miT", element[2]),
        Record("miT", element[3]),
    ]

    assert expected == list(
        flp.it(source).group_by(
            lambda e: e.name,
            result_selector=lambda k, es: len(k) * sum(e.score for e in es),
            comparer=_ANAGRAM_COMPARER,
        )
    )


@_SKIP_RESULT
def test_NullComparerResultSelectorUsed():
    element = [60, -10, 40, 100]
    source = [
        Record("Tim", element[0]),
        Record("Tim", element[1]),
        Record("miT", element[2]),
        Record("miT", element[3]),
    ]
    expected = [150, 420]

    assert expected == list(
        flp.it(source).group_by(
            lambda e: e.name,
            result_selector=lambda k, es: len(k) * sum(e.score for e in es),
            comparer=None,
        )
    )


def test_GroupingToArray(flp_type):
    source = _records()

    grouped_array = list(flp_type(source).group_by(lambda r: r.name))
    assert len(grouped_array) == 4
    assert list(flp_type(source).group_by(lambda r: r.name)) == grouped_array


@_SKIP_ELEMENT
def test_GroupingWithElementSelectorToArray():
    source = _records()

    grouped_array = list(flp.it(source).group_by(lambda r: r.name, element_selector=lambda e: e.score))
    assert len(grouped_array) == 4
    assert list(
        flp.it(source).group_by(lambda r: r.name, element_selector=lambda e: e.score)
    ) == grouped_array


@_SKIP_RESULT
def test_GroupingWithResultsToArray():
    source = _records()

    grouped_array = [list(e) for e in flp.it(source).group_by(lambda r: r.name, result_selector=lambda r, e: e)]
    assert len(grouped_array) == 4
    assert [list(e) for e in flp.it(source).group_by(lambda r: r.name, result_selector=lambda r, e: e)] == grouped_array


@_SKIP_ELEMENT
def test_GroupingWithElementSelectorAndResultsToArray():
    source = _records()

    def query():
        return flp.it(source).group_by(
            lambda r: r.name, element_selector=lambda e: e, result_selector=lambda r, e: e
        )

    grouped_array = [list(e) for e in query()]
    assert len(grouped_array) == 4
    assert [list(e) for e in query()] == grouped_array


def test_GroupingToList(flp_type):
    source = _records()

    grouped_list = flp_type(source).group_by(lambda r: r.name).to_list()
    assert len(grouped_list) == 4
    assert list(flp_type(source).group_by(lambda r: r.name)) == list(grouped_list)


@_SKIP_ELEMENT
def test_GroupingWithElementSelectorToList():
    source = _records()

    grouped_list = flp.it(source).group_by(lambda r: r.name, element_selector=lambda e: e.score).to_list()
    assert len(grouped_list) == 4
    assert list(
        flp.it(source).group_by(lambda r: r.name, element_selector=lambda e: e.score)
    ) == list(grouped_list)


@_SKIP_RESULT
def test_GroupingWithResultsToList():
    source = _records()

    grouped_list = flp.it(source).group_by(lambda r: r.name, result_selector=lambda r, e: list(e)).to_list()
    assert len(grouped_list) == 4
    assert list(
        flp.it(source).group_by(lambda r: r.name, result_selector=lambda r, e: list(e))
    ) == list(grouped_list)


@_SKIP_ELEMENT
def test_GroupingWithElementSelectorAndResultsToList():
    source = _records()

    def query():
        return flp.it(source).group_by(
            lambda r: r.name, element_selector=lambda e: e, result_selector=lambda r, e: list(e)
        )

    grouped_list = query().to_list()
    assert len(grouped_list) == 4
    assert list(query()) == list(grouped_list)


def test_GroupingCount(flp_type):
    source = _records()

    assert flp_type(source).group_by(lambda r: r.name).count() == 4


@_SKIP_ELEMENT
def test_GroupingWithElementSelectorCount():
    source = _records()

    assert flp.it(source).group_by(lambda r: r.name, element_selector=lambda e: e.score).count() == 4


@_SKIP_RESULT
def test_GroupingWithResultsCount():
    source = _records()

    assert flp.it(source).group_by(lambda r: r.name, result_selector=lambda r, e: e).count() == 4


@_SKIP_ELEMENT
def test_GroupingWithElementSelectorAndResultsCount():
    source = _records()

    assert (
            flp.it(source)
            .group_by(lambda r: r.name, element_selector=lambda e: e, result_selector=lambda r, e: e)
            .count()
            == 4
    )


def test_EmptyGroupingToArray(flp_type):
    assert list(flp_type([]).group_by(lambda i: i)) == []


def test_EmptyGroupingToList(flp_type):
    assert list(flp_type([]).group_by(lambda i: i).to_list()) == []


def test_EmptyGroupingCount(flp_type):
    assert flp_type([]).group_by(lambda i: i).count() == 0


@_SKIP_RESULT
def test_EmptyGroupingWithResultToArray():
    assert list(flp.it([]).group_by(lambda i: i, result_selector=lambda x, y: x + flp.it(y).count())) == []


@_SKIP_RESULT
def test_EmptyGroupingWithResultToList():
    assert list(
        flp.it([]).group_by(lambda i: i, result_selector=lambda x, y: x + flp.it(y).count()).to_list()
    ) == []


@_SKIP_RESULT
def test_EmptyGroupingWithResultCount():
    assert flp.it([]).group_by(lambda i: i, result_selector=lambda x, y: x + flp.it(y).count()).count() == 0


def test_GroupingKeyIsPublic(flp_type):
    # Grouping.Key needs to be public (not explicitly implemented) for the sake of WPF.
    objs = ["Foo", Decimal("1.0"), "Bar", SimpleNamespace(X="X"), Decimal("2.00")]
    group = flp_type(objs).group_by(lambda x: type(x)).first()

    assert isinstance(getattr(type(group), "key", None), property)


_MULTIPLE_ITERATIONS_VARIANTS = [
    "key",
    pytest.param("element_selector", marks=_SKIP_ELEMENT),
    pytest.param("result_selector", marks=_SKIP_RESULT),
    pytest.param("element_selector_and_result_selector", marks=_SKIP_ELEMENT),
]


@pytest.mark.parametrize("variant", _MULTIPLE_ITERATIONS_VARIANTS)
def test_MultipleIterationsOfSameEnumerable(variant):
    source = flp.it(range(0, 10))

    if variant == "key":
        e = source.group_by(lambda i: i)
    elif variant == "element_selector":
        e = source.group_by(lambda i: i, element_selector=lambda i: i)
    elif variant == "result_selector":
        e = source.group_by(lambda i: i, result_selector=lambda i, e: i)
    else:
        e = source.group_by(lambda i: i, element_selector=lambda i: i, result_selector=lambda i, e: i)

    for trial in range(3):
        count = 0
        for _ in e:
            count += 1
        assert count == 10


def test_EnumerateGrouping(flp_type):
    g = flp_type(range(0, 42)).group_by(lambda i: "onegroup").first()
    assert g.key == "onegroup"
    assert g.count() == 42

    for trial in range(3):
        # .NET reuses one enumerator and calls Reset(); Python iterators have no Reset(),
        # so every trial starts a fresh iteration of the same grouping.
        e = iter(g)
        values = set()
        for value in e:
            assert value not in values
            values.add(value)
        assert len(values) == 42
        assert list(range(0, 42)) == sorted(values)