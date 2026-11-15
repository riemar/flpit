"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq IndexTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/IndexTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Migration rule: faithful. Every .NET test is ported one-to-one under its original name
(prefixed with `test_`). Ported tests are allowed to fail; a failing test carries a
`# EXPECTED FAIL:` comment explaining why it is believed to fail.

.NET overloads covered by IndexTests (introduced in .NET 9):
    Index(source)                        -> source.index()               (yields IndexTuple(index, item))

.NET helper / language mapping:
    (int Index, TSource Item)            -> IndexTuple(index, item), a NamedTuple (so it compares equal to
                                            a plain ``(index, item)`` tuple and unpacks like one).
    Assert.Empty(...)                    -> assert list(...) == []
    AssertExtensions.Throws<ArgumentNullException>("source", ...) -> pytest.raises(SourceNoneError):
                                            the FlpIt/FlpList constructor rejects None before index()
                                            can be called.
    TestEnvironment.IsStressModeEnabled  -> the two stress-mode tests enumerate 2^31 elements; ported
                                            as skipped tests with the reason.
"""
import pytest

from flpit import IndexTuple, SourceNoneError, flp


def test_Empty(flp_type):
    assert list(flp_type([]).index()) == []


def test_Index_SourceIsNull_ArgumentNullExceptionThrown(flp_type):
    # .NET: ArgumentNullException("source"); flp: the constructor rejects None.
    with pytest.raises(SourceNoneError):
        flp_type(None).index()


@pytest.mark.skip("Python int can't overflow")
def test_LargeEnumerable_ThrowsOverflowException():
    # .NET (stress mode only): Index() throws OverflowException after int.MaxValue elements.
    pass


@pytest.mark.skip("Stress mode only: enumerates 2^31 elements")
def test_LargeEnumerable():
    # .NET (stress mode only): the index of the last of int.MaxValue + 1 elements is int.MaxValue.
    pass


def test_Index(flp_type):
    source = flp_type(["a", "b"])

    actual = list(source.index())
    expected = [(0, "a"), (1, "b")]

    assert expected == actual
    assert [IndexTuple(0, "a"), IndexTuple(1, "b")] == actual
    assert [(t.index, t.item) for t in actual] == expected
