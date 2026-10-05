import pytest

from conftest import create_sources
from flpit import flp, ArgumentOutOfRangeError

def assert_equal(expected, actual):
    assert list(actual) == list(expected)


def assert_empty(actual):
    assert list(actual) == []


def test_SkipSome(flp_type):
    assert_equal(range(10, 20), flp_type(range(0, 20)).skip(10))


def test_SkipSomeIList(flp_type):
    assert_equal(range(10, 20), flp_type(range(0, 20)).to_list().skip(10))


def test_RunOnce(flp_type):
    assert_equal(range(10, 20), flp_type(x for x in range(0, 20)).skip(10))
    assert_equal(
        range(10, 20), flp_type(x for x in range(0, 20)).to_list().skip(10)
    )


def test_SkipNone(flp_type):
    assert_equal(range(0, 20), flp_type(range(0, 20)).skip(0))


def test_SkipNoneIList(flp_type):
    assert_equal(range(0, 20), flp_type(range(0, 20)).to_list().skip(0))


def test_SkipExcessive(flp_type):
    assert_empty(flp_type(range(0, 20)).skip(42))


def test_SkipExcessiveIList(flp_type):
    assert_empty(flp_type(range(0, 20)).to_list().skip(42))


def test_SkipAllExactly(flp_type):
    assert not flp_type(range(0, 20)).skip(20).any()


def test_SkipAllExactlyIList(flp_type):
    assert not flp_type(range(0, 20)).skip(20).to_list().any()


def test_SkipThrowsOnNull(flp_type):
    with pytest.raises((TypeError, ValueError)):
        flp_type(None).skip(3)


def test_SkipThrowsOnNullIList(flp_type):
    with pytest.raises((TypeError, ValueError)):
        flp_type(None).skip(3)


def test_SkipOnEmpty(flp_type):
    for source in create_sources(flp_type)([]):
        assert_empty(source.skip(0))
        assert_empty(source.skip(-1))
        assert_empty(source.skip(1))


def test_SkipNegative(flp_type):
    for source in create_sources(flp_type)(range(0, 20)):
        assert_equal(range(0, 20), source.skip(-42))


def test_SameResultsRepeatCallsIntQuery(flp_type):
    INT_MIN_VALUE = -2147483648
    for source in create_sources(flp_type)([9999, 0, 888, -1, 66, -777, 1, 2, -12345]):
        q = source.where(lambda x: x > INT_MIN_VALUE)
        assert_equal(q.skip(0), q.skip(0))


def test_SameResultsRepeatCallsStringQuery(flp_type):
    for source in create_sources(flp_type)(
            ["!@#$%^", "C", "AAA", "", "Calling Twice", "SoS", ""]
    ):
        q = source.where(lambda x: bool(x))
        assert_equal(q.skip(0), q.skip(0))


def test_SkipOne(flp_type):
    expected = [100, 4, None, 10]
    for source in create_sources(flp_type)([3, 100, 4, None, 10]):
        assert_equal(expected, source.skip(1))


def test_SkipAllButOne(flp_type):
    expected = [10]
    for source in create_sources(flp_type)([3, 100, 4, None, 10]):
        assert_equal(expected, source.skip(4))


def test_SkipOneMoreThanAll(flp_type):
    for source in create_sources(flp_type)([3, 100, 4, 10]):
        assert_empty(source.skip(5))


def test_ForcedToEnumeratorDoesntEnumerate(flp_type):
    for source in create_sources(flp_type)(range(0, 3)):
        iterator = source.skip(2)
        en = iterator if hasattr(iterator, "__next__") else None
        assert not (en is not None and getattr(en, "move_next", lambda: False)())


def test_Count(flp_type):
    assert flp_type(range(0, 3)).skip(1).count() == 2
    assert flp_type([1, 2, 3]).skip(1).count() == 2


def test_FollowWithTake(flp_type):
    expected = [6, 7]
    for source in create_sources(flp_type)(range(5, 9)):
        assert_equal(expected, source.skip(1).take(2))


def test_FollowWithTakeThenMassiveTake(flp_type):
    INT_MAX_VALUE = 2147483647
    expected = [7]
    for source in create_sources(flp_type)([5, 6, 7, 8]):
        assert_equal(expected, source.skip(2).take(1).take(INT_MAX_VALUE))


def test_FollowWithSkip(flp_type):
    expected = [4, 5, 6]
    for source in create_sources(flp_type)([1, 2, 3, 4, 5, 6]):
        assert_equal(expected, source.skip(1).skip(2).skip(-4))


def test_ElementAt(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5, 6]):
        remaining = source.skip(2)
        assert remaining.element_at(0) == 3
        assert remaining.element_at(1) == 4
        assert remaining.element_at(3) == 6
        with pytest.raises(ArgumentOutOfRangeError):
            remaining.element_at(-1)
        with pytest.raises(ArgumentOutOfRangeError):
            remaining.element_at(4)


@pytest.mark.skip("not implemented yet")
def test_ElementAtOrDefault(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5, 6]):
        remaining = source.skip(2)
        assert remaining.element_at_or_default(0, default=0) == 3
        assert remaining.element_at_or_default(1, default=0) == 4
        assert remaining.element_at_or_default(3, default=0) == 6
        assert remaining.element_at_or_default(-1, default=0) == 0
        assert remaining.element_at_or_default(4, default=0) == 0


def test_First(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        assert source.skip(0).first() == 1
        assert source.skip(2).first() == 3
        assert source.skip(4).first() == 5
        with pytest.raises((RuntimeError, ValueError, StopIteration)):
            source.skip(5).first()


def test_FirstOrDefault(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        assert source.skip(0).first_or_default(default=0) == 1
        assert source.skip(2).first_or_default(default=0) == 3
        assert source.skip(4).first_or_default(default=0) == 5
        assert source.skip(5).first_or_default(default=0) == 0


def test_Last(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        assert source.skip(0).last() == 5
        assert source.skip(1).last() == 5
        assert source.skip(4).last() == 5
        with pytest.raises((RuntimeError, ValueError, StopIteration)):
            source.skip(5).last()

@pytest.mark.skip("not implemented yet")
def test_LastOrDefault(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        assert source.skip(0).last_or_default(default=0) == 5
        assert source.skip(1).last_or_default(default=0) == 5
        assert source.skip(4).last_or_default(default=0) == 5
        assert source.skip(5).last_or_default(default=0) == 0


@pytest.mark.skip("not implemented yet, and most likely to_array, never will ")
def test_ToArray(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        assert_equal([1, 2, 3, 4, 5], source.skip(0).to_array())
        assert_equal([2, 3, 4, 5], source.skip(1).to_array())
        assert list(source.skip(4).to_array())[0] == 5
        assert_empty(source.skip(5).to_array())
        assert_empty(source.skip(40).to_array())


def test_ToList(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        assert_equal([1, 2, 3, 4, 5], source.skip(0).to_list())
        assert_equal([2, 3, 4, 5], source.skip(1).to_list())
        assert list(source.skip(4).to_list())[0] == 5
        assert_empty(source.skip(5).to_list())
        assert_empty(source.skip(40).to_list())


def test_RepeatEnumerating(flp_type):
    for source in create_sources(flp_type)([1, 2, 3, 4, 5]):
        remaining = source.skip(1)
        assert_equal(remaining, remaining)

def test_LazySkipMoreThan32Bits(flp_type):
    INT_MAX_VALUE = 2147483647
    range_seq = flp_type(range(1, 101))
    skipped = range_seq.skip(50).skip(INT_MAX_VALUE)
    assert_empty(skipped)
    assert skipped.count() == 0
    # assert_empty(skipped.to_array())
    assert_empty(skipped.to_list())


def test_IteratorStateShouldNotChangeIfNumberOfElementsIsUnbounded():
    class FastInfiniteEnumerator:

        def __iter__(self):
            i = 0
            while True:
                yield i
                i += 1

    # Verify that skipping a massive number (past 32-bit int max) still functions lazily
    # and doesn't crash or overflow internally.
    INT_MAX_VALUE = 2147 # 483647 # 2 billion takes too long and is sort of pointless in Pyhton
    skipped = flp.it(FastInfiniteEnumerator()).skip(INT_MAX_VALUE + 10)
    iterator = iter(skipped)

    assert next(iterator) == INT_MAX_VALUE + 10
    assert next(iterator) == INT_MAX_VALUE + 11


@pytest.mark.parametrize(
    "source_count, count",
    [
        (0, -1),
        (0, 0),
        (1, 0),
        (2, 1),
        (2, 2),
        (2, 3),
    ],
)
def test_DisposeSource(flp_type, source_count, count):
    state = [0]

    class DelegateIterator:

        def __iter__(self):
            while state[0] < source_count:
                state[0] += 1
                yield 0
            state[0] = -1

    source = flp_type(DelegateIterator())
    iterator = iter(source.skip(count))
    iterator_count = max(0, source_count - max(0, count))

    for _ in range(iterator_count):
        assert next(iterator, None) is not None

    assert next(iterator, None) is None
    if hasattr(iterator, "close"):
        iterator.close()
    assert state[0] == -1


def test_SkipMoreThanCountFollowedByOperators(flp_type):
    items = [2, 3]

    for source in create_sources(flp_type)([1]):
        # assert_equal(items, source.skip(2).concat(items).to_array())
        assert_equal(items, source.skip(2).concat(items).to_list())
        # assert_equal(items, source.skip(2).append(2).append(3).to_array())
        assert_equal(items, source.skip(2).append(2).append(3).to_list())
        # assert_equal(items, flp_type(items).concat(source.skip(2)).to_array())
        assert_equal(items, flp_type(items).concat(source.skip(2)).to_list())
        # assert_empty(source.skip(2).select(lambda x: x * 2).to_array())
        assert_empty(source.skip(2).select(lambda x: x * 2).to_list())
        # assert_empty(source.skip(2).where(lambda x: x > 0).to_array())
        assert_empty(source.skip(2).where(lambda x: x > 0).to_list())
        # assert_empty(source.skip(2).take(10).to_array())
        assert_empty(source.skip(2).take(10).to_list())
        # assert_empty(source.skip(2).skip(1).to_array())
        assert_empty(source.skip(2).skip(1).to_list())
        # assert_empty(source.skip(2).distinct().to_array())
        assert_empty(source.skip(2).distinct().to_list())
        # assert_empty(source.skip(2).order_by(lambda x: x).to_array())
        assert_empty(source.skip(2).order_by(lambda x: x).to_list())
        # contains not implemented yet
        # assert not source.skip(2).contains(1)
        # assert not source.skip(2).contains(2)