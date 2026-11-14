from __future__ import annotations

from io import BytesIO, StringIO

import decimal
from decimal import Decimal, Overflow, Inexact
from contextlib import AbstractContextManager

import builtins
from collections import UserList
from functools import wraps, partial as _partial
from operator import is_not as _is_not, ne as _ne, eq as _eq
from itertools import islice, chain, compress
from numbers import Real as _Real

from typing import (
    Any,
    Callable,
    Iterable,
    Iterator,
    Collection,
    SupportsIndex,
    List,
    Set,
    Type,
    TypeVar,
    ClassVar,
    Union,
    override,
    overload,
    cast as typing_cast,
    BinaryIO,
    Concatenate,
    Sized
)

from flpit.json import JsonConvert, JsonSerializerOptions
from flpit import ZipTuple

TKey = TypeVar("TKey")
TOther = TypeVar("TOther")
TAccumulate = TypeVar("TAccumulate")

class _Sentinel:
    __slots__ = ()

    def __call__(self, *args: object, **kwargs: object) -> Any:
        raise TypeError("_SENTINEL cannot be called")

_SENTINEL = _Sentinel()
_MISSING = object()

# =============================================================================
# Invalid Operation Errors
# =============================================================================
class InvalidOperationError(ValueError):
    pass

class EmptySequenceError(InvalidOperationError):
    def __init__(self):
        super().__init__("Sequence contains no elements")

class NoMatchError(InvalidOperationError):
    def __init__(self):
        super().__init__("Sequence contains no matching elements")

class MultipleMatchesError(InvalidOperationError):
    def __init__(self):
        super().__init__("Sequence contains more than one matching element")

class MultipleElementsError(InvalidOperationError):
    def __init__(self):
        super().__init__("Sequence contains more than one element")


# =============================================================================
# Argument Errors
# =============================================================================
class ArgumentError(TypeError):
    pass

class ArgumentNullError(ArgumentError):
    def __init__(self, argument: str):
        super().__init__(f"Value cannot be None. (Argument '{argument}')")

class SourceNoneError(ArgumentNullError):
    def __init__(self):
        super().__init__("source")

class PredicateNoneError(ArgumentNullError):
    def __init__(self):
        super().__init__("predicate")

class CollectionNoneError(ArgumentNullError):
    def __init__(self):
        super().__init__("collection")

class SelectorNoneError(ArgumentNullError):
    def __init__(self):
        super().__init__("keySelector")

class SecondNoneError(ArgumentNullError):
    def __init__(self):
        super().__init__("second")

class FuncNoneError(ArgumentNullError):
    def __init__(self):
        super().__init__("func")

class ResultSelectorNoneError(ArgumentNullError):
    def __init__(self):
        super().__init__("resultSelector")

class ArgumentOutOfRangeError(ArgumentError):
    def __init__(self, argument: str, pattern:str="Index was out of range. Must be non-negative and less than the size of the collection."):
        super().__init__(f"{pattern} (Parameter '{argument}')")

class ArgumentNonNegError(ArgumentOutOfRangeError):
    def __init__(self, argument:str):
        super().__init__(argument, "Non-negative number required.")

class ArgumentOutOfBoundsError(ArgumentError):
    def __init__(self):
        super().__init__("Offset and length were out of bounds for the array or count is greater than the number of elements from index to the end of the source collection.")


_NOT_NONE = _partial(_is_not, None)
_EXTREME_CHUNK = 1024


def _project(items: Iterable[Any], selector: Any) -> Iterable[Any]:
    """Applies an optional selector lazily (C-level map); None selector is an error."""
    if selector is _SENTINEL:
        return items
    if selector is None:
        raise SelectorNoneError()
    return map(selector, items)


def _extreme_values(items: Iterable[Any], is_min: bool) -> Any:
    """
    Single-pass min/max of values with .NET Enumerable.Min/Max semantics.

    flpit has no runtime generics, so every sequence is "None-able":

    - empty input or only None values -> None
    - None values are skipped (nullable Min/Max)
    - numeric NaN uses .NET's total order, where NaN is smaller than every
      other value, including -inf:  min -> NaN if any is present,
      max -> NaN only if every value is NaN
      (builtins.min/max depend on where the NaN sits, since every comparison
      with NaN is False)

    Only the leading run of None values is scanned in Python; the remainder
    is filtered at C speed. Numeric input is reduced in bounded chunks so NaN
    can be detected at C speed (x != x is True only for NaN) in O(chunk) memory.
    """
    pick = builtins.min if is_min else builtins.max
    it = iter(items)

    for first in it:
        if first is None:
            continue

        rest = filter(_NOT_NONE, it)

        if not isinstance(first, (_Real, Decimal)):
            # Non-numeric (str, tuple, date, ...): no NaN semantics apply.
            return pick(chain((first,), rest)) # pyrefly: ignore [bad-specialization]

        if is_min:
            if first != first:
                return first

            best = first
            while chunk := list(islice(rest, _EXTREME_CHUNK)):
                if any(map(_ne, chunk, chunk)):
                    return next(x for x in chunk if x != x)
                best = pick(best, pick(chunk)) # pyrefly: ignore [bad-specialization]
            return best

        nan: Any = first if first != first else _MISSING
        best = _MISSING if nan is not _MISSING else first
        while chunk := list(islice(rest, _EXTREME_CHUNK)):
            if any(map(_ne, chunk, chunk)):
                if nan is _MISSING:
                    nan = next(x for x in chunk if x != x)
                chunk = list(compress(chunk, map(_eq, chunk, chunk)))
                if not chunk:
                    continue
            candidate = builtins.max(chunk) # pyrefly: ignore [bad-specialization]
            best = candidate if best is _MISSING else builtins.max(best, candidate) # pyrefly: ignore [bad-specialization]
        return nan if best is _MISSING else best

    return None


def _extreme_by(items: Iterable[Any], key_selector: Any, is_min: bool) -> Any:
    """
    Single-pass MinBy/MaxBy returning the *element* with the extreme key.

    Follows .NET Enumerable.MinBy/MaxBy:
    - empty input                  -> None (no runtime generics: everything is None-able)
    - key_selector is None         -> SelectorNoneError as soon as there is an element
                                      to select a key for (empty input still gives None)
    - None keys are skipped; if every key is None the first element is returned
    - ties keep the first element
    - NaN keys order below every other number (Comparer<double>.Default):
      min_by returns the first NaN-keyed element, max_by ignores NaN keys
      unless all keys are NaN.

    The selector runs exactly once per element, in order. Work is done in
    bounded chunks so None/NaN filtering and the reduction run at C speed.
    """
    it = iter(items)

    if key_selector is None:
        for _ in it:
            raise SelectorNoneError()
        return None

    pick = builtins.min if is_min else builtins.max
    first_item: Any = _MISSING
    nan_item: Any = _MISSING
    best_item: Any = _MISSING
    best_key: Any = _MISSING

    while chunk := list(islice(it, _EXTREME_CHUNK)):
        if first_item is _MISSING:
            first_item = chunk[0]

        keys = list(map(key_selector, chunk))

        if not all(map(_NOT_NONE, keys)):
            mask = list(map(_NOT_NONE, keys))
            keys = list(compress(keys, mask))
            chunk = list(compress(chunk, mask))
            if not keys:
                continue

        if any(map(_ne, keys, keys)):
            nan_index = next(i for i, k in enumerate(keys) if k != k)
            if is_min:
                return chunk[nan_index]
            if nan_item is _MISSING:
                nan_item = chunk[nan_index]
            mask = list(map(_eq, keys, keys))
            keys = list(compress(keys, mask))
            chunk = list(compress(chunk, mask))
            if not keys:
                continue

        extreme = pick(keys)
        if best_key is _MISSING or (extreme < best_key if is_min else extreme > best_key):
            best_key = extreme
            best_item = chunk[keys.index(extreme)]

    if best_item is not _MISSING:
        return best_item
    if nan_item is not _MISSING:
        return nan_item
    if first_item is not _MISSING:
        return first_item

    # raise EmptySequenceError()
    # no proper generic runtime type, so everything is assumed to be nullable
    return None


def dotnet_context() -> AbstractContextManager[decimal.Context]:
    # 1. Create and configure pure Context object
    ctx = decimal.getcontext().copy()
    ctx.prec = max(ctx.prec, 29)
    ctx.traps[Overflow] = True
    ctx.traps[Inexact] = True

    return decimal.localcontext(ctx)


class _FactoryIterable[TItem](Iterable[TItem]):
    """
    Wraps a generator factory function into a clean Iterable[T].
    Ensures __iter__ produces a brand-new iterator instance on every call
    without type-checker warnings or runtime callable-check overhead.
    """
    __slots__ = ("_factory",)

    def __init__(self, factory: Callable[[], Iterator[TItem]]) -> None:
        self._factory = factory

    def __iter__(self) -> Iterator[TItem]:
        return self._factory()


# Exact builtin types whose iter() has no side effects and no failure mode, so
# calling it eagerly is indistinguishable from calling it on the first next().
_PURE_ITER_TYPES = (list, tuple, range)


def _is_pure(source: object) -> bool:
    return type(source) in _PURE_ITER_TYPES or getattr(source, "_pure", False) is True


class _WhereIterable[TItem](Iterable[TItem]):
    """Deferred filter node with independent iteration state."""
    __slots__ = ("_source", "_predicate", "_pure")

    def __init__(self, source: Iterable[TItem], predicate: Callable[[TItem], bool]) -> None:
        self._source = source
        self._predicate = predicate
        self._pure = _is_pure(source)

    def __iter__(self) -> Iterator[TItem]:
        if self._pure:  # whole chain bottoms out in a list/tuple/range: no wrapper needed
            return filter(self._predicate, iter(self._source))  # type: ignore[arg-type]
        # chain.from_iterable defers iter(source) to the first next(), like a generator would.
        return filter(self._predicate, chain.from_iterable((self._source,)))  # type: ignore[arg-type]


class _SelectIterable[TItem, TResult](Iterable[TResult]):
    """Deferred projection node with independent iteration state."""
    __slots__ = ("_source", "_selector", "_pure")

    def __init__(self, source: Iterable[TItem], selector: Callable[[TItem], TResult]) -> None:
        self._source = source
        self._selector = selector
        self._pure = _is_pure(source)

    def __iter__(self) -> Iterator[TResult]:
        if self._pure:
            return map(self._selector, iter(self._source))  # type: ignore[arg-type]
        return map(self._selector, chain.from_iterable((self._source,)))  # type: ignore[arg-type]


class FlpIt[TItem](Iterable[TItem]):
    """
    | Fluent Iterable
    Lazy evaluation wrapper around an iterable, inspired by .NET LINQ's
    IEnumerable<T> semantics. Operations are deferred and do not cache results
    unless explicitly documented otherwise.

    Multiple enumeration is supported when the underlying source is re-iterable;
    one-shot iterators and generators remain one-shot.
    """
    __slots__ = ("_iterable",)

    def __init__(self, source: Iterable[TItem]) -> None:
        if source is None:
            raise SourceNoneError()
        self._iterable: Iterable[TItem] = source

    def __iter__(self) -> Iterator[TItem]:
        return iter(self._iterable)

    # noinspection unused-parameter
    def as_type[TResult](self, target_type: Type[TResult]) -> FlpIt[TResult]:
        """Zero-cost static type hint update returning self directly without checks or allocations."""
        return self  # type: ignore[return-value]

    # --- Deferred Execution (Lazy Operations) ---

    def append(self, element: TItem) -> FlpIt[TItem]:
        """Appends an element to the end of the sequence (deferred)."""
        def _generator() -> Iterator[TItem]:
            yield from self
            yield element

        return FlpIt(_FactoryIterable(_generator))

    @overload
    def any(self) -> bool: ...

    @overload
    def any(self, predicate: Callable[[TItem], bool]) -> bool: ...

    def any(
            self,
            predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL,
    ) -> bool:
        """
        Determines whether the sequence contains any elements,
        or whether any element satisfies the predicate.

        Mirrors Enumerable.Any:
            Any()
            Any(predicate)

        Evaluation stops as soon as the result is known.
        """
        if predicate is not _SENTINEL:
            return builtins.any(map(predicate, self))

        iterator = iter(self)
        try:
            next(iterator)
        except StopIteration:
            return False

        return True


    def all(self, predicate: Callable[[TItem], bool]) -> bool:
        """
        Determines whether all elements satisfy the predicate.

        Mirrors Enumerable.All.

        Returns True for an empty sequence.
        Evaluation stops at the first element that fails the predicate.
        """
        return builtins.all(map(predicate, self))

    def concat(self, second: Iterable[TItem]) -> "FlpIt[TItem]":
        if second is None:
            raise SecondNoneError()

        def _generator() -> Iterator[TItem]:
            yield from self
            yield from second

        return FlpIt(_FactoryIterable(_generator))

    def prepend(self, element: TItem) -> FlpIt[TItem]:
        """Prepends an element to the beginning of the sequence (deferred)."""
        def _generator() -> Iterator[TItem]:
            yield element
            yield from self

        return FlpIt(_FactoryIterable(_generator))

    def contains(self, value: TItem) -> bool:
        source = self._iterable

        if isinstance(source, Collection):
            return value in source

        for item in source:
            if item == value:
                return True

        return False

    def _node_source(self) -> Iterable[TItem]:
        """Return the upstream iterable, preserving subclasses that customize iteration."""
        return self._iterable if type(self) is FlpIt else self

    def where(self, predicate: Callable[[TItem], bool]) -> FlpIt[TItem]:
        """Filters elements based on a predicate (deferred)."""
        if predicate is None:
            raise PredicateNoneError()
        return FlpIt[TItem](_WhereIterable(self._node_source(), predicate))

    def select[TResult](self, selector: Callable[[TItem], TResult]) -> FlpIt[TResult]:
        """Projects each element into a new form (deferred)."""
        if selector is None:
            raise SelectorNoneError()
        return FlpIt(_SelectIterable(self._node_source(), selector))

    def select_many[TResult](
            self, selector: Callable[[TItem], Iterable[TResult]]
    ) -> FlpIt[TResult]:
        """Flattens sequence projections."""
        if selector is None:
            raise SelectorNoneError()

        def _generator() -> Iterator[TResult]:
            for item in self:
                yield from selector(item)

        return FlpIt(_FactoryIterable(_generator))

    def skip(self, count: int) -> "FlpIt[TItem]":
        """
        |Bypasses a specified number of elements from the start.
        """
        if count <= 0:
            return self

        def _generator() -> Iterator[TItem]:
            yield from islice(iter(self), count, None)

        return FlpIt(_FactoryIterable(_generator))

    def take(self, count: int) -> "FlpIt[TItem]":
        """
        |Returns a specified number of contiguous elements from the start.

        Execution is deferred until the returned sequence is enumerated.
        The operator consumes no more than `count` elements from upstream.

        `take()` does not own the upstream iterator and therefore does not
        close it when the limit is reached. Upstream resource lifetime is the
        responsibility of the code that owns/acquires the source; use an
        explicit context manager or close the source explicitly when required.

        This is intentional: reaching the `take()` limit is normal completion,
        not cancellation or disposal of the upstream sequence.
        """
        if count <= 0:
            return FlpIt(())

        def _generator() -> Iterator[TItem]:
            yield from islice(iter(self), count)

        return FlpIt(_FactoryIterable(_generator))

    def cast[TResult](self, target_type: Type[TResult]) -> FlpIt[TResult]:
        """Casts elements to a specified type or raises TypeError if cast fails."""
        def _generator() -> Iterator[TResult]:
            for item in self:
                if not isinstance(item, target_type):
                    raise TypeError(
                        f"Cannot cast element {item!r} of type {type(item).__name__} to {target_type.__name__}"
                    )
                yield item  # type: ignore[misc]

        return FlpIt(_FactoryIterable(_generator))

    def of_type[TResult](self, target_type: Type[TResult]) -> FlpIt[TResult]:
        """Filters the elements of an Iterable based on a specified type."""
        def _generator() -> Iterator[TResult]:
            for item in self:
                if isinstance(item, target_type):
                    yield item  # type: ignore[misc]

        return FlpIt(_FactoryIterable(_generator))

    def distinct(self) -> FlpIt[TItem]:
        """Returns distinct elements from a sequence by using O(1) set lookups."""
        def _generator() -> Iterator[TItem]:
            seen: Set[TItem] = set()
            for item in self:
                if item not in seen:
                    seen.add(item)
                    yield item

        return FlpIt(_FactoryIterable(_generator))

    def distinct_by(
            self, key_selector: Callable[[TItem], TKey]
    ) -> FlpIt[TItem]:
        """Returns distinct elements from a sequence according to a key selector function."""
        if key_selector is None:
            raise SelectorNoneError()

        def _generator() -> Iterator[TItem]:
            seen: Set[TKey] = set()
            for item in self:
                key = key_selector(item)
                if key not in seen:
                    seen.add(key)
                    yield item

        return FlpIt(_FactoryIterable(_generator))

    @overload
    def zip(self, second: Iterable[TOther]) -> FlpIt[ZipTuple[TItem, TOther]]: ...

    @overload
    def zip[TResult, TOther](
            self,
            second: Iterable[TOther],
            result_selector: Callable[[TItem, TOther], TResult],
    ) -> FlpIt[TResult]: ...

    def zip(
            self,
            second: Iterable[TOther],
            result_selector: Callable[[TItem, TOther], Any] | _Sentinel = _SENTINEL,
    ) -> FlpIt[Any]:
        """Applies a specified function to corresponding elements of two sequences."""
        if second is None:
            raise SecondNoneError()

        if result_selector is None:
            raise ResultSelectorNoneError()

        def _generator() -> Iterator[Any]:
            for first_item, second_item in zip(self, second):
                if result_selector is not _SENTINEL:
                    yield result_selector(first_item, second_item)
                else:
                    yield ZipTuple(first_item, second_item)

        return FlpIt(_FactoryIterable(_generator))

    def chunk(self, size: int) -> FlpIt[FlpList[TItem]]:
        """Splits the elements of a sequence into chunks of size at most size."""
        if size <= 0:
            raise ArgumentOutOfRangeError("Specified argument was out of the range of valid values. (Parameter 'size')")

        def _generator() -> Iterator[FlpList[TItem]]:
            current_chunk: List[TItem] = []
            for item in self:
                current_chunk.append(item)
                if len(current_chunk) == size:
                    yield FlpList(current_chunk)
                    current_chunk = []
            if current_chunk:
                yield FlpList(current_chunk)

        return FlpIt(_FactoryIterable(_generator))

    def order_by(
            self, key_selector: Callable[[TItem], Any]
    ) -> OrderedIt[TItem]:
        """Sorts elements in ascending order according to a key."""
        return OrderedIt(self, key_selector, descending=False)

    def order_by_descending(
            self, key_selector: Callable[[TItem], Any]
    ) -> OrderedIt[TItem]:
        """Sorts elements in descending order according to a key."""
        return OrderedIt(self, key_selector, descending=True)

    def group_by(
            self, key_selector: Callable[[TItem], TKey]
    ) -> FlpIt[Grouping[TKey, TItem]]:
        """Groups elements according to a specified key selector function."""
        if key_selector is None:
            raise SelectorNoneError()

        def _generator() -> Iterator[Grouping[TKey, TItem]]:
            groups: dict[TKey, List[TItem]] = {}
            for item in self:
                key = key_selector(item)
                groups.setdefault(key, []).append(item)
            for k, v in groups.items():
                yield Grouping(k, v)

        return FlpIt(_FactoryIterable(_generator))

    # --- Immediate Execution (Materialization & Aggregation) ---

    @overload
    def aggregate(self, func: Callable[[TItem, TItem], TItem], /) -> TItem: ...

    @overload
    def aggregate(
            self, seed: TAccumulate, func: Callable[[TAccumulate, TItem], TAccumulate], /
    ) -> TAccumulate: ...

    @overload
    def aggregate[TAcc, TResult](
            self,
            seed: TAcc,
            func: Callable[[TAcc, TItem], TAcc],
            result_selector: Callable[[TAcc], TResult],
            /,
    ) -> TResult: ...

    def aggregate(self, *args: Any) -> Any:
        """Applies an accumulator function over a sequence.

        aggregate(func)                         first element is the seed; raises
                                                EmptySequenceError for an empty source
        aggregate(seed, func)                   seed is the initial accumulator
        aggregate(seed, func, result_selector)  result_selector is applied to the
                                                final accumulator value
        """
        if len(args) == 1:
            (func,) = args
            has_seed = False
            seed = None
            result_selector = _SENTINEL
        elif len(args) == 2:
            seed, func = args
            has_seed = True
            result_selector = _SENTINEL
        elif len(args) == 3:
            seed, func, result_selector = args
            has_seed = True
        else:
            raise TypeError(
                f"aggregate() takes from 1 to 3 positional arguments but {len(args)} were given"
            )

        if func is None:
            raise FuncNoneError()
        if result_selector is None:
            raise ResultSelectorNoneError()

        it = iter(self)
        if has_seed:
            accumulator = seed
        else:
            try:
                accumulator = next(it)
            except StopIteration:
                raise EmptySequenceError()
        for item in it:
            accumulator = func(accumulator, item)

        if result_selector is not _SENTINEL:
            return result_selector(accumulator)
        return accumulator

    @overload
    def last(self) -> TItem: ...

    @overload
    def last(self, predicate: Callable[[TItem], bool]) -> TItem: ...

    def last(
            self,
            predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL,
    ) -> TItem:
        """
        Returns the last element of the sequence, or the last element
        satisfying the predicate.

        Mirrors Enumerable.Last:
            Last()
            Last(predicate)

        Raises EmptySequenceError if the sequence is empty or if no
        element satisfies the predicate.
        """
        if predicate is None:
            raise PredicateNoneError()

        last_item: TItem | object = _MISSING

        for item in self:
            if predicate is _SENTINEL or predicate(item):
                last_item = item

        if last_item is _MISSING:
            raise EmptySequenceError() if predicate is _SENTINEL else NoMatchError()

        return typing_cast(TItem, last_item)

    @overload
    def min(self) -> TItem: ...

    @overload
    def min[TResult](self, selector: Callable[[TItem], TResult]) -> TResult: ...

    def min(self, selector: Callable[[TItem], Any] | _Sentinel = _SENTINEL) -> Any:
        """
        Returns the minimum value in a sequence, optionally projecting each
        element through a selector first (Enumerable.Min / Min(selector)).

        With a selector the minimum *projected value* is returned, not the
        element (use min_by for that). None values are ignored; all-None
        returns None; empty raises EmptySequenceError; NaN wins if present.
        """
        return _extreme_values(_project(self, selector), True)

    @overload
    def max(self) -> TItem: ...

    @overload
    def max[TResult](self, selector: Callable[[TItem], TResult]) -> TResult: ...

    def max(self, selector: Callable[[TItem], Any] | _Sentinel = _SENTINEL) -> Any:
        """
        Returns the maximum value in a sequence, optionally projecting each
        element through a selector first (Enumerable.Max / Max(selector)).
        Same None / NaN / empty rules as min.
        """
        return _extreme_values(_project(self, selector), False)

    def min_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        """Returns the element with the minimum key (Enumerable.MinBy)."""
        return _extreme_by(self, key_selector, True)

    def max_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        """Returns the element with the maximum key (Enumerable.MaxBy)."""
        return _extreme_by(self, key_selector, False)

    def average(
            self, selector: Callable[[TItem], int | float | Decimal] | _Sentinel = _SENTINEL
    ) -> float | int | Decimal | None:
        """Computes the arithmetic mean of the sequence, optionally applying a selector."""
        with dotnet_context():
            total, count = self.__sum_and_count(selector)

            if total is None:
                return None

            if isinstance(total, Decimal):
                return total / Decimal(count)

            assert total is not None
            assert isinstance(total, Decimal) or isinstance(total, int) or isinstance(total, float)
            return total / count

    avg = average

    def sum(
            self, selector: Callable[[TItem], int | float | Decimal] | _Sentinel = _SENTINEL
    ) -> Union[int, float, Decimal]:
        """Calculates the sum of the sequence, optionally applying a selector."""
        with dotnet_context():
            total, count = self.__sum_and_count(selector)

            if count == 0:
                return 0

            assert total is not None
            assert isinstance(total, Decimal) or isinstance(total, int) or isinstance(total, float)
            return total

    def __sum_and_count(self, selector: Callable[[TItem], int | float | Decimal]) -> tuple[Decimal | float | int | TItem | None, int]:
        if selector is None:
            raise SelectorNoneError()

        total = None
        count: int = 0
        query = (selector(x) for x in self) if selector is not _SENTINEL else self

        for item in query:
            if item is not None:
                if total is None:
                    total = item
                else:
                    try:
                        total += item
                    except (Overflow, Inexact):
                        raise OverflowError(
                            "System.OverflowException: Value was either too large or too small for a Decimal."
                        )
                count += 1

        return total, count


    def count(
            self,
            predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL,
    ) -> int:
        """Counts elements in the sequence, optionally matching a predicate."""
        if predicate is _SENTINEL:
            return builtins.sum(1 for _ in self)

        return builtins.sum(1 for _ in self.where(predicate))

    def element_at(self, index: int) -> TItem:
        """Returns the element at a specified index in a sequence."""
        if index < 0:
            raise ArgumentOutOfRangeError("index")

        for i, item in enumerate(self):
            if i == index:
                return item

        raise ArgumentOutOfRangeError("index")

    def first(self, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL) -> TItem:
        """Returns the first element matching a predicate, or raises ValueError."""
        query = self.where(predicate) if predicate is not _SENTINEL else self
        for item in query:
            return item
        raise EmptySequenceError() if predicate is _SENTINEL else NoMatchError()

    def first_or_default[TResult](
            self, default: TResult, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL
    ) -> Union[TItem, TResult]:
        """Returns the first element matching a predicate, or a default value."""
        try:
            return self.first(predicate)
        except (EmptySequenceError, NoMatchError):
            return default

    def last_or_default[TResult](
            self, default: TResult, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL
    ) -> TItem | TResult:
        """Returns the last element matching a predicate, or a default value."""
        try:
            return self.last(predicate)
        except (EmptySequenceError, NoMatchError):
            return default

    def reverse(self) -> FlpIt[TItem]:
        """Returns the elements of the sequence in reverse order."""
        def _generator() -> Iterator[TItem]:
            items = list(self)
            yield from reversed(items)

        return FlpIt(_FactoryIterable(_generator))

    def single(self, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL) -> TItem:
        """Returns the single, unique element matching a predicate."""
        has_predicate = predicate is not _SENTINEL
        query = self.where(predicate) if has_predicate else self
        it = iter(query)

        try:
            first_val = next(it)
        except StopIteration:
            raise NoMatchError() if has_predicate else EmptySequenceError()

        try:
            next(it)
        except StopIteration:
            return first_val

        raise MultipleMatchesError() if has_predicate else MultipleElementsError()

    def single_or_default[TResult](
            self,
            default: TResult,
            predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL,
    ) -> TItem | TResult:
        """Returns the single matching element, or the specified default."""
        try:
            return self.single(predicate)
        except (EmptySequenceError, NoMatchError):
            return default

    @overload
    def to_dictionary[TKey](
            self, key_selector: Callable[[TItem], TKey], /
    ) -> dict[TKey, TItem]: ...

    @overload
    def to_dictionary[TKey, TValue](
            self,
            key_selector: Callable[[TItem], TKey],
            element_selector: Callable[[TItem], TValue],
            /,
    ) -> dict[TKey, TValue]: ...

    def to_dictionary(
            self,
            key_selector: Callable[[TItem], Any],
            element_selector: Callable[[TItem], Any] | _Sentinel = _SENTINEL,
    ) -> dict[Any, Any]:
        """Materializes the sequence as a dictionary using the selected key and optional value."""
        if key_selector is None:
            raise SelectorNoneError()
        if element_selector is None:
            raise SelectorNoneError()

        result: dict[Any, Any] = {}
        for item in self:
            key = key_selector(item)
            if key in result:
                raise ValueError(f"An item with the same key has already been added. Key: {key!r}")
            value = item if element_selector is _SENTINEL else element_selector(item)
            result[key] = value

        return result

    def to_list(self) -> FlpList[TItem]:
        """Explicitly materializes the query into a FlpList."""
        return FlpList[TItem](self)

    # =====================================================================
    # 5. json serialization
    # =====================================================================

    @classmethod
    def from_json[T](cls, data: str | bytes, item_type: type[T], jso: JsonSerializerOptions|None=None) -> FlpIt[T]:
        return FlpIt[T](JsonConvert.deserialize(data, list[item_type], jso))

    def to_json_bytes[T](self, item_type: type[T], jso: JsonSerializerOptions|None=None) -> bytes:
        writer = BytesIO()
        JsonConvert.serialize_to(self, item_type, writer, jso)
        return writer.getvalue()

    def to_json[T](self, item_type: type[T], jso: JsonSerializerOptions|None=None) -> str:
        writer = StringIO()
        JsonConvert.serialize_to(self, item_type, writer, jso)
        return writer.getvalue()

    def write_json[T](
            self,
            item_type: type[T],
            output: BinaryIO,
            jso: JsonSerializerOptions | None = None,
    ) -> None:
        JsonConvert.serialize_to(self, item_type, output, jso)


from functools import partial

class _NoneOrderKey:
    __slots__ = ()

    def __lt__(self, other: object) -> bool:
        return other is not self

    def __gt__(self, other: object) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        return other is self


_NONE_ORDER_KEY = _NoneOrderKey()

class OrderedIt[TItem](FlpIt[TItem]):
    __slots__ = ("_criteria",)

    def __init__(
            self,
            source: Iterable[TItem],
            selector: Callable[[TItem], Any],
            descending: bool = False,
            *,
            _criteria: tuple[tuple[Callable[[TItem], Any], bool], ...] | None = None,
    ):
        if selector is None:
            raise SelectorNoneError()

        super().__init__(source)

        if _criteria is None:
            self._criteria = ((selector, descending),)
        else:
            self._criteria = _criteria + ((selector, descending),)

    @staticmethod
    def __none_aware_key(
            selector: Callable[[TItem], Any],
            item: TItem,
    ) -> Any:
        key = selector(item)
        return _NONE_ORDER_KEY if key is None else key

    @override
    def __iter__(self) -> Iterator[TItem]:
        items = list(self._iterable)

        for selector, descending in reversed(self._criteria):
            items.sort(
                key=partial(self.__none_aware_key, selector),
                reverse=descending,
            )

        yield from items

    def then_by(
            self,
            key_selector: Callable[[TItem], Any],
    ) -> "OrderedIt[TItem]":
        return OrderedIt(
            self._iterable,
            key_selector,
            False,
            _criteria=self._criteria,
        )

    def then_by_descending(
            self,
            key_selector: Callable[[TItem], Any],
    ) -> "OrderedIt[TItem]":
        return OrderedIt(
            self._iterable,
            key_selector,
            True,
            _criteria=self._criteria,
        )


class FlpList[TItem](Collection[TItem]):
    """
    | Fluent List
    A materialized list extending UserList that yields lazy FlpIt instances for query operations.
    """
    __type_args__: ClassVar[tuple[Any, ...]]

    def __init__(self, source: Iterable[TItem] | _Sentinel=_SENTINEL):
        if source is None:
            raise SourceNoneError()

        if source is _SENTINEL:
            init_list: Iterable[TItem] = list[TItem]()  # don't depend on the base class to do the right thing
        else:
            init_list = typing_cast(Iterable[TItem], source)

        self.__list: UserList[TItem] = UserList[TItem](init_list)

    # =====================================================================
    # 1. THE ABC CONTRACT
    # =====================================================================
    def __iter__(self) -> Iterator[TItem]:
        return self.__list.__iter__()

    def __len__(self) -> int:
        """Evaluates the stream to get total count."""
        return self.__list.__len__()

    def __contains__(self, item: TItem) -> bool:
        return self.__list.__contains__(item)

    # =====================================================================
    # 2. Keep some of the Python UserList like behavior
    # =====================================================================

    def __repr__(self):
        return self.__list.__repr__()

    def __str__(self) -> str:
        return self.__list.__str__()

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, FlpList):
            return self.__list.__eq__(other.__list)
        return self.__list.__eq__(other)

    def __lt__(self, other: Any) -> bool:
        target = other.__list if isinstance(other, FlpList) else other
        return self.__list.__lt__(target)

    def __le__(self, other: Any) -> bool:
        target = other.__list if isinstance(other, FlpList) else other
        return self.__list.__le__(target)

    def __gt__(self, other: Any) -> bool:
        target = other.__list if isinstance(other, FlpList) else other
        return self.__list.__gt__(target)

    def __ge__(self, other: Any) -> bool:
        target = other.__list if isinstance(other, FlpList) else other
        return self.__list.__ge__(target)


    @overload
    def __getitem__(self, index: SupportsIndex) -> TItem: ...

    @overload
    def __getitem__(self, index: slice) -> FlpList[TItem]: ...

    def __getitem__(self, index: SupportsIndex | slice):
        if isinstance(index, slice):
            return self.__class__(self.__list[index])
        else:
            return self.__list[index]

    @overload
    def __setitem__(self, index: SupportsIndex, value: TItem) -> None: ...

    @overload
    def __setitem__(self, index: slice, value: Iterable[TItem]) -> None: ...

    def __setitem__(
            self,
            index: SupportsIndex | slice,
            value: TItem | Iterable[TItem],
    ) -> None:
        if isinstance(index, slice):
            if not isinstance(value, Iterable):
                raise TypeError("slice assignment requires an iterable value")
            self.__list.data[index] = value
        else:
            if isinstance(value, Iterable):
                raise TypeError("item assignment requires a non-iterable value")
            self.__list.data[index] = value

    # =====================================================================
    # 3. Put .NET List<T> mechanics on top
    # =====================================================================

    def add(self, item: TItem) -> None:
        """
        |Adds an item and performs O(1) type consistency check against the first element.

        |Type safety via
        - type checks
        - manual of_type(...) filter if you don't trust your checks
        """
        self.__list.data.append(item)

    def add_range(self, collection: Iterable[TItem]) -> None:
        """
        | Adds an Iterable sequence or stream.
        Optimizes paths based on input type without destroying volatile generators.

        |Type safety via
        - type checks
        - manual of_type(...) filter if you don't trust your checks
        """
        if collection is None:
            raise CollectionNoneError()

        if isinstance(collection, UserList):
            self.__list.data.extend(collection.data)
        elif isinstance(collection, FlpList):
            self.__list.data.extend(collection.__list.data)
        else:
            self.__list.data.extend(collection)

    def clear(self) -> None:
        self.__list.data.clear()

    def contains(self, item: TItem) -> bool:
        return item in self.__list.data

    def exists(self, predicate: Callable[[TItem], bool]) -> bool:
        return any(predicate(item) for item in self.__list.data)

    def find(self, predicate: Callable[[TItem], bool]) -> TItem | None:
        if predicate is None:
            raise PredicateNoneError()

        for item in self.__list.data:
            if predicate(item):
                return item

        return None

    def find_all(self, predicate: Callable[[TItem], bool]) -> FlpList[TItem]:
        if predicate is None:
            raise PredicateNoneError()

        return FlpList(item for item in self.__list.data if predicate(item))

    def insert(self, index: int, item: TItem) -> None:
        if index < 0 or index > len(self.__list.data):
            raise ArgumentOutOfRangeError("index")

        self.__list.data.insert(index, item)

    def insert_range(self, index: int, collection: Iterable[TItem]) -> None:
        if collection is None:
            raise CollectionNoneError()

        if index < 0 or index > len(self.__list.data):
            raise ArgumentOutOfRangeError("index")

        self.__list.data[index:index] = list(collection)

    def remove(self, item: TItem) -> bool:
        try:
            self.__list.data.remove(item)
            return True
        except ValueError:
            return False

    def remove_all(self, predicate: Callable[[TItem], bool]) -> int:
        if predicate is None:
            raise PredicateNoneError()

        original_length = len(self.__list.data)

        self.__list.data[:] = [
            item
            for item in self.__list.data
            if not predicate(item)
        ]

        return original_length - len(self.__list.data)

    def remove_at(self, index: int) -> None:
        if index < 0 or index >= len(self.__list.data):
            raise ArgumentOutOfRangeError("index")

        del self.__list.data[index]

    def remove_range(self, index: int, count: int) -> None:
        size = len(self.__list.data)

        if index < 0:
            raise ArgumentNonNegError("index")

        if count < 0:
            raise ArgumentNonNegError("count")

        if count > size - index:
            raise ArgumentOutOfBoundsError()

        del self.__list.data[index : index + count]

    @overload
    def reverse(self) -> None: ...

    @overload
    def reverse(self, index: int, count: int) -> None: ...

    def reverse(self, index: int = 0, count: int | None = None) -> None:
        if count is None:
            self.__list.data.reverse()
            return

        size = len(self.__list.data)

        # Apply your List<T>-compatible argument validation here.
        if index < 0 or index > size:
            raise ArgumentNonNegError("index")

        if count < 0:
            raise ArgumentNonNegError("count")

        if index + count > size:
            raise ArgumentOutOfBoundsError()

        self.__list.data[index:index + count] = reversed(
            self.__list.data[index:index + count]
        )

    # =====================================================================
    # 4. IEnumerable add-ons
    # =====================================================================

    @overload
    def any(self) -> bool: ...

    @overload
    def any(self, predicate: Callable[[TItem], bool]) -> bool: ...

    def any(
            self,
            predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL,
    ) -> bool:
        if predicate is _SENTINEL:
            return len(self.__list.data) > 0

        return any(predicate(item) for item in self.__list.data)

    def all(
            self,
            predicate: Callable[[TItem], bool],
    ) -> bool:
        return all(predicate(item) for item in self.__list.data)

    def append(self, element: TItem) -> FlpIt[TItem]:
        """Appends an element to the sequence lazily, returning a FlpIt without mutating this list."""
        return FlpIt(self.__list.data).append(element)

    def prepend(self, element: TItem) -> FlpIt[TItem]:
        """Prepends an element to the sequence lazily, returning a FlpIt without mutating this list."""
        return FlpIt(self.__list.data).prepend(element)

    def concat(self, second: Iterable[TItem]) -> FlpIt[TItem]:
        return FlpIt(self.__list.data).concat(second)

    def as_type[TResult](self, target_type: Type[TResult]) -> FlpList[TResult]:
        return typing_cast(FlpList[TResult], self)

    def where(self, predicate: Callable[[TItem], bool]) -> FlpIt[TItem]:
        return FlpIt[TItem](self.__list.data).where(predicate)

    def select[TResult](self, selector: Callable[[TItem], TResult]) -> FlpIt[TResult]:
        return FlpIt(self.__list.data).select(selector)

    def select_many[TResult](
            self, selector: Callable[[TItem], Iterable[TResult]]
    ) -> FlpIt[TResult]:
        return FlpIt(self.__list.data).select_many(selector)

    def skip(self, count: int) -> FlpIt[TItem]:
        return FlpIt(self.__list.data).skip(count)

    def take(self, count: int) -> FlpIt[TItem]:
        return FlpIt(self.__list.data).take(count)

    def cast[TResult](self, target_type: Type[TResult]) -> FlpIt[TResult]:
        return FlpIt(self.__list.data).cast(target_type)

    def of_type[TResult](self, target_type: Type[TResult]) -> FlpIt[TResult]:
        return FlpIt(self.__list.data).of_type(target_type)

    def distinct(self) -> FlpIt[TItem]:
        return FlpIt(self.__list.data).distinct()

    def distinct_by(
            self, key_selector: Callable[[TItem], TKey]
    ) -> FlpIt[TItem]:
        return FlpIt(self.__list.data).distinct_by(key_selector)

    @overload
    def zip(self, second: Iterable[TOther]) -> FlpIt[ZipTuple[TItem, TOther]]: ...

    @overload
    def zip[TResult, TOther](
            self,
            second: Iterable[TOther],
            result_selector: Callable[[TItem, TOther], TResult],
    ) -> FlpIt[TResult]: ...

    def zip(
            self,
            second: Iterable[TOther],
            result_selector: Callable[[TItem, TOther], Any] | _Sentinel = _SENTINEL,
    ) -> FlpIt[Any]:
        return FlpIt(self.__list.data).zip(second, result_selector)

    def chunk(self, size: int) -> FlpIt[FlpList[TItem]]:
        return FlpIt(self.__list.data).chunk(size)

    def order_by(
            self, key_selector: Callable[[TItem], Any]
    ) -> OrderedIt[TItem]:
        return FlpIt(self.__list.data).order_by(key_selector)

    def order_by_descending(
            self, key_selector: Callable[[TItem], Any]
    ) -> OrderedIt[TItem]:
        return FlpIt(self.__list.data).order_by_descending(key_selector)

    def group_by(
            self, key_selector: Callable[[TItem], TKey]
    ) -> FlpIt[Grouping[TKey, TItem]]:
        return FlpIt(self.__list.data).group_by(key_selector)

    @overload
    def aggregate(self, func: Callable[[TItem, TItem], TItem], /) -> TItem: ...

    @overload
    def aggregate(
            self, seed: TAccumulate, func: Callable[[TAccumulate, TItem], TAccumulate], /
    ) -> TAccumulate: ...

    @overload
    def aggregate[TAcc, TResult](
            self,
            seed: TAcc,
            func: Callable[[TAcc, TItem], TAcc],
            result_selector: Callable[[TAcc], TResult],
            /,
    ) -> TResult: ...

    def aggregate(self, *args: Any) -> Any:
        return FlpIt(self.__list.data).aggregate(*args)

    @overload
    def min(self) -> TItem: ...

    @overload
    def min[TResult](self, selector: Callable[[TItem], TResult]) -> TResult: ...

    def min(self, selector: Callable[[TItem], Any] | _Sentinel = _SENTINEL) -> Any:
        return _extreme_values(_project(self.__list.data, selector), True)

    @overload
    def max(self) -> TItem: ...

    @overload
    def max[TResult](self, selector: Callable[[TItem], TResult]) -> TResult: ...

    def max(self, selector: Callable[[TItem], Any] | _Sentinel = _SENTINEL) -> Any:
        return _extreme_values(_project(self.__list.data, selector), False)

    def min_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        return _extreme_by(self.__list.data, key_selector, True)

    def max_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        return _extreme_by(self.__list.data, key_selector, False)

    def sum(
            self, selector: Callable[[TItem], int | float | Decimal] | _Sentinel = _SENTINEL
    ) -> int | float | Decimal:
        """Calculates the sum of elements, optionally applying a selector."""
        return FlpIt(self.__list.data).sum(selector)

    def average(
            self, selector: Callable[[TItem], int | float | Decimal] | _Sentinel = _SENTINEL
    ) -> float | int | Decimal | None:
        """Calculates the arithmetic mean, optionally applying a selector."""
        return FlpIt(self.__list.data).average(selector)

    def count(
            self,
            predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL,
    ) -> int:
        """
        Counts elements using LINQ semantics.

        Supported forms:
            - count()          -> total number of elements
            - count(predicate) -> number of elements satisfying the predicate
        """
        if predicate is _SENTINEL:
            return len(self.__list.data)

        return FlpIt(self.__list.data).count(predicate)

    def element_at(self, index: int) -> TItem:
        if index < 0 or index >= len(self.__list.data):
            raise ArgumentOutOfRangeError("index")
        return self.__list.data[index]

    def first(self, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL) -> TItem:
        return FlpIt(self.__list.data).first(predicate)

    @overload
    def last(self) -> TItem: ...

    @overload
    def last(self, predicate: Callable[[TItem], bool]) -> TItem: ...

    def last(
            self,
            predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL,
    ) -> TItem:
        """
        Returns the last element of the sequence, or the last element
        satisfying the predicate.

        Mirrors Enumerable.Last:
            Last()
            Last(predicate)

        Raises EmptySequenceError if the sequence is empty or if no
        element satisfies the predicate.
        """
        if predicate is None:
            raise PredicateNoneError()

        if predicate is _SENTINEL:
            if not self.__list.data:
                raise EmptySequenceError()
            return self.__list.data[-1]

        for item in reversed(self.__list.data):
            if predicate(item):
                return item

        raise EmptySequenceError() if predicate is _SENTINEL else NoMatchError()

    def first_or_default[TResult](
            self, default: TResult, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL
    ) -> TItem | TResult:
        return FlpIt(self.__list.data).first_or_default(default, predicate)

    def last_or_default[TResult](
            self, default: TResult, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL
    ) -> TItem | TResult:
        try:
            return self.last(predicate)
        except (EmptySequenceError, NoMatchError):
            return default

    def single(self, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL) -> TItem:
        return FlpIt(self.__list.data).single(predicate)

    def single_or_default[TResult](
            self,
            default: TResult,
            predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL,
    ) -> TItem | TResult:
        return FlpIt(self.__list.data).single_or_default(default, predicate)

    @overload
    def to_dictionary[TKey](
            self, key_selector: Callable[[TItem], TKey], /
    ) -> dict[TKey, TItem]: ...

    @overload
    def to_dictionary[TKey, TValue](
            self,
            key_selector: Callable[[TItem], TKey],
            element_selector: Callable[[TItem], TValue],
            /,
    ) -> dict[TKey, TValue]: ...

    def to_dictionary(
            self,
            key_selector: Callable[[TItem], Any],
            element_selector: Callable[[TItem], Any] | _Sentinel = _SENTINEL,
    ) -> dict[Any, Any]:
        return FlpIt(self.__list.data).to_dictionary(key_selector, element_selector)

    def to_list(self) -> FlpList[TItem]:
        """Explicitly returns a shallow copy instance to isolate mutations."""
        return FlpList(self.__list.data.copy())
    def to_list(self) -> FlpList[TItem]:
        """Explicitly returns a shallow copy instance to isolate mutations."""
        return FlpList(self.__list.data.copy())

    # =====================================================================
    # 5. json serialization
    # =====================================================================

    @classmethod
    def from_json[T](cls, data: str | bytes, item_type: type[T], jso: JsonSerializerOptions|None=None) -> FlpList[T]:
        return FlpList[T](JsonConvert.deserialize(data, list[item_type], jso))

    def to_json_bytes[T](self, item_type: type[T], jso: JsonSerializerOptions|None=None) -> bytes:
        return JsonConvert.serialize_bytes(self.__list.data, list[item_type], jso)

    def to_json[T](self, item_type: type[T], jso: JsonSerializerOptions|None=None) -> str:
        return JsonConvert.serialize(self.__list.data, list[item_type], jso)

    def write_json[T](
            self,
            item_type: type[T],
            output: BinaryIO,
            jso: JsonSerializerOptions | None = None,
    ) -> None:
        JsonConvert.serialize_to(self, item_type, output, jso)

# I hate it, but Python being Python
from ._grouping import Grouping
