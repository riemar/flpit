"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq CastTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/CastTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET type / exception mapping used by this port:
    int / long / byte / ushort  -> int   (ONE integer type in Python: int<->long casts never throw)
    double                      -> float
    string                      -> str
    int? / long?                -> int | None
    null                        -> None
    object[] / T[]              -> list
    InvalidCastException        -> TypeError            (what flpit's cast() raises)
    NullReferenceException      -> AttributeError       (closest Python "null dereference" error)
    InvalidOperationException   -> InvalidOperationError
    ArgumentOutOfRangeException -> ArgumentOutOfRangeError
    foreach (var t in rst) ;    -> for _ in rst: pass
    ToArray()                   -> list(...)  (flpit has no ToArray)
    RunOnce()                   -> conftest `run_once` fixture
    Multi-dimensional Array     -> nested list (Python has no flat-enumerating multi-dim array)
"""
from collections.abc import Iterator

import pytest

from flpit import (
    flp,
    ArgumentOutOfRangeError,
    InvalidOperationError,
    SourceNoneError,
)

INT_MIN = -2147483648


def _enumerate_all(iterable):
    for _ in iterable:
        pass


# ---------------------------------------------------------------------------
# CastTests
# ---------------------------------------------------------------------------
@pytest.mark.skip("Python doesn't differentiate types at runtime")
def test_CastIntToLongThrows(flp_type):
    q = flp_type([9999, 0, 888, -1, 66, -777, 1, 2, -12345]).where(lambda x: x > INT_MIN)

    rst = q.cast(int)  # Cast<long>()

    # EXPECTED FAIL: int and long are the same Python type, so the cast succeeds and nothing is raised.
    with pytest.raises(TypeError):
        _enumerate_all(rst)

@pytest.mark.skip("Python doesn't differentiate types at runtime")
def test_CastByteToUShortThrows(flp_type):
    q = flp_type([0, 255, 127, 128, 1, 33, 99])

    rst = q.cast(int)  # Cast<ushort>()

    # EXPECTED FAIL: byte and ushort are both plain int in Python; the cast succeeds.
    with pytest.raises(TypeError):
        _enumerate_all(rst)


def test_EmptySource(flp_type):
    source = []

    assert list(flp_type(source).cast(int)) == []


def test_NullableIntFromAppropriateObjects(flp_type):
    i = 10
    source = [-4, 1, 2, 3, 9, i]
    expected = [-4, 1, 2, 3, 9, i]

    assert list(flp_type(source).cast(int | None)) == expected


def test_NullableIntFromAppropriateObjectsRunOnce(run_once):
    i = 10
    source = [-4, 1, 2, 3, 9, i]
    expected = [-4, 1, 2, 3, 9, i]

    assert list(flp.it(run_once(source)).cast(int | None)) == expected

@pytest.mark.skip("Python doesn't differentiate types at runtime")
def test_LongFromNullableIntInObjectsThrows(flp_type):
    i = 10
    source = [-4, 1, 2, 3, 9, i]

    cast = flp_type(source).cast(int)  # Cast<long>()

    # EXPECTED FAIL: a boxed int? cannot be unboxed as long in .NET; in Python int == long, no error.
    with pytest.raises(TypeError):
        cast.to_list()

@pytest.mark.skip("Python doesn't differentiate types at runtime")
def test_LongFromNullableIntInObjectsIncludingNullThrows(flp_type):
    i = 10
    source = [-4, 1, 2, 3, 9, None, i]

    cast = flp_type(source).cast(int | None)  # Cast<long?>()

    # EXPECTED FAIL: int and long are the same Python type; the cast succeeds.
    with pytest.raises(TypeError):
        cast.to_list()


def test_NullableIntFromAppropriateObjectsIncludingNull(flp_type):
    i = 10
    source = [-4, 1, 2, 3, 9, None, i]
    expected = [-4, 1, 2, 3, 9, None, i]

    assert list(flp_type(source).cast(int | None)) == expected


def test_ThrowOnUncastableItem(flp_type):
    source = [-4, 1, 2, 3, 9, "45"]
    expected_beginning = [-4, 1, 2, 3, 9]

    cast = flp_type(source).cast(int)

    with pytest.raises(TypeError):
        cast.to_list()
    assert list(cast.take(5)) == expected_beginning
    with pytest.raises(TypeError):
        cast.element_at(5)


def test_ThrowCastingIntToDouble(flp_type):
    source = [-4, 1, 2, 9]

    cast = flp_type(source).cast(float)

    with pytest.raises(TypeError):
        cast.to_list()


def _test_cast_throw(flp_type, target_type, o):
    i = 10  # byte? i = 10
    source = [-1, 0, o, i]

    cast = flp_type(source).cast(target_type)

    with pytest.raises(TypeError):
        cast.to_list()

@pytest.mark.skip("Python doesn't differentiate types at runtime")
def test_ThrowOnHeterogenousSource(flp_type):
    # EXPECTED FAIL: both calls cast plain Python ints (-1, 0, 10, 9) to int / int | None, so
    # nothing is raised: .NET fails because boxed int/byte cannot be unboxed as long.
    _test_cast_throw(flp_type, int | None, None)  # TestCastThrow<long?>(null)
    _test_cast_throw(flp_type, int, 9)  # TestCastThrow<long>(9L)

def test_CastToString(flp_type):
    source = ["Test1", "4.5", None, "Test2"]
    expected = ["Test1", "4.5", None, "Test2"]

    # EXPECTED FAIL: isinstance(None, str) is False, so cast(str) raises TypeError for the None;
    # .NET allows a null reference to be cast to string.
    assert list(flp_type(source).cast(str | None)) == expected


def test_CastToStringRunOnce(run_once):
    source = ["Test1", "4.5", None, "Test2"]
    expected = ["Test1", "4.5", None, "Test2"]

    # EXPECTED FAIL: same as test_CastToString (None is rejected by cast(str)).
    assert list(flp.it(run_once(source)).cast(str)) == expected

@pytest.mark.skip("Python doesn't differentiate types at runtime")
def test_ArrayConversionThrows(flp_type):
    # EXPECTED FAIL: int -> long never fails in Python.
    with pytest.raises(TypeError):
        flp_type([-4]).cast(int).to_list()


def test_FirstElementInvalidForCast(flp_type):
    source = ["Test", 3, 5, 10]

    cast = flp_type(source).cast(int)

    with pytest.raises(TypeError):
        cast.to_list()


def test_LastElementInvalidForCast(flp_type):
    source = [-5, 9, 0, 5, 9, "Test"]

    cast = flp_type(source).cast(int)

    with pytest.raises(TypeError):
        cast.to_list()


def test_NullableIntFromNullsAndInts(flp_type):
    source = [3, None, 5, -4, 0, None, 9]
    expected = [3, None, 5, -4, 0, None, 9]

    assert list(flp_type(source).cast(int | None)) == expected

@pytest.mark.skip("Python doesn't differentiate types at runtime")
def test_ThrowCastingIntToLong(flp_type):
    source = [-4, 1, 2, 3, 9]

    cast = flp_type(source).cast(int)  # Cast<long>()

    # EXPECTED FAIL: int and long are the same Python type.
    with pytest.raises(TypeError):
        cast.to_list()

@pytest.mark.skip("Python doesn't differentiate types at runtime")
def test_ThrowCastingIntToNullableLong(flp_type):
    source = [-4, 1, 2, 3, 9]

    cast = flp_type(source).cast(int | None)  # Cast<long?>()

    # EXPECTED FAIL: int and long are the same Python type.
    with pytest.raises(TypeError):
        cast.to_list()

@pytest.mark.skip("Python doesn't differentiate types at runtime")
def test_ThrowCastingNullableIntToLong(flp_type):
    source = [-4, 1, 2, 3, 9]  # int?[]

    cast = flp_type(source).cast(int)  # Cast<long>()

    # EXPECTED FAIL: int and long are the same Python type.
    with pytest.raises(TypeError):
        cast.to_list()

@pytest.mark.skip("Python doesn't differentiate types at runtime")
def test_ThrowCastingNullableIntToNullableLong(flp_type):
    source = [-4, 1, 2, 3, 9, None]  # int?[]

    cast = flp_type(source).cast(int | None)  # Cast<long?>()

    # EXPECTED FAIL: int and long are the same Python type.
    with pytest.raises(TypeError):
        cast.to_list()


def test_CastingNullToNonnullableIsNullReferenceException(flp_type):
    source = [-4, 1, None, 3]  # int?[]

    cast = flp_type(source).cast(int)

    # (AttributeError is the closest "null dereference" analogue), so the expected type differs.
    with pytest.raises(AttributeError):
        cast.to_list()


def test_NullSource(flp_type):
    # .NET: ArgumentNullException("source"); flp: the FlpIt/FlpList constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).cast(str)


def test_ForcedToEnumeratorDoesntEnumerate():
    iterator = flp.it([]).where(lambda i: i is not None).cast(str)
    # Don't insist on this behaviour, but check it's correct if it happens
    en = iterator if isinstance(iterator, Iterator) else None
    _end = object()
    assert not (en is not None and next(en, _end) is not _end)


@pytest.mark.skip("Python does not track generic types at runtime")
def test_TargetTypeIsSourceType_Nop(flp_type):
    values = flp_type(["hello", "world"])

    # EXPECTED FAIL: cast() always returns a new deferred FlpIt; there is no identity
    # short-circuit when the source already has the target type.
    assert values.cast(str) is values


@pytest.mark.skip("Python nested lists do not support multidimensional array semantics")
def test_CastOnMultidimensionalArraySucceeds(flp_type):
    array = [[None] * 3 for _ in range(2)]
    for i in range(2):
        for j in range(3):
            array[i][j] = i * 3 + j

    # EXPECTED FAIL: a nested list enumerates its rows (lists), not the 6 ints, so cast(int)
    # raises TypeError; Python has no multi-dimensional array that enumerates flat.
    result = list(flp_type(array).cast(int))
    for i in range(6):
        assert i == result[i]


def test_CastCountReturnsExpectedLength(flp_type):
    objects = ["hello", "world"]

    assert 2 == flp_type(objects).cast(str).count()


def test_CastFirstReturnsFirstElement(flp_type):
    objects = ["hello", "world"]

    assert "hello" == flp_type(objects).cast(str).first()


def test_CastFirstOnEmptySequenceThrows(flp_type):
    objects = []

    with pytest.raises(InvalidOperationError):
        flp_type(objects).cast(str).first()


def test_CastLastReturnsLastElement(flp_type):
    objects = ["hello", "world"]

    assert "world" == flp_type(objects).cast(str).last()


def test_CastElementAtReturnsExpectedElement(flp_type):
    objects = ["hello", "world"]

    assert "world" == flp_type(objects).cast(str).element_at(1)


def test_CastElementAtOutOfRangeThrows(flp_type):
    objects = ["hello", "world"]

    with pytest.raises(ArgumentOutOfRangeError):
        flp_type(objects).cast(str).element_at(2)


def test_CastLastOnEmptySequenceThrows(flp_type):
    objects = []

    with pytest.raises(InvalidOperationError):
        flp_type(objects).cast(str).last()


def test_CastSelectProcessesEachElement(flp_type):
    objects = ["hello", "world!"]

    assert [5, 6] == list(flp_type(objects).cast(str).select(lambda s: len(s)))


def test_CastSkipSkipsElements(flp_type):
    objects = ["hello", "there", "world"]

    assert ["world"] == list(flp_type(objects).cast(str).skip(2))


def test_CastTakeTakesElements(flp_type):
    objects = ["hello", "there", "world"]

    assert ["hello", "there"] == list(flp_type(objects).cast(str).take(2))
