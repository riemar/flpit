from __future__ import annotations

import builtins
from functools import wraps
from itertools import islice

from collections import UserList
from typing import (
    Any,
    Callable,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Type,
    TypeVar,
    Union,
    overload,
    cast as typing_cast,
)

TItem = TypeVar("TItem")
TResult = TypeVar("TResult")
TKey = TypeVar("TKey")
TOther = TypeVar("TOther")
TAccumulate = TypeVar("TAccumulate")

_SENTINEL = object()

class EmptySequenceError(ValueError):
    def __init__(self, message="Sequence contains no elements"):
        super().__init__(message)

def _guard_empty(func: Callable[..., Any]) -> Callable[..., Any]:
    """Catches Python's native empty-sequence ValueError and re-raises LINQ-compliant error."""
    @wraps(func)
    def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return func(self, *args, **kwargs)
        except ValueError as e:
            if not self.data:
                raise EmptySequenceError() from e
            raise
    return wrapper

class FlpIt(Iterable[TItem], Generic[TItem]):
    """
    | Fluent Iterable
    Lazy evaluation wrapper around an iterable (matching .NET IEnumerable<T>). No internal caching.
    """
    __slots__ = ("_iterable",)

    def __init__(self, iterable: Iterable[TItem]) -> None:
        self._iterable: Iterable[TItem] = iterable

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

        return FlpIt(_generator())

    def prepend(self, element: TItem) -> FlpIt[TItem]:
        """Prepends an element to the beginning of the sequence (deferred)."""
        def _generator() -> Iterator[TItem]:
            yield element
            yield from self

        return FlpIt(_generator())

    def where(self, predicate: Callable[[TItem], bool]) -> FlpIt[TItem]:
        """Filters elements based on a predicate."""
        return FlpIt(item for item in self if predicate(item))

    def select(self, selector: Callable[[TItem], TResult]) -> FlpIt[TResult]:
        """Projects each element into a new form."""
        return FlpIt(selector(item) for item in self)

    def select_many(
            self, selector: Callable[[TItem], Iterable[TResult]]
    ) -> FlpIt[TResult]:
        """Flattens sequence projections."""

        def _generator() -> Iterator[TResult]:
            for item in self:
                yield from selector(item)

        return FlpIt(_generator())

    def take(self, count: int) -> FlpIt[TItem]:
        """Returns a specified number of contiguous elements from the start."""
        if count <= 0:
            return FlpIt(())
        return FlpIt(islice(self, count))

    def cast(self, target_type: Type[TResult]) -> FlpIt[TResult]:
        """Casts elements to a specified type or raises TypeError if cast fails."""

        def _generator() -> Iterator[TResult]:
            for item in self:
                if not isinstance(item, target_type):
                    raise TypeError(
                        f"Cannot cast element {item!r} of type {type(item).__name__} to {target_type.__name__}"
                    )
                yield item  # type: ignore[misc]

        return FlpIt(_generator())

    def of_type(self, target_type: Type[TResult]) -> FlpIt[TResult]:
        """Filters the elements of an Iterable based on a specified type."""

        def _generator() -> Iterator[TResult]:
            for item in self:
                if isinstance(item, target_type):
                    yield item  # type: ignore[misc]

        return FlpIt(_generator())

    def distinct(self) -> FlpIt[TItem]:
        """Returns distinct elements from a sequence by using O(1) set lookups."""

        def _generator() -> Iterator[TItem]:
            seen: Set[TItem] = set()
            for item in self:
                if item not in seen:
                    seen.add(item)
                    yield item

        return FlpIt(_generator())

    def distinct_by(
            self, key_selector: Callable[[TItem], TKey]
    ) -> FlpIt[TItem]:
        """Returns distinct elements from a sequence according to a specified key selector function via O(1) set lookups."""

        def _generator() -> Iterator[TItem]:
            seen: Set[TKey] = set()
            for item in self:
                key = key_selector(item)
                if key not in seen:
                    seen.add(key)
                    yield item

        return FlpIt(_generator())

    def zip(
            self,
            second: Iterable[TOther],
            result_selector: Optional[Callable[[TItem, TOther], TResult]] = None,
    ) -> FlpIt[Any]:
        """Applies a specified function to the corresponding elements of two sequences, producing a sequence of the results."""

        def _generator() -> Iterator[Any]:
            for first_item, second_item in zip(self, second):
                if result_selector is not None:
                    yield result_selector(first_item, second_item)
                else:
                    yield first_item, second_item

        return FlpIt(_generator())

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

        return FlpIt(_generator())

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

        return FlpIt(_generator())

    def join(
            self,
            inner: Iterable[TOther],
            outer_key_selector: Callable[[TItem], TKey],
            inner_key_selector: Callable[[TOther], TKey],
            result_selector: Callable[[TItem, TOther], TResult],
    ) -> FlpIt[TResult]:
        """Correlates elements of two sequences based on matching keys (Hash Join)."""

        def _generator() -> Iterator[TResult]:
            lookup: dict[TKey, List[TOther]] = {}
            for inner_item in inner:
                key = inner_key_selector(inner_item)
                lookup.setdefault(key, []).append(inner_item)

            for outer_item in self:
                key = outer_key_selector(outer_item)
                if key in lookup:
                    for inner_item in lookup[key]:
                        yield result_selector(outer_item, inner_item)

        return FlpIt(_generator())

    # --- Immediate Execution (Materialization & Aggregation) ---

    @overload
    def aggregate(self, func: Callable[[TItem, TItem], TItem]) -> TItem: ...

    @overload
    def aggregate(
            self, func: Callable[[TAccumulate, TItem], TAccumulate], seed: TAccumulate
    ) -> TAccumulate: ...

    def aggregate(
            self,
            func: Callable[[Any, TItem], Any],
            seed: Any = _SENTINEL,
    ) -> Any:
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

    def min(self) -> TItem:
        """Returns the minimum value in a sequence."""
        try:
            return min(self)  # type: ignore[type-var]
        except ValueError:
            raise EmptySequenceError()

    def min_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        """Returns the value in a sequence that has the minimum key value."""
        try:
            return min(self, key=key_selector)
        except ValueError:
            raise EmptySequenceError()

    def max(self) -> TItem:
        """Returns the maximum value in a sequence."""
        try:
            return max(self)  # type: ignore[type-var]
        except ValueError:
            raise EmptySequenceError()

    def max_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        """Returns the value in a sequence that has the maximum key value."""
        try:
            return max(self, key=key_selector)
        except ValueError:
            raise EmptySequenceError()

    def average(
            self, selector: Optional[Callable[[TItem], Union[int, float]]] = None
    ) -> float:
        """Computes the arithmetic mean of the sequence, optionally applying a selector."""
        total = 0.0
        count = 0
        query = (selector(x) for x in self) if selector is not None else self
        for item in query:
            total += float(item)  # type: ignore[arg-type]
            count += 1
        if count == 0:
            raise EmptySequenceError()
        return total / count

    avg = average

    def average_by(self, key_selector: Callable[[TItem], Union[int, float]]) -> float:
        """Computes the average of a sequence of numeric values projected by a key selector."""
        total = 0.0
        count = 0
        for item in self:
            total += float(key_selector(item))
            count += 1
        if count == 0:
            raise EmptySequenceError()
        return total / count

    avg_by = average_by

    def sum(
            self, selector: Optional[Callable[[TItem], Union[int, float]]] = None
    ) -> Union[int, float]:
        """Calculates the sum of the sequence, optionally applying a selector."""
        if selector is not None:
            return sum(selector(x) for x in self._iterable)
        return sum(self._iterable)

    def count(self, predicate: Optional[Callable[[TItem], bool]] = None) -> int:
        """Counts elements in the sequence matching an optional predicate."""
        query = self.where(predicate) if predicate else self
        return sum(1 for _ in query)

    def element_at(self, index: int) -> TItem:
        """Returns the element at a specified index in a sequence."""
        if index < 0:
            raise IndexError("Index out of range")
        for i, item in enumerate(self):
            if i == index:
                return item
        raise IndexError("Index out of range")

    def first(self, predicate: Optional[Callable[[TItem], bool]] = None) -> TItem:
        """Returns the first element matching a predicate, or raises ValueError."""
        query = self.where(predicate) if predicate else self
        for item in query:
            return item
        raise ValueError("Sequence contains no matching elements")

    def first_or_default(
            self, default: TResult, predicate: Optional[Callable[[TItem], bool]] = None
    ) -> Union[TItem, TResult]:
        """Returns the first element matching a predicate, or a default value."""
        try:
            return self.first(predicate)
        except ValueError:
            return default

    def single(self, predicate: Optional[Callable[[TItem], bool]] = None) -> TItem:
        """Returns the single, unique element matching a predicate."""
        query = self.where(predicate) if predicate else self
        it = iter(query)
        try:
            first_val = next(it)
        except StopIteration:
            raise ValueError("Sequence contains no matching elements")

        try:
            next(it)
        except StopIteration:
            return first_val

        raise ValueError("Sequence contains more than one matching element")

    def to_list(self) -> FlpList[TItem]:
        """Explicitly materializes the query into a FlpList."""
        return FlpList(self)


class OrderedIt(FlpIt[TItem]):
    """
    | Ordered Iterable
    Represents a sorted sequence (matching .NET IOrderedEnumerable<T>). Supports then_by chaining.
    """
    __slots__ = ("_source", "_comparers")

    def __init__(
            self,
            source: Iterable[TItem],
            key_selector: Callable[[TItem], Any],
            descending: bool = False,
    ) -> None:
        super().__init__(source)
        self._source: Iterable[TItem] = source
        self._comparers: list[tuple[Callable[[TItem], Any], bool]] = [
            (key_selector, descending)
        ]

    def then_by(self, key_selector: Callable[[TItem], Any]) -> OrderedIt[TItem]:
        """Performs a subsequent ordering in ascending order."""
        new_ordered = OrderedIt(self._source, key_selector, descending=False)
        new_ordered._comparers = self._comparers + [(key_selector, False)]
        return new_ordered

    def then_by_descending(self, key_selector: Callable[[TItem], Any]) -> OrderedIt[TItem]:
        """Performs a subsequent ordering in descending order."""
        new_ordered = OrderedIt(self._source, key_selector, descending=True)
        new_ordered._comparers = self._comparers + [(key_selector, True)]
        return new_ordered

    def __iter__(self) -> Iterator[TItem]:
        # Deferred evaluation: sorting occurs only upon iteration using multi-pass stable sort
        items = list(self._source)
        for key_selector, descending in reversed(self._comparers):
            items.sort(key=key_selector, reverse=descending)
        return iter(items)


class Grouping(FlpIt[TItem], Generic[TKey, TItem]):
    """Represents a collection of elements sharing a common key (.NET IGrouping<TKey, TElement>)."""

    __slots__ = ("_key",)

    def __init__(self, key: TKey, elements: Iterable[TItem]) -> None:
        self._key: TKey = key
        super().__init__(elements)

    @property
    def key(self) -> TKey:
        return self._key

    def __repr__(self) -> str:
        return f"Grouping(key={self.key!r}, elements={self.to_list()!r})"


class FlpList(UserList[TItem], Sequence[TItem], Generic[TItem]):
    """
    | Fluent List
    A materialized list extending UserList that yields lazy FlpIt instances for query operations.
    """

    def add(self, item: TItem) -> None:
        """Adds an item and performs O(1) type consistency check against the first element."""
        if self.data and not isinstance(item, type(self.data[0])):
            raise TypeError(
                f"Element of type '{type(item).__name__}' does not match "
                f"list item type '{type(self.data[0]).__name__}'."
            )
        self.data.append(item)

    def add_range(self, items: Iterable[TItem]) -> None:
        """Adds a sequence of items and performs O(1) type checking on the first incoming element."""
        it = iter(items)
        try:
            first_item = next(it)
        except StopIteration:
            return

        if self.data and not isinstance(first_item, type(self.data[0])):
            raise TypeError(
                f"Element of type '{type(first_item).__name__}' does not match "
                f"list item type '{type(self.data[0]).__name__}'."
            )

        self.data.append(first_item)
        self.data.extend(it)

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

    def zip(
            self,
            second: Iterable[TOther],
            result_selector: Optional[Callable[[TItem, TOther], TResult]] = None,
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

    def join(
            self,
            inner: Iterable[TOther],
            outer_key_selector: Callable[[TItem], TKey],
            inner_key_selector: Callable[[TOther], TKey],
            result_selector: Callable[[TItem, TOther], TResult],
    ) -> FlpIt[TResult]:
        return FlpIt(self.data).join(
            inner, outer_key_selector, inner_key_selector, result_selector
        )

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
    ) -> Any:
        return FlpIt(self.data).aggregate(func, seed=seed)

    @_guard_empty
    def min(self) -> TItem:
        return builtins.min(self.data)

    @_guard_empty
    def min_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        return builtins.min(self.data, key=key_selector)

    @_guard_empty
    def max(self) -> TItem:
        return builtins.max(self.data)

    @_guard_empty
    def max_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        return builtins.max(self.data, key=key_selector)

    def sum(
            self, selector: Optional[Callable[[TItem], Union[int, float]]] = None
    ) -> Union[int, float]:
        """Calculates the sum of elements, optionally applying a selector."""
        if selector is not None:
            return builtins.sum(selector(x) for x in self.data)
        return builtins.sum(self.data)

    def average(
            self, selector: Optional[Callable[[TItem], Union[int, float]]] = None
    ) -> float:
        """Calculates the arithmetic mean, optionally applying a selector."""
        if not self.data:
            raise EmptySequenceError()

        if selector is not None:
            return builtins.sum(selector(x) for x in self.data) / len(self.data)
        return builtins.sum(self.data) / len(self.data)

    def count(self, item: Any = _SENTINEL) -> int:
        if item is _SENTINEL:
            return len(self.data)

        if callable(item):
            predicate = typing_cast(Callable[[TItem], bool], item)
            return FlpIt(self.data).count(predicate)

        return self.data.count(item)

    def element_at(self, index: int) -> TItem:
        if index < 0:
            raise IndexError("Index out of range")
        return self.data[index]

    def first(self, predicate: Optional[Callable[[TItem], bool]] = None) -> TItem:
        return FlpIt(self.data).first(predicate)

    def first_or_default(
            self, default: TResult, predicate: Optional[Callable[[TItem], bool]] = None
    ) -> Union[TItem, TResult]:
        return FlpIt(self.data).first_or_default(default, predicate)

    def single(self, predicate: Optional[Callable[[TItem], bool]] = None) -> TItem:
        return FlpIt(self.data).single(predicate)

    def to_list(self) -> FlpList[TItem]:
        return self