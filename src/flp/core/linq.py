from __future__ import annotations

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

        return FlpIt(_FactoryIterable(_generator))

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
            result_selector: Optional[Callable[[TItem, TOther], Any]] = None,
    ) -> FlpIt[Any]:
        """Applies a specified function to corresponding elements of two sequences."""
        def _generator() -> Iterator[Any]:
            for first_item, second_item in zip(self, second):
                if result_selector is not None:
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
            return builtins.min(self)  # type: ignore[type-var]
        except ValueError:
            raise EmptySequenceError()

    def min_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        """Returns the value in a sequence that has the minimum key value."""
        try:
            return builtins.min(self, key=key_selector)
        except ValueError:
            raise EmptySequenceError()

    def max(self) -> TItem:
        """Returns the maximum value in a sequence."""
        try:
            return builtins.max(self)  # type: ignore[type-var]
        except ValueError:
            raise EmptySequenceError()

    def max_by(self, key_selector: Callable[[TItem], Any]) -> TItem:
        """Returns the value in a sequence that has the maximum key value."""
        try:
            return builtins.max(self, key=key_selector)
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
            return builtins.sum(selector(x) for x in self)
        return builtins.sum(self)  # type: ignore[arg-type]

    def count(self, predicate: Optional[Callable[[TItem], bool]] = None) -> int:
        """Counts elements in the sequence matching an optional predicate."""
        query = self.where(predicate) if predicate else self
        return builtins.sum(1 for _ in query)

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


from threading import Lock

class OrderedIt(FlpIt[TItem]):
    """
    Ordered Iterable.

    Sorts the source lazily on first iteration and caches the resulting order.
    The source is consumed at most once; subsequent iterations reuse the cached
    result.
    """

    __slots__ = (
        "_source",
        "_key_selector",
        "_descending",
        "_parent",
        "_cached_result",
        "_lock",
    )

    def __init__(
            self,
            source: Iterable[TItem],
            key_selector: Callable[[TItem], Any],
            descending: bool = False,
            parent: Optional["OrderedIt[TItem]"] = None,
    ) -> None:
        super().__init__(source)

        self._source = source
        self._key_selector = key_selector
        self._descending = descending
        self._parent = parent

        self._cached_result: Optional[list[TItem]] = None
        self._lock = Lock()

    def then_by(
            self,
            key_selector: Callable[[TItem], Any],
    ) -> "OrderedIt[TItem]":
        return OrderedIt(
            self._source,
            key_selector,
            descending=False,
            parent=self,
        )

    def then_by_descending(
            self,
            key_selector: Callable[[TItem], Any],
    ) -> "OrderedIt[TItem]":
        return OrderedIt(
            self._source,
            key_selector,
            descending=True,
            parent=self,
        )

    def __iter__(self) -> Iterator[TItem]:
        cached = self._cached_result

        if cached is None:
            with self._lock:
                cached = self._cached_result

                if cached is None:
                    # Collect the complete ordering chain.
                    comparers: list[
                        tuple[Callable[[TItem], Any], bool]
                    ] = []

                    node: Optional["OrderedIt[TItem]"] = self

                    while node is not None:
                        comparers.append(
                            (node._key_selector, node._descending)
                        )
                        node = node._parent

                    comparers.reverse()

                    # Consume the source exactly once.
                    items = list(self._source)

                    class SortWrapper:
                        __slots__ = ("obj", "keys")

                        def __init__(self, obj: Any) -> None:
                            self.obj = obj
                            self.keys = [
                                selector(obj)
                                for selector, _ in comparers
                            ]

                        def __lt__(self, other: "SortWrapper") -> bool:
                            for index, (_, descending) in enumerate(comparers):
                                left = self.keys[index]
                                right = other.keys[index]

                                if left == right:
                                    continue

                                return right < left if descending else left < right

                            return False

                    wrapped_items = [
                        SortWrapper(item)
                        for item in items
                    ]

                    wrapped_items.sort()

                    # Store ONLY the actual result objects.
                    cached = [
                        wrapper.obj
                        for wrapper in wrapped_items
                    ]

                    self._cached_result = cached

                    # Important: __iter__ is a generator function.
                    # Release potentially large temporary structures
                    # before yielding anything.
                    del wrapped_items
                    del items
                    del comparers

        yield from cached


class Grouping(FlpIt[TItem], Generic[TKey, TItem]):
    """Represents a collection of elements sharing a common key (.NET IGrouping<TKey, TElement>)."""
    __slots__ = ("_key")

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

    def to_list(self) -> "FlpList[TItem]":
        """Explicitly returns a new shallow copy instance to isolate mutations matching .NET."""
        return FlpList(self.data.copy())

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
            result_selector: Optional[Callable[[TItem, TOther], Any]] = None,
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
        return FlpIt(self.data).sum(selector)

    def average(
            self, selector: Optional[Callable[[TItem], Union[int, float]]] = None
    ) -> float:
        """Calculates the arithmetic mean, optionally applying a selector."""
        return FlpIt(self.data).average(selector)

    # --- Overloads for the Type System ---
    # 1. Native compatibility path (MUST be first): exact value match
    @overload
    def count(self, item: TItem) -> int: ...

    # 2. LINQ style path: matching via predicate function
    @overload
    def count(self, item: Callable[[TItem], bool]) -> int: ...

    # 3. LINQ style path: no arguments (counts everything)
    @overload
    def count(self) -> int: ...

    # --- The Clean Implementation ---
    # We name the parameter 'item' to perfectly match UserList, but default it to None
    def count(self, item: Any = _SENTINEL) -> int:
        """Counts elements in the list matching an optional predicate or exact value."""
        # Scenario C: No argument passed (.count()) -> Return total length
        if item is _SENTINEL:
            return len(self.data)

        # Scenario A: A LINQ predicate function was passed
        if callable(item):
            return FlpIt(self.data).count(item)

        # Scenario B: An exact raw value was passed (.count(4))
        # Invokes the original parent implementation of UserList to remain 100% compliant
        return super().count(item)

    def element_at(self, index: int) -> TItem:
        if index < 0 or index >= len(self.data):
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
        """Explicitly returns a shallow copy instance to isolate mutations."""
        return FlpList(self.data.copy())