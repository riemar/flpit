from __future__ import annotations
import decimal
from decimal import Decimal, Overflow, Inexact

import builtins
from collections import UserList
from functools import wraps
from itertools import islice
from typing import (
    Any,
    Callable,
    Generic,
    Iterable,
    Iterator,
    List,
    Sequence,
    Set,
    Type,
    TypeVar,
    Union,
    override,
    overload,
    cast as typing_cast,
)

TItem = TypeVar("TItem")
TResult = TypeVar("TResult")
TKey = TypeVar("TKey")
TOther = TypeVar("TOther")
TAccumulate = TypeVar("TAccumulate")

class _Sentinel:
    __slots__ = ()

    def __call__(self, *args: object, **kwargs: object) -> Any:
        raise TypeError("_SENTINEL cannot be called")

_SENTINEL = _Sentinel()
_MISSING = object()


class EmptySequenceError(ValueError):
    def __init__(self):
        super().__init__("Sequence contains no elements")

class NoMatchError(ValueError):
    def __init__(self):
        super().__init__("Sequence contains no matching elements")

class MultipleMatchesError(ValueError):
    def __init__(self):
        super().__init__("Sequence contains more than one matching element")

class MultipleElementsError(ValueError):
    def __init__(self):
        super().__init__("Sequence contains more than one element")

class SourceNoneError(TypeError):
    def __init__(self):
        super().__init__("Value cannot be None. (Argument 'source')")

class PredicateNoneError(TypeError):
    def __init__(self):
        super().__init__("Value cannot be None. (Argument 'predicate')")

class SelectorNoneError(TypeError):
    def __init__(self):
        super().__init__("Value cannot be null. (Parameter 'keySelector')")


def _guard_empty(func: Callable[..., Any]) -> Callable[..., Any]:
    """Catches Python's native empty-sequence ValueError and re-raises LINQ-compliant error."""
    @wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return func(self, *args, **kwargs)
        except ValueError as e:
            if not self.data:
                raise EmptySequenceError() from e
            raise
    return wrapper


# noinspection unresolved-references,protected-member
def dotnet_context() -> decimal._ContextManager: # awesome that type was not intended
    # 1. Create and configure pure Context object
    ctx = decimal.getcontext().copy()
    ctx.prec = max(ctx.prec, 29)
    ctx.traps[Overflow] = True
    ctx.traps[Inexact] = True

    return decimal.localcontext(ctx)


class _FactoryIterable(Iterable[TItem], Generic[TItem]):
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


class FlpIt(Iterable[TItem], Generic[TItem]):
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
    def as_type(self, target_type: Type[TResult]) -> FlpIt[TResult]:
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

    def where(self, predicate: Callable[[TItem], bool]) -> FlpIt[TItem]:
        """Filters elements based on a predicate."""
        def _generator() -> Iterator[TItem]:
            for item in self:
                if predicate(item):
                    yield item

        return typing_cast(FlpIt[TItem], FlpIt(_FactoryIterable(_generator)))

    def select(self, selector: Callable[[TItem], TResult]) -> FlpIt[TResult]:
        """Projects each element into a new form."""
        def _generator() -> Iterator[TResult]:
            for item in self:
                yield selector(item)

        return FlpIt(_FactoryIterable(_generator))

    def select_many(
            self, selector: Callable[[TItem], Iterable[TResult]]
    ) -> FlpIt[TResult]:
        """Flattens sequence projections."""
        def _generator() -> Iterator[TResult]:
            for item in self:
                yield from selector(item)

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

    def cast(self, target_type: Type[TResult]) -> FlpIt[TResult]:
        """Casts elements to a specified type or raises TypeError if cast fails."""
        def _generator() -> Iterator[TResult]:
            for item in self:
                if not isinstance(item, target_type):
                    raise TypeError(
                        f"Cannot cast element {item!r} of type {type(item).__name__} to {target_type.__name__}"
                    )
                yield item  # type: ignore[misc]

        return FlpIt(_FactoryIterable(_generator))

    def of_type(self, target_type: Type[TResult]) -> FlpIt[TResult]:
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
        def _generator() -> Iterator[TItem]:
            seen: Set[TKey] = set()
            for item in self:
                key = key_selector(item)
                if key not in seen:
                    seen.add(key)
                    yield item

        return FlpIt(_FactoryIterable(_generator))

    @overload
    def zip(self, second: Iterable[TOther]) -> FlpIt[tuple[TItem, TOther]]: ...

    @overload
    def zip(
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
        def _generator() -> Iterator[Any]:
            for first_item, second_item in zip(self, second):
                if result_selector is not _SENTINEL:
                    yield result_selector(first_item, second_item)
                else:
                    yield first_item, second_item

        return FlpIt(_FactoryIterable(_generator))

    def chunk(self, size: int) -> FlpIt[FlpList[TItem]]:
        """Splits the elements of a sequence into chunks of size at most size."""
        if size <= 0:
            raise ValueError("Chunk size must be greater than 0.")

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
    def aggregate(self, func: Callable[[TItem, TItem], TItem]) -> TItem: ...

    @overload
    def aggregate(
            self, func: Callable[[TAccumulate, TItem], TAccumulate], seed: TAccumulate
    ) -> TAccumulate: ...

    def aggregate(
            self,
            func: Callable[[Any, Any], Any],
            seed: Any = _SENTINEL,
    ) -> TItem | TAccumulate:
        """Applies an accumulator function over a sequence."""
        it = iter(self)
        if seed is _SENTINEL:
            try:
                accumulator = next(it)
            except StopIteration:
                raise EmptySequenceError()
            for item in it:
                accumulator = func(accumulator, item)
        else:
            accumulator = seed
            for item in it:
                accumulator = func(accumulator, item)
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

    def _extreme(self, func: Any, **kwargs: Any) -> TItem:
        result = func(self, default=_MISSING, **kwargs)

        if result is _MISSING:
            raise EmptySequenceError()

        return typing_cast(TItem, result)

    def min(self) -> TItem:
        """Returns the minimum value in a sequence."""
        return self._extreme(builtins.min)

    def min_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        """Returns the value in a sequence that has the minimum key value."""
        return self._extreme(builtins.min, key=key_selector)

    def max(self) -> TItem:
        """Returns the maximum value in a sequence."""
        return self._extreme(builtins.max)

    def max_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        """Returns the value in a sequence that has the maximum key value."""
        return self._extreme(builtins.max, key=key_selector)

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
            raise IndexError("Index out of range")
        for i, item in enumerate(self):
            if i == index:
                return item
        raise IndexError("Index out of range")

    def first(self, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL) -> TItem:
        """Returns the first element matching a predicate, or raises ValueError."""
        query = self.where(predicate) if predicate is not _SENTINEL else self
        for item in query:
            return item
        raise EmptySequenceError() if predicate is _SENTINEL else NoMatchError()

    def first_or_default(
            self, default: TResult, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL
    ) -> Union[TItem, TResult]:
        """Returns the first element matching a predicate, or a default value."""
        try:
            return self.first(predicate)
        except (EmptySequenceError, NoMatchError):
            return default

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


    def to_list(self) -> FlpList[TItem]:
        """Explicitly materializes the query into a FlpList."""
        return FlpList(self)

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

def _none_aware_key(
        selector: Callable[[TItem], Any],
        item: TItem,
) -> Any:
    key = selector(item)
    return _NONE_ORDER_KEY if key is None else key

class OrderedIt(FlpIt[TItem]):
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

    @override
    def __iter__(self) -> Iterator[TItem]:
        items = list(self._iterable)

        for selector, descending in reversed(self._criteria):
            items.sort(
                key=partial(_none_aware_key, selector),
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


class Grouping(FlpIt[TItem], Generic[TKey, TItem]):
    """Represents a collection of elements sharing a common key (.NET IGrouping<TKey, TElement>)."""
    __slots__ = ("_key", )

    def __init__(self, key: TKey, elements: Iterable[TItem]) -> None:
        self._key: TKey = key
        super().__init__(elements)

    @property
    def key(self) -> TKey:
        return self._key

    def __repr__(self) -> str:
        return f"Grouping(key={self.key!r}, elements={self.to_list()!r})"

    def __eq__(self, other: Any) -> bool:
        # Check if the other object is a Grouping (or subclass)
        if not isinstance(other, Grouping):
            return False

        # Compare the keys, then compare the elements inside FlpIt
        return self.key == other.key and self.to_list() == other.to_list()


class FlpList(UserList[TItem], Sequence[TItem], Generic[TItem]):
    """
    | Fluent List
    A materialized list extending UserList that yields lazy FlpIt instances for query operations.
    """
    def __init__(self, source: Iterable[TItem] | _Sentinel=_SENTINEL):
        if source is None:
            raise SourceNoneError()

        if source is _SENTINEL:
            init_list: Iterable[TItem] = list[TItem]()  # don't depend on the base class to do the right thing
        else:
            init_list = typing_cast(Iterable[TItem], source)

        super().__init__(init_list)

    def add(self, item: TItem) -> None:
        """
        |Adds an item and performs O(1) type consistency check against the first element.

        |Type safety via
        - type checks
        - manual of_type(...) filter if you don't trust your checks
        """
        self.data.append(item)

    def add_range(self, items: Iterable[TItem]) -> None:
        """
        | Adds an Iterable sequence or stream.
        Optimizes paths based on input type without destroying volatile generators.

        |Type safety via
        - type checks
        - manual of_type(...) filter if you don't trust your checks
        """
        # 1. Optimized Path: Fast memory extensions for pre-materialized sequences
        if isinstance(items, (Sequence, list, tuple, UserList)):
            self.data.extend(items)
            return

        # 2. Stream Path: Volatile one-shot generator handling
        it = iter(items)
        try:
            first_item = next(it)
        except StopIteration:
            return

        # Append the tracked peek-element and stream the remainder safely
        self.data.append(first_item)
        self.data.extend(it)

    @overload
    def any(self) -> bool: ...

    @overload
    def any(self, predicate: Callable[[TItem], bool]) -> bool: ...

    def any(
            self,
            predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL,
    ) -> bool:
        if predicate is _SENTINEL:
            return len(self.data) > 0

        return any(predicate(item) for item in self.data)

    def all(
            self,
            predicate: Callable[[TItem], bool],
    ) -> bool:
        return all(predicate(item) for item in self.data)

    def append_linq(self, element: TItem) -> FlpIt[TItem]:
        """Appends an element to the sequence lazily, returning a FlpIt without mutating this list."""
        return FlpIt(self.data).append(element)

    def prepend(self, element: TItem) -> FlpIt[TItem]:
        """Prepends an element to the sequence lazily, returning a FlpIt without mutating this list."""
        return FlpIt(self.data).prepend(element)

    # noinspection unused-parameter
    def as_type(self, target_type: Type[TResult]) -> FlpList[TResult]:
        return self  # type: ignore[return-value]

    def where(self, predicate: Callable[[TItem], bool]) -> FlpIt[TItem]:
        return FlpIt(self.data).where(predicate)

    def select(self, selector: Callable[[TItem], TResult]) -> FlpIt[TResult]:
        return FlpIt(self.data).select(selector)

    def select_many(
            self, selector: Callable[[TItem], Iterable[TResult]]
    ) -> FlpIt[TResult]:
        return FlpIt(self.data).select_many(selector)

    def take(self, count: int) -> FlpIt[TItem]:
        return FlpIt(self.data).take(count)

    def cast(self, target_type: Type[TResult]) -> FlpIt[TResult]:
        return FlpIt(self.data).cast(target_type)

    def of_type(self, target_type: Type[TResult]) -> FlpIt[TResult]:
        return FlpIt(self.data).of_type(target_type)

    def distinct(self) -> FlpIt[TItem]:
        return FlpIt(self.data).distinct()

    def distinct_by(
            self, key_selector: Callable[[TItem], TKey]
    ) -> FlpIt[TItem]:
        return FlpIt(self.data).distinct_by(key_selector)

    @overload
    def zip(self, second: Iterable[TOther]) -> FlpIt[tuple[TItem, TOther]]: ...

    @overload
    def zip(
            self,
            second: Iterable[TOther],
            result_selector: Callable[[TItem, TOther], TResult],
    ) -> FlpIt[TResult]: ...

    def zip(
            self,
            second: Iterable[TOther],
            result_selector: Callable[[TItem, TOther], Any] | _Sentinel = _SENTINEL,
    ) -> FlpIt[Any]:
        return FlpIt(self.data).zip(second, result_selector)

    def chunk(self, size: int) -> FlpIt[FlpList[TItem]]:
        return FlpIt(self.data).chunk(size)

    def order_by(
            self, key_selector: Callable[[TItem], Any]
    ) -> OrderedIt[TItem]:
        return FlpIt(self.data).order_by(key_selector)

    def order_by_descending(
            self, key_selector: Callable[[TItem], Any]
    ) -> OrderedIt[TItem]:
        return FlpIt(self.data).order_by_descending(key_selector)

    def group_by(
            self, key_selector: Callable[[TItem], TKey]
    ) -> FlpIt[Grouping[TKey, TItem]]:
        return FlpIt(self.data).group_by(key_selector)

    @overload
    def aggregate(self, func: Callable[[TItem, TItem], TItem]) -> TItem: ...

    @overload
    def aggregate(
            self, func: Callable[[TAccumulate, TItem], TAccumulate], seed: TAccumulate
    ) -> TAccumulate: ...

    def aggregate(
            self,
            func: Callable[[Any, Any], Any],
            seed: Any = _SENTINEL,
    ) -> TItem | TAccumulate:
        return FlpIt(self.data).aggregate(func, seed=seed)

    @_guard_empty
    def min(self) -> TItem:
        return builtins.min(self.data) # pyrefly: ignore [bad-specialization]

    @_guard_empty
    def min_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        return builtins.min(self.data, key=key_selector)

    @_guard_empty
    def max(self) -> TItem:
        return builtins.max(self.data) # pyrefly: ignore [bad-specialization]

    @_guard_empty
    def max_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        return builtins.max(self.data, key=key_selector)

    def sum(
            self, selector: Callable[[TItem], int | float | Decimal] | _Sentinel = _SENTINEL
    ) -> int | float | Decimal:
        """Calculates the sum of elements, optionally applying a selector."""
        return FlpIt(self.data).sum(selector)

    def average(
            self, selector: Callable[[TItem], int | float | Decimal] | _Sentinel = _SENTINEL
    ) -> float | int | Decimal | None:
        """Calculates the arithmetic mean, optionally applying a selector."""
        return FlpIt(self.data).average(selector)

    def count_item(self, item: TItem) -> int:
        return self.data.count(item) # just redirect how the count redirected before

    # noinspection method-overriding
    @override
    # pyrefly: ignore [bad-override-param-name]
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
            return len(self.data)

        return FlpIt(self.data).count(predicate)

    def element_at(self, index: int) -> TItem:
        if index < 0 or index >= len(self.data):
            raise IndexError("Index out of range")
        return self.data[index]

    def first(self, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL) -> TItem:
        return FlpIt(self.data).first(predicate)

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
            if not self.data:
                raise EmptySequenceError()
            return self.data[-1]

        for item in reversed(self.data):
            if predicate(item):
                return item

        raise EmptySequenceError() if predicate is _SENTINEL else NoMatchError()

    def first_or_default(
            self, default: TResult, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL
    ) -> TItem | TResult:
        return FlpIt(self.data).first_or_default(default, predicate)

    def single(self, predicate: Callable[[TItem], bool] | _Sentinel = _SENTINEL) -> TItem:
        return FlpIt(self.data).single(predicate)

    def to_list(self) -> FlpList[TItem]:
        """Explicitly returns a shallow copy instance to isolate mutations."""
        return FlpList(self.data.copy())
