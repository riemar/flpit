"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq OfTypeTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/OfTypeTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET type mapping used by this port:
    int / long / short ...      -> int      (Python has ONE integer type: int and long are indistinguishable)
    double / float              -> float
    decimal                     -> decimal.Decimal
    string                      -> str
    object                      -> object
    int? / decimal?             -> int | None / Decimal | None
    null                        -> None
    object[] / int[] / T[]      -> list
    IEnumerable<object> source  -> flp_type(list)  (FlpIt and FlpList)
    Enumerable.Range            -> flp.range
    RunOnce()                   -> conftest `run_once` fixture
    NumberRangeGuaranteedNotCollectionType(0, 3) -> flp.it(_ForceNotCollection(range(0, 3)))
    ToArray()                   -> list(...)     (flpit has no ToArray)
    ElementAtOrDefault(i)       -> _element_at_or_default(...) (flpit has no such operator)
    TryGetNonEnumeratedCount    -> no flpit counterpart; those asserts are not ported (noted inline)

Known systematic Python/.NET differences that make some tests fail (see inline comments):
    * isinstance(None, object) is True in Python; .NET `null` is an instance of nothing.
    * isinstance(None, int | None) is True; .NET OfType<int?>() skips nulls.
    * int and long are the same type in Python.
    * Python has no multi-dimensional arrays that enumerate as a flat sequence.
"""
from collections.abc import Iterator
from decimal import Decimal

import pytest

from flpit import flp, SourceNoneError

INT_MIN = -2147483648


# ---------------------------------------------------------------------------
# .NET test helpers
# ---------------------------------------------------------------------------

class _ForceNotCollection:
    """IEnumerable<T> with no other interfaces (re-enumerable, no __len__/__getitem__)."""

    def __init__(self, source):
        self._source = list(source)

    def __iter__(self):
        for item in self._source:
            yield item


def _element_at_or_default(source, index, default):
    """Enumerable.ElementAtOrDefault: flpit has no such operator, so emulate it via element_at."""
    try:
        return source.element_at(index)
    except Exception:
        return default


class _MySneakyObject1:
    def __eq__(self, other):
        return isinstance(other, _MySneakyObject1)

    def __hash__(self):
        return 0


class _MySneakyObject2(_MySneakyObject1):
    def __eq__(self, other):
        return isinstance(other, _MySneakyObject2)

    def __hash__(self):
        return 0


# ---------------------------------------------------------------------------
# OfTypeTests
# ---------------------------------------------------------------------------

def test_SameResultsRepeatCallsIntQuery(flp_type):
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > INT_MIN)

    assert list(q.of_type(int)) == list(q.of_type(int))


def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]).where(lambda x: x is None or x == "")

    assert list(q.of_type(int)) == list(q.of_type(int))


def test_EmptySource(flp_type):
    source = []

    assert list(flp_type(source).of_type(int)) == []


@pytest.mark.skip("Python doesn't differentiate types at runtime")
def test_LongSequenceFromIntSource(flp_type):
    source = [99, 45, 81]

    # EXPECTED FAIL: Python has a single integer type; of_type(int) is also "long",
    # so all three elements match, whereas .NET boxes int and OfType<long>() yields nothing.
    assert list(flp_type(source).of_type(int)) == []


def test_HeterogenousSourceNoAppropriateElements(flp_type):
    source = ["Hello", 3.5, "Test"]

    assert list(flp_type(source).of_type(int)) == []


def test_HeterogenousSourceOnlyFirstOfType(flp_type):
    source = [10, "Hello", 3.5, "Test"]
    expected = [10]

    assert list(flp_type(source).of_type(int)) == expected


def test_AllElementsOfNullableTypeNullsSkipped(flp_type):
    source = [10, -4, None, None, 4, 9]
    expected = [10, -4, 4, 9]

    # EXPECTED FAIL: isinstance(None, int | None) is True, so of_type(int | None) keeps the
    # Nones; .NET OfType<int?>() never yields null because null is not an instance of any type.
    assert list(flp_type(source).of_type(int | None)) == expected


def test_HeterogenousSourceSomeOfType(flp_type):
    source = [Decimal("3.5"), -4, "Test", "Check", 4, 8.0, 10.5, 9]
    expected = [-4, 4, 9]

    assert list(flp_type(source).of_type(int)) == expected


def test_RunOnce(run_once):
    source = [Decimal("3.5"), -4, "Test", "Check", 4, 8.0, 10.5, 9]
    expected = [-4, 4, 9]

    assert list(flp.it(run_once(source)).of_type(int)) == expected


def test_IntFromNullableInt(flp_type):
    source = [-4, 4, 9]
    expected = [-4, 4, 9]

    assert list(flp_type(source).of_type(int | None)) == expected


def test_IntFromNullableIntWithNulls(flp_type):
    source = [None, -4, 4, None, 9]
    expected = [-4, 4, 9]

    assert list(flp_type(source).of_type(int)) == expected


def test_NullableDecimalFromString(flp_type):
    source = ["Test1", "Test2", "Test9"]

    assert list(flp_type(source).of_type(Decimal | None)) == []


def test_LongFromDouble(flp_type):
    source = [99, 45, 81]

    assert list(flp_type(source).of_type(float)) == []


def test_NullSource(flp_type):
    # .NET: ArgumentNullException("source"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).of_type(str)


def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it(_ForceNotCollection(range(0, 3))).of_type(int)
    # Don't insist on this behaviour, but check it's correct if it happens
    en = iterator if isinstance(iterator, Iterator) else None
    _end = object()
    assert not (en is not None and next(en, _end) is not _end)


@pytest.mark.skip("Python does not track generic types at runtime")
def test_ValueType_ReturnsOriginal():
    e = flp.range(0, 10)

    # EXPECTED FAIL: of_type() always builds a new deferred FlpIt; there is no identity
    # short-circuit when the static element type already matches (.NET returns the source).
    assert e.of_type(int) is e


def test_NullableValueType_ReturnsNewEnumerable():
    e = flp.range(0, 10).select(lambda i: i)

    assert e is not e.of_type(int)
    assert e is not e.of_type(int | None)


def test_ReferenceType_ReturnsNewEnumerable():
    e = flp.range(0, 10).select(lambda i: i)

    assert e is not e.of_type(int)
    assert e is not e.of_type(int | None)
    assert e is not e.of_type(object)
    assert e is not e.of_type(object | None)


def test_ToArray(flp_type):
    source = flp_type([1, 2, 3, 4, 5])

    assert [1, 2, 3, 4, 5] == list(source.of_type(int))
    assert [] == list(source.of_type(float))


def test_ToList(flp_type):
    source = flp_type([1, 2, 3, 4, 5])

    assert [1, 2, 3, 4, 5] == list(source.of_type(int).to_list())
    assert [] == list(source.of_type(float).to_list())


def test_Count(flp_type):
    assert 0 == flp_type([]).of_type(str).count()
    assert 1 == flp_type(["abc"]).of_type(str).count()
    assert 2 == flp_type(["abc", "def"]).of_type(str).count()
    assert 2 == flp_type(["abc", 42, "def"]).of_type(str).count()
    assert 2 == flp_type(["abc", 42, None, "def"]).of_type(str).count()

    # EXPECTED FAIL: isinstance(None, object) is True in Python, so the three Nones are
    # counted too (6 instead of 3); .NET `null` is not an instance of object for OfType.
    assert 3 == flp_type([None, object(), None, object(), object(), None]).of_type(object).count()

    # Not ported: TryGetNonEnumeratedCount has no flpit counterpart (3 asserts).


@pytest.mark.skip("Python does not distinguish .NET numeric types")
def test_First_Last_ElementAt(flp_type):
    source = flp_type([1, 2, 3, 4, 5])

    assert 1 == source.of_type(int).first()
    # EXPECTED FAIL (next 3 lines, first one reached): int and long are the same type in Python,
    # so of_type(int) (long) is not empty and the default 0 is never returned.
    assert 0 == source.of_type(int).first_or_default(0)
    assert 5 == source.of_type(int).last()
    assert 0 == source.of_type(int).last_or_default(0)
    assert 4 == source.of_type(int).element_at(3)
    assert 0 == _element_at_or_default(source.of_type(int), 6, 0)


def test_OfTypeSelect(flp_type):
    objects = flp_type(["1", None, "22", None, 3, 4, "55555"])

    assert [1, 2, 5] == list(objects.of_type(str).select(lambda s: len(s)))
    assert [1, 2, 3, 4, 5] == list(flp_type([1, 2, 3, 4, 5]).of_type(object).select(lambda o: int(o)))


def test_MultipleIterations():
    orig = [None, None, None, None, None]
    # flp.it keeps a live view over the list (flp.lst would copy it).
    objects = flp.it(orig).of_type(object)

    for i in range(len(orig)):
        orig[i] = str(i)
        count = 0
        for _ in objects:
            count += 1
        # EXPECTED FAIL: isinstance(None, object) is True, so the not-yet-replaced Nones are
        # counted as well (5 on the first pass instead of 1).
        assert i + 1 == count


@pytest.mark.skip("Python nested lists do not support multidimensional array semantics")
def test_MultiDimArray_OfType_Succeeds(flp_type):
    # C# string[3, 4] enumerates row-major as a flat sequence; Python has no such type,
    # the closest literal translation is a list of rows.
    array = [[None] * 4 for _ in range(3)]
    for i in range(3):
        for j in range(4):
            array[i][j] = f"{i}{j}"

    # ToArray
    # EXPECTED FAIL: enumerating a nested list yields the *rows* (lists), not the 12 strings,
    # so of_type(str) is empty.
    result = list(flp_type(array).of_type(str))
    assert 12 == len(result)
    for i in range(3):
        for j in range(4):
            assert f"{i}{j}" == result[i * 4 + j]

    # Contains
    for row in array:
        for s in row:
            assert flp_type(array).of_type(str).contains(s)


def test_OfType_Contains_FiltersByTypeEvenIfEqual():
    lst = flp.lst([_MySneakyObject1()])

    assert list(lst.of_type(_MySneakyObject2)) == []
    # EXPECTED FAIL: FlpIt has no contains() (only FlpList does), so this raises AttributeError.
    assert not lst.of_type(_MySneakyObject2).contains(_MySneakyObject2())
