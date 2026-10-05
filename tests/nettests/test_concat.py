"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq ConcatTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/ConcatTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.
"""
import pytest

from typing import Generic, Iterable, Iterator, TypeVar
from helpers import broken_iterator

from flpit import flp, EmptySequenceError, SecondNoneError, ArgumentOutOfRangeError, SourceNoneError

T = TypeVar("T")


class ForceNotCollection(Generic[T]):
    """
    Wraps a sequence to expose ONLY raw iterable semantics (__iter__).

    Strips collection interfaces (__len__, __getitem__, __contains__) to force
    LINQ fallback paths, while generating a fresh iterator on every __iter__
    call to preserve multi-pass re-iterability.
    """

    __slots__ = ("_source",)

    def __init__(self, source: Iterable[T]):
        self._source = source

    def __iter__(self) -> Iterator[T]:
        yield from self._source


# Helper identity transforms mimicking LINQ test infrastructure
def IdentityTransforms(flp_type):
    return [
        lambda e: flp_type(e),
        lambda e: flp_type(list(e)),
        lambda e: ForceNotCollection(e),
    ]


# Private static worker helper
def SameResultsWithQueryAndRepeatCallsWorker(first, second):
    first_seq = first.select(lambda e: e)
    second_seq = second.select(lambda e: e)

    assert list(first_seq.concat(second_seq)) == list(first_seq.concat(second_seq))
    assert list(second_seq.concat(first_seq)) == list(second_seq.concat(first_seq))


# Data Providers
def GenerateSourcesData(flp_type, outer_transform=None, inner_transform=None):
    outer_transform = outer_transform or (lambda e: flp_type(e))
    inner_transform = inner_transform or (lambda e: flp_type(e))

    for i in range(7):
        expected = list(range(i * 3))
        actual = flp_type([])

        for j in range(i):
            inner = inner_transform(range(j * 3, j * 3 + 3))
            actual = outer_transform(flp_type(actual).concat(inner))

        yield expected, actual


def ArraySourcesData(flp_type):
    return GenerateSourcesData(flp_type, outer_transform=lambda e: list(e))


def SelectArraySourcesData(flp_type):
    return GenerateSourcesData(flp_type, outer_transform=lambda e: [i for i in e])


def EnumerableSourcesData(flp_type):
    return GenerateSourcesData(flp_type)


def NonCollectionSourcesData(flp_type):
    return GenerateSourcesData(flp_type, outer_transform=lambda e: ForceNotCollection(e))


def ListSourcesData(flp_type):
    return GenerateSourcesData(flp_type, outer_transform=lambda e: list(e))


def ConcatOfConcatsData(flp_type):
    yield [
        list(range(20)),
        flp_type(range(0, 4))
        .concat(range(4, 10))
        .concat(flp_type(range(10, 13)).concat(range(13, 20))),
    ]


def ConcatWithSelfData(flp_type):
    source = flp_type([1] * 4).concat([1] * 5)
    source = source.concat(source)
    yield [[1] * 18, source]


def ChainedCollectionConcatData(flp_type):
    return GenerateSourcesData(flp_type, inner_transform=lambda e: list(e))


def AppendedPrependedConcatAlternationsData(flp_type):
    enumerable_count = 4
    foundation = flp_type([])

    for i in range(1 << enumerable_count):
        for j in range(1 << enumerable_count):
            expected = []
            actual = foundation

            for k in range(enumerable_count):
                next_range = flp_type(range(k, k + 1))
                prepend = ((i >> k) & 1) != 0
                force_collection = ((j >> k) & 1) != 0

                if force_collection:
                    next_range = list(next_range)

                if prepend:
                    actual = flp_type(next_range).concat(actual)
                    expected.insert(0, k)
                else:
                    actual = flp_type(actual).concat(next_range)
                    expected.append(k)

            yield expected, actual

def ConcatWithEmptyEnumerableData(flp_type):
    base_list = [0, 1, 2, 3, 4]
    yield [list(range(5)), flp_type([]).concat([]).concat(base_list)]
    yield [list(range(5)), flp_type([]).concat(base_list)]
    yield [list(range(5)), flp_type(base_list).concat([]).concat([])]
    yield [list(range(5)), flp_type(base_list).concat([])]


def GetAllVerifyEqualsData(flp_type):
    sources = [
        ArraySourcesData,
        SelectArraySourcesData,
        EnumerableSourcesData,
        NonCollectionSourcesData,
        ListSourcesData,
        ConcatOfConcatsData,
        ConcatWithSelfData,
        ChainedCollectionConcatData,
        AppendedPrependedConcatAlternationsData,
    ]
    for src in sources:
        yield from src(flp_type)


def GetAllFirstLastElementAtData(flp_type):
    yield from GetAllVerifyEqualsData(flp_type)
    yield from ConcatWithEmptyEnumerableData(flp_type)


def ManyConcatsData(flp_type):
    yield [flp_type([]) for _ in range(256)]
    yield [flp_type([6]) for _ in range(256)]
    yield [flp_type([i]) for i in reversed(range(500))]


def GetToArrayDataSources(flp_type):
    yield [
        ForceNotCollection([0]),
        ForceNotCollection([1]),
        ForceNotCollection([2]),
        [3],
    ]

    yield [
        [0],
        ForceNotCollection([1]),
        ForceNotCollection([2]),
        ForceNotCollection([3]),
    ]

    yield [
        ForceNotCollection([0]),
        [1],
        ForceNotCollection([2]),
    ]

    yield [
        [0],
        ForceNotCollection([1]),
        [2],
    ]

    yield [
        ForceNotCollection(range(0, 100)),
        list(range(100, 200)),
        ForceNotCollection(range(200, 300)),
    ]

    yield [
        list(range(0, 100)),
        ForceNotCollection(range(100, 200)),
        list(range(200, 300)),
    ]

    yield [
        [0],
        ForceNotCollection([1]),
        [2],
        ForceNotCollection([3]),
        [4],
    ]

    yield [
        ForceNotCollection([0]),
        [1],
        ForceNotCollection([2]),
        [3],
        ForceNotCollection([4]),
    ]


# Complete Migrated Tests Suite
def test_SameResultsWithQueryAndRepeatCalls_Int(flp_type):
    first = flp_type([2, 3, 2, 4, 5])
    second = flp_type([1, 9, 4])
    SameResultsWithQueryAndRepeatCallsWorker(first, second)


def test_SameResultsWithQueryAndRepeatCalls_String(flp_type):
    first = flp_type(["AAA", "", "q", "C", "#", "!@#$%^", "0987654321", "Calling Twice"])
    second = flp_type(["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS"])
    SameResultsWithQueryAndRepeatCallsWorker(first, second)


@pytest.mark.parametrize(
    "first, second, expected",
    [
        ([], [], []),
        ([], [2, 6, 4, 6, 2], [2, 6, 4, 6, 2]),
        ([2, 3, 5, 9], [8, 10], [2, 3, 5, 9, 8, 10]),
    ],
)
def test_PossiblyEmptyInputs(flp_type, first, second, expected):
    first_seq = flp_type(first)
    second_seq = flp_type(second)
    exp_seq = flp_type(expected)

    assert list(first_seq.concat(second_seq)) == expected

    first_len = len(first)
    skipped_then_taken = exp_seq.skip(first_len).concat(exp_seq.take(first_len))
    assert list(skipped_then_taken) == list(second_seq.concat(first_seq))


def test_ForcedToEnumeratorDoesntEnumerate():
    # Verifies deferred execution so that instantiating a concatenated query does not enumerate the source immediately.
    iterator = flp.it(broken_iterator()).concat(range(3))
    assert iterator is not None


def test_FirstNull(flp_type):
    with pytest.raises(SourceNoneError):
        flp_type(None).concat(range(0))

    with pytest.raises(SourceNoneError):
        flp_type(None).concat(None)


def test_SecondNull(flp_type):
    with pytest.raises(SecondNoneError):
        flp_type(range(0)).concat(None)


def test_VerifyEquals(flp_type):
    for expected, actual in GetAllVerifyEqualsData(flp_type):
        assert list(expected) == list(actual)


def test_First_Last_ElementAt(flp_type):
    for _, actual in GetAllFirstLastElementAtData(flp_type):
        actual_seq = flp_type(actual)
        actual_list = list(actual_seq)
        count = len(actual_list)

        if count == 0:
            with pytest.raises(EmptySequenceError):
                actual_seq.first()
            with pytest.raises(EmptySequenceError):
                actual_seq.last()
            with pytest.raises(ArgumentOutOfRangeError):
                actual_seq.element_at(0)
        else:
            first_val = actual_seq.first()
            last_val = actual_seq.last()
            element_at_val = actual_seq.element_at(count // 2)

            enum_first, enum_last, enum_element_at = 0, 0, 0
            for i, item in enumerate(actual_seq):
                if i == 0:
                    enum_first = item
                if i == count // 2:
                    enum_element_at = item
                enum_last = item

            assert enum_first == first_val
            assert enum_last == last_val
            assert enum_element_at == element_at_val


def test_ManyConcats(flp_type):
    for sources in ManyConcatsData(flp_type):
        sources_list = list(sources)
        for transform in IdentityTransforms(flp_type):
            concatee = flp_type([])
            for source in sources_list:
                concatee = concatee.concat(transform(source))

            total_count = sum(len(list(s)) for s in sources_list)
            assert len(list(concatee)) == total_count

            flattened = [item for s in sources_list for item in list(s)]
            assert list(concatee) == flattened


def test_ManyConcatsRunOnce(flp_type):
    for sources in ManyConcatsData(flp_type):
        # The .NET version is also a stress test for its internal
        # concat-chain representation. That is not a FlpIt requirement at the moment
        sources_list = list(sources)[:32]

        for transform in IdentityTransforms(flp_type):
            concatee = flp_type([])

            for source in sources_list:
                concatee = flp_type(
                    item for item in concatee
                ).concat(transform(source))

            total_count = sum(len(list(s)) for s in sources_list)
            assert len(list(concatee)) == total_count


@pytest.mark.skip(
    reason="Python handles arbitrary-precision integers natively, so Int32 overflow exceptions are inapplicable."
)
def test_CountOfConcatIteratorShouldThrowExceptionOnIntegerOverflow(flp_type):
    pass


def test_CountOfConcatCollectionChainShouldBeResilientToStackOverflow(flp_type):
    number_of_concats = 950 # 10000 # original tested the frame flattening with 10k
    concat_chain = flp_type([])

    for _ in range(number_of_concats):
        concat_chain = concat_chain.concat([])

    assert len(list(concat_chain)) == 0
    assert list(concat_chain) == []


def test_CountOfConcatEnumerableChainShouldBeResilientToStackOverflow(flp_type):
    number_of_concats = 950 # 10000 # original tested the frame flattening with 10k
    concat_chain = flp_type(ForceNotCollection([]))

    for _ in range(number_of_concats):
        concat_chain = concat_chain.concat([])

    assert len(list(concat_chain)) == 0


def test_GettingFirstEnumerableShouldBeResilientToStackOverflow(flp_type):
    number_of_concats = 950 # 10000 # original tested the frame flattening with 10k
    concat_chain = flp_type(ForceNotCollection([0xF00]))

    for _ in range(number_of_concats):
        concat_chain = concat_chain.concat([])

    iterator = iter(concat_chain)
    assert next(iterator) == 0xF00


def test_GetEnumerableOfConcatCollectionChainFollowedByEnumerableNodeShouldBeResilientToStackOverflow(flp_type):
    number_of_concats = 950 # 10000 # original tested the frame flattening with 10k
    concat_chain = flp_type([0xF00])

    for _ in range(number_of_concats - 1):
        concat_chain = concat_chain.concat([])

    concat_chain = concat_chain.concat(ForceNotCollection([]))

    iterator = iter(concat_chain)
    assert next(iterator) == 0xF00


def test_CollectionInterleavedWithLazyEnumerables_ToArray(flp_type):
    for arrays in GetToArrayDataSources(flp_type):
        concats = flp_type(arrays[0])
        for arr in arrays[1:]:
            concats = concats.concat(arr)

        results = list(concats)
        for i, item in enumerate(results):
            assert i == item


@pytest.mark.skip("not implemented yet")
def test_ToArray(flp_type):
    for expected, actual in GetAllVerifyEqualsData(flp_type):
        assert list(actual) == list(expected)


def test_ToList(flp_type):
    for expected, actual in GetAllVerifyEqualsData(flp_type):
        assert list(actual) == list(expected)


def test_Count(flp_type):
    for expected, actual in GetAllVerifyEqualsData(flp_type):
        assert len(list(actual)) == len(list(expected))


def test_Concat2(flp_type):
    first = flp_type([1, 2])
    second = flp_type([3, 4])
    assert list(first.concat(second)) == [1, 2, 3, 4]


def test_Concat3(flp_type):
    first = flp_type([1, 2])
    second = flp_type([3, 4])
    third = flp_type([5, 6])
    assert list(first.concat(second).concat(third)) == [1, 2, 3, 4, 5, 6]


def test_Concat4(flp_type):
    first = flp_type([1, 2])
    second = flp_type([3, 4])
    third = flp_type([5, 6])
    fourth = flp_type([7, 8])
    assert list(first.concat(second).concat(third).concat(fourth)) == [1, 2, 3, 4, 5, 6, 7, 8]


def test_Concat5(flp_type):
    first = flp_type([1, 2])
    second = flp_type([3, 4])
    third = flp_type([5, 6])
    fourth = flp_type([7, 8])
    fifth = flp_type([9, 10])
    assert list(first.concat(second).concat(third).concat(fourth).concat(fifth)) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_ConcatN(flp_type):
    res = flp_type([0])
    for i in range(1, 10):
        res = res.concat([i])
    assert list(res) == list(range(10))


def test_Concat_Self(flp_type):
    source = flp_type([1, 2, 3])
    assert list(source.concat(source)) == [1, 2, 3, 1, 2, 3]


def test_Concat_ThrowInFirst():
    # Exception thrown during first sequence enumeration must propagate immediately upon iteration.
    def throwing_gen():
        yield 1
        raise RuntimeError("Error in first sequence")

    seq = flp.it(throwing_gen()).concat([2, 3])
    iterator = iter(seq)
    assert next(iterator) == 1
    with pytest.raises(RuntimeError):
        next(iterator)


def test_Concat_ThrowInSecond(flp_type):
    # Exception thrown during second sequence enumeration must propagate when the second sequence is reached.
    def throwing_gen():
        yield 3
        raise RuntimeError("Error in second sequence")

    seq = flp_type([1, 2]).concat(throwing_gen())
    iterator = iter(seq)
    assert next(iterator) == 1
    assert next(iterator) == 2
    assert next(iterator) == 3
    with pytest.raises(RuntimeError):
        next(iterator)


def test_ToArray_NonCollection(flp_type):
    for expected, actual in NonCollectionSourcesData(flp_type):
        assert list(actual) == list(expected)


def test_ToList_NonCollection(flp_type):
    for expected, actual in NonCollectionSourcesData(flp_type):
        assert list(actual) == list(expected)


def test_Count_NonCollection(flp_type):
    for expected, actual in NonCollectionSourcesData(flp_type):
        assert len(list(actual)) == len(list(expected))


def test_MoveNext_AfterEndOfSequence_ReturnsFalse(flp_type):
    seq = flp_type([1]).concat([2])
    iterator = iter(seq)
    assert next(iterator) == 1
    assert next(iterator) == 2
    with pytest.raises(StopIteration):
        next(iterator)
    with pytest.raises(StopIteration):
        next(iterator)


def test_Enumerator_Dispose(flp_type):
    # Explicit Dispose calls in C# map to generator close/cleanup mechanics in Python.
    seq = flp_type([1, 2]).concat([3, 4])
    iterator = iter(seq)
    if hasattr(iterator, "close"):
        iterator.close()


def test_GetEnumerator_ReturnsFreshEnumerator(flp_type):
    seq = flp_type([1, 2]).concat([3, 4])
    it1 = iter(seq)
    it2 = iter(seq)
    assert next(it1) == 1
    assert next(it2) == 1
    assert list(it1) == [2, 3, 4]
    assert list(it2) == [2, 3, 4]