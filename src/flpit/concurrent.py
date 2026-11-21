"""
Thread-safe collections for code that shares data between threads and flpit tasks.

Built on Python's dict and deque and guarded by locks, so they
behave the same on regular and free-threaded CPython.

The public API is modeled on .NET's``System.Collections.Concurrent``.

What there is:

* ``ConcurrentDictionary[K, V]``: a ``MutableMapping`` whose read-modify-write operations are
  atomic: ``get_or_add``, ``add_or_update``, ``try_update``, ``try_remove``. It is created with
  its types, ``ConcurrentDictionary[str, int]()``. The value type tells it what a callable
  passed as a value means: a factory, unless the values are callable themselves.
* ``ConcurrentQueue[T]`` (first in, first out), ``ConcurrentStack[T]`` (last in, first out) and
  ``ConcurrentBag[T]`` (no order; a thread gets its own items back first). All three are
  ``ProducerConsumerCollection``\\ s.
* ``CDict``, ``CQueue``, ``CStack``, ``CBag``: short names for the same classes.

For example::

    counts = ConcurrentDictionary[str, int]()
    counts.add_or_update(word, 1, lambda _, n: n + 1)  # no lost updates under contention

    jobs = ConcurrentQueue[Job]()
    jobs.enqueue(job)
    ok, job = jobs.try_dequeue()                       # (False, None) when empty

Conventions: ``try_*`` methods return ``(True, item)`` or ``(False, None)``. Iterating a
collection walks a snapshot taken when the iteration starts, so it never fails because
another thread changed the collection. Iterating a ``ConcurrentDictionary`` yields its keys,
as with any Python mapping; ``items()`` gives the pairs.
"""
from __future__ import annotations

import collections.abc
import threading
import types
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from contextvars import ContextVar
from typing import Annotated, Any, ForwardRef, Literal, TypeVar, Union, cast, get_args, get_origin, overload, override

from flpit.core.comparers import EqualityComparer, IEqualityComparer
from flpit.core.linq import ArgumentError, ArgumentNullError, ArgumentOutOfRangeError, KeyNotFoundError

__all__ = [
    "CBag",
    "CDict",
    "CQueue",
    "CStack",
    "ConcurrentBag",
    "ConcurrentDictionary",
    "ConcurrentQueue",
    "ConcurrentStack",
    "ProducerConsumerCollection",
    "TryResult",
]

type TryResult[T] = tuple[Literal[True], T] | tuple[Literal[False], None]

_FAILED: tuple[Literal[False], None] = (False, None)


class _Missing:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<missing>"


_MISSING: Any = _Missing()


def _out_of_range(argument: str, message: str = "Specified argument was out of the range of valid values.") -> ArgumentOutOfRangeError:
    return ArgumentOutOfRangeError(argument, message)


def _validate_copy_to(array: list[Any] | None, index: int, count: int) -> None:
    if array is None:
        raise ArgumentNullError("array")
    if index < 0:
        raise _out_of_range("index", "Index is less than zero.")
    if len(array) - index < count:
        raise ArgumentError(
            "The number of elements in the collection is greater than the available space "
            "from index to the end of the destination array."
        )


def _copy_into(items: list[Any], array: list[Any] | None, index: int) -> None:
    _validate_copy_to(array, index, len(items))
    assert array is not None
    array[index:index + len(items)] = items


# =============================================================================
# ProducerConsumerCollection
# =============================================================================

class ProducerConsumerCollection[T]:
    """A thread-safe collection to add to and take from (.NET ``IProducerConsumerCollection<T>``).

    Subclasses implement ``try_add``, ``try_take``, ``to_array`` and ``__len__``; iteration
    and ``copy_to`` work on ``to_array()``.
    """

    __slots__ = ()

    def try_add(self, item: T) -> bool:
        raise NotImplementedError

    def try_take(self) -> TryResult[T]:
        raise NotImplementedError

    def to_array(self) -> list[T]:
        """A snapshot of the items, in the order ``try_take`` would return them."""
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    @property
    def count(self) -> int:
        return len(self)

    def copy_to(self, array: list[T], index: int = 0) -> None:
        """Copy a snapshot into ``array`` from ``index`` on (.NET ``CopyTo``)."""
        _copy_into(self.to_array(), array, index)

    def __iter__(self) -> Iterator[T]:
        return iter(self.to_array())

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.to_array()!r})"


def _initial_items(collection: Iterable[Any] | None) -> Iterable[Any]:
    if collection is _MISSING:
        return ()
    if collection is None:
        raise ArgumentNullError("collection")
    return collection


# =============================================================================
# ConcurrentQueue
# =============================================================================

class ConcurrentQueue[T](ProducerConsumerCollection[T]):
    """A thread-safe first in, first out queue (.NET ``ConcurrentQueue<T>``)."""

    __slots__ = ("_items",)

    def __init__(self, collection: Iterable[T] = _MISSING) -> None:
        # deque's append / popleft / [0] / copy are atomic on regular and free-threaded builds.
        self._items: deque[T] = deque(_initial_items(collection))

    def enqueue(self, item: T) -> None:
        self._items.append(item)

    def try_dequeue(self) -> TryResult[T]:
        try:
            return True, self._items.popleft()
        except IndexError:
            return _FAILED

    def try_peek(self) -> TryResult[T]:
        try:
            return True, self._items[0]
        except IndexError:
            return _FAILED

    @property
    def is_empty(self) -> bool:
        return not self._items

    def clear(self) -> None:
        self._items.clear()

    @override
    def __len__(self) -> int:
        return len(self._items)

    @override
    def to_array(self) -> list[T]:
        return list(self._items.copy())

    @override
    def try_add(self, item: T) -> bool:
        self._items.append(item)
        return True

    @override
    def try_take(self) -> TryResult[T]:
        return self.try_dequeue()


# =============================================================================
# ConcurrentStack
# =============================================================================

def _validate_range(items: list[Any] | None, start_index: int, count: int | None) -> int:
    if items is None:
        raise ArgumentNullError("items")
    length = len(items)
    if count is None:
        count = length - start_index
    if count < 0:
        raise _out_of_range("count")
    if start_index > length or start_index < 0:
        raise _out_of_range("startIndex", "The startIndex argument must be greater than or equal to zero.")
    if length - count < start_index:
        raise ArgumentError("The sum of the startIndex and count arguments must be less than or equal to the collection's Count.")
    return count


class ConcurrentStack[T](ProducerConsumerCollection[T]):
    """A thread-safe last in, first out stack (.NET ``ConcurrentStack<T>``).

    ``push_range`` / ``try_pop_range`` move several items at once: they stay adjacent.
    Enumeration and ``to_array()`` go from the top (newest) down.
    """

    __slots__ = ("_items", "_lock")

    def __init__(self, collection: Iterable[T] = _MISSING) -> None:
        self._items: list[T] = list(_initial_items(collection))  # top of the stack last
        self._lock = threading.Lock()

    def push(self, item: T) -> None:
        with self._lock:
            self._items.append(item)

    def push_range(self, items: list[T], start_index: int = 0, count: int | None = None) -> None:
        """Push ``items[start_index:start_index + count]`` atomically; the last one ends on top."""
        count = _validate_range(items, start_index, count)
        if count:
            with self._lock:
                self._items.extend(items[start_index:start_index + count])

    def try_pop(self) -> TryResult[T]:
        with self._lock:
            if self._items:
                return True, self._items.pop()
        return _FAILED

    def try_pop_range(self, items: list[T], start_index: int = 0, count: int | None = None) -> int:
        """Pop up to ``count`` items (top first) into ``items`` from ``start_index`` on; returns how many."""
        count = _validate_range(items, start_index, count)
        if not count:
            return 0
        with self._lock:
            taken = self._items[-count:]
            del self._items[-count:]
        taken.reverse()
        items[start_index:start_index + len(taken)] = taken
        return len(taken)

    def try_peek(self) -> TryResult[T]:
        try:
            return True, self._items[-1]
        except IndexError:
            return _FAILED

    @property
    def is_empty(self) -> bool:
        return not self._items

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    @override
    def __len__(self) -> int:
        return len(self._items)

    @override
    def to_array(self) -> list[T]:
        snapshot = self._items.copy()
        snapshot.reverse()
        return snapshot

    @override
    def try_add(self, item: T) -> bool:
        self.push(item)
        return True

    @override
    def try_take(self) -> TryResult[T]:
        return self.try_pop()


# =============================================================================
# ConcurrentBag
# =============================================================================

_EMPTY_ITERATOR: Iterator[Any] = iter(())


class ConcurrentBag[T](ProducerConsumerCollection[T]):
    """A thread-safe unordered collection (.NET ``ConcurrentBag<T>``).

    Every thread keeps its own items: ``try_take`` / ``try_peek`` return the calling thread's
    newest item, or else the oldest item of another thread. That makes the bag cheap for
    threads that consume what they produce. Items stay in the bag when their thread exits.
    """

    __slots__ = ("_lists", "_lock")

    def __init__(self, collection: Iterable[T] = _MISSING) -> None:
        self._lock = threading.Lock()
        self._lists: dict[int, deque[T]] = {}
        items = deque(_initial_items(collection))
        if items:
            self._lists[threading.get_ident()] = items

    def add(self, item: T) -> None:
        ident = threading.get_ident()
        with self._lock:
            local = self._lists.get(ident)
            if local is None:
                local = self._lists[ident] = deque()
            local.append(item)

    @override
    def try_take(self) -> TryResult[T]:
        return self._take_or_peek(take=True)

    def try_peek(self) -> TryResult[T]:
        return self._take_or_peek(take=False)

    def _take_or_peek(self, take: bool) -> TryResult[T]:
        ident = threading.get_ident()
        with self._lock:
            local = self._lists.get(ident)
            if local:
                return True, local.pop() if take else local[-1]
            for owner, items in self._lists.items():  # steal the oldest item of another thread
                if owner != ident and items:
                    return True, items.popleft() if take else items[0]
        return _FAILED

    @property
    def is_empty(self) -> bool:
        with self._lock:
            return not any(self._lists.values())

    def clear(self) -> None:
        with self._lock:
            for items in self._lists.values():
                items.clear()

    @override
    def __len__(self) -> int:
        with self._lock:
            return sum(map(len, self._lists.values()))

    @override
    def to_array(self) -> list[T]:
        with self._lock:
            snapshot: list[T] = []
            for items in self._lists.values():
                snapshot.extend(reversed(items))
        return snapshot

    @override
    def __iter__(self) -> Iterator[T]:
        snapshot = self.to_array()
        return iter(snapshot) if snapshot else _EMPTY_ITERATOR

    @override
    def try_add(self, item: T) -> bool:
        self.add(item)
        return True


# =============================================================================
# ConcurrentDictionary
# =============================================================================

class _Key:
    """A key compared through a custom comparer."""

    __slots__ = ("key", "_comparer", "_hash")

    def __init__(self, key: Any, comparer: IEqualityComparer[Any]) -> None:
        self.key = key
        self._comparer = comparer
        self._hash = comparer.get_hash_code(key)

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        if type(other) is not _Key:
            return NotImplemented
        return self is other or self._comparer.equals(self.key, other.key)


def _key_error(key: Any) -> ArgumentError:
    return ArgumentError(f"An item with the same key has already been added. Key: {key!r}")


# --- the value type, needed at runtime -------------------------------------------------------

_PENDING_TYPES: ContextVar[tuple[Any, ...] | None] = ContextVar("_PENDING_TYPES", default=None)


class _DictionaryAlias(types.GenericAlias):
    """``ConcurrentDictionary[K, V]``: hands ``K, V`` to the instance it creates."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:  # not in the GenericAlias stubs
        token = _PENDING_TYPES.set(self.__args__)
        try:
            return super().__call__(*args, **kwargs)
        finally:
            _PENDING_TYPES.reset(token)


def _is_callable_type(tp: Any) -> bool:
    """Whether values of type ``tp`` are callable: then a callable passed as a value is a value."""
    if tp is Any or tp is object or tp is None or tp is type(None) or isinstance(tp, TypeVar):
        return False
    if isinstance(tp, (str, ForwardRef)):
        raise TypeError(
            f"cannot tell whether {tp!r} values are callable: pass the type itself, not a string"
        )
    value = getattr(tp, "__value__", None)  # `type Alias = ...`
    if value is not None and type(tp).__name__ == "TypeAliasType":
        return _is_callable_type(value)
    supertype = getattr(tp, "__supertype__", None)  # NewType
    if supertype is not None:
        return _is_callable_type(supertype)
    origin = get_origin(tp)
    if origin is Annotated:
        return _is_callable_type(get_args(tp)[0])
    if origin is Union or origin is types.UnionType:
        return any(_is_callable_type(member) for member in get_args(tp))
    if origin is Literal:
        return any(callable(member) for member in get_args(tp))
    if tp is collections.abc.Callable or origin is collections.abc.Callable:
        return True
    if origin is not None:
        tp = origin  # list[int] -> list, type[X] -> type
    if isinstance(tp, type):
        return any("__call__" in vars(base) for base in tp.__mro__ if base is not object)
    return False


def _value_type(cls: type, pending: tuple[Any, ...] | None) -> Any:
    """``V`` for an instance of ``cls`` created with the type arguments ``pending`` (if any)."""
    if cls is ConcurrentDictionary:
        return _MISSING if pending is None else pending[1]
    for base in cls.__dict__.get("__orig_bases__", cls.__bases__):
        origin = get_origin(base) or base
        if not (isinstance(origin, type) and issubclass(origin, ConcurrentDictionary)):
            continue
        arguments = get_args(base)
        if not arguments:
            return _value_type(origin, None)
        parameters = getattr(cls, "__parameters__", ())
        if parameters:
            if pending is None or len(pending) != len(parameters):
                return _MISSING
            mapping = dict(zip(parameters, pending, strict=True))
            arguments = tuple(mapping.get(argument, argument) for argument in arguments)
        return _value_type(origin, arguments)
    return _MISSING


class ConcurrentDictionary[K, V](MutableMapping[K, V]):
    """A thread-safe dictionary (.NET ``ConcurrentDictionary<TKey, TValue>``).

    Create it with its types, ``ConcurrentDictionary[str, int]()`` (or ``CDict[str, int]()``): the
    runtime needs ``V`` to read a callable passed to ``get_or_add`` / ``add_or_update`` the way C#
    overload resolution does. A callable is a value factory, unless ``V`` is itself a callable type
    (``Callable[...]``, a class with ``__call__``): then it is the value. ``ConcurrentDictionary()``
    without types raises ``TypeError``. Subclasses like ``class Registry(ConcurrentDictionary[str,
    Handler])`` carry their types.

    ``collection`` is a mapping or an iterable of ``(key, value)`` pairs (duplicate keys raise
    ``ArgumentError``); ``comparer`` an ``IEqualityComparer`` for the keys. ``None`` is not a
    valid key (``ArgumentNullError``), as in .NET. ``concurrency_level`` and ``capacity`` are
    validated like .NET's and otherwise only hints.

    Reads (``try_get_value``, ``[key]``, ``in``) take no lock; writes are atomic. The factories
    of ``get_or_add`` / ``add_or_update`` run outside the lock: under contention they may run
    more than once, and only one result is stored (as in .NET).

    ``keys()``, ``values()`` and ``items()`` return tuples: read-only snapshots, like .NET's
    ``Keys`` / ``Values``.
    """

    __slots__ = ("_map", "_lock", "_comparer", "_wrap", "_values_are_callable")

    def __class_getitem__(cls, params: Any) -> Any:
        arguments = params if isinstance(params, tuple) else (params,)
        expected = len(getattr(cls, "__parameters__", ()))
        if expected and len(arguments) != expected:
            raise TypeError(f"Too {'few' if len(arguments) < expected else 'many'} arguments for {cls.__name__}; "
                            f"actual {len(arguments)}, expected {expected}")
        return _DictionaryAlias(cls, arguments)

    def __init__(
            self,
            collection: Mapping[K, V] | Iterable[tuple[K, V]] | None = _MISSING,
            comparer: IEqualityComparer[K] | None = None,
            *,
            concurrency_level: int = -1,
            capacity: int = 31,
    ) -> None:
        value_type = _value_type(type(self), _PENDING_TYPES.get())
        _PENDING_TYPES.set(None)  # dictionaries created inside __init__ need their own types
        if value_type is _MISSING:
            name = type(self).__name__
            example = "[str, int]" if type(self) is ConcurrentDictionary else "[...]"
            raise TypeError(f"{name} needs its type arguments, e.g. {name}{example}()")
        self._values_are_callable = _is_callable_type(value_type)
        if concurrency_level < 1 and concurrency_level != -1:
            raise _out_of_range("concurrencyLevel", "The concurrencyLevel argument must be positive.")
        if capacity < 0:
            raise _out_of_range("capacity", "The capacity argument must be greater than or equal to zero.")
        if comparer is not None and not isinstance(comparer, IEqualityComparer):
            raise TypeError("comparer must provide equals(x, y) and get_hash_code(obj)")
        self._lock = threading.Lock()
        self._map: dict[Any, V] = {}
        self._comparer: IEqualityComparer[K] = EqualityComparer.default() if comparer is None else comparer
        self._wrap: Callable[[K], Any] | None = (
            None if self._comparer is EqualityComparer.default() else self._wrap_key
        )
        if collection is not _MISSING:
            if collection is None:
                raise ArgumentNullError("collection")
            pairs: Iterable[tuple[K, V]]
            if isinstance(collection, Mapping):
                pairs = cast(Mapping[K, V], collection).items()
            else:
                pairs = cast(Iterable[tuple[K, V]], collection)
            for key, value in pairs:
                if not self.try_add(key, value):
                    raise _key_error(key)

    def _wrap_key(self, key: K) -> Any:
        return _Key(key, self._comparer)

    def _k(self, key: K, argument: str = "key") -> Any:
        if key is None:
            raise ArgumentNullError(argument)
        wrap = self._wrap
        return key if wrap is None else wrap(key)

    def _unwrap(self, stored: Any) -> K:
        return stored if self._wrap is None else stored.key

    # --- properties -------------------------------------------------------------------------

    @property
    def comparer(self) -> IEqualityComparer[K]:
        """The key comparer; ``EqualityComparer.default()`` when none was given."""
        return self._comparer

    @property
    def count(self) -> int:
        return len(self._map)

    @property
    def is_empty(self) -> bool:
        return not self._map

    # --- .NET operations --------------------------------------------------------------------

    def try_add(self, key: K, value: V) -> bool:
        """Add ``key`` unless it is present."""
        stored = self._k(key)
        with self._lock:
            if stored in self._map:
                return False
            self._map[stored] = value
            return True

    def add(self, key: K, value: V) -> None:
        """Add ``key``; raises ``ArgumentError`` if it is present (.NET ``IDictionary.Add``)."""
        if not self.try_add(key, value):
            raise _key_error(key)

    def try_get_value(self, key: K) -> TryResult[V]:
        value = self._map.get(self._k(key), _MISSING)
        if value is _MISSING:
            return _FAILED
        return True, value

    def contains_key(self, key: K) -> bool:
        return self._k(key) in self._map

    def try_remove(self, key: K) -> TryResult[V]:
        """Remove ``key``: ``(True, its value)``, or ``(False, None)`` if it was absent."""
        stored = self._k(key)
        with self._lock:
            value = self._map.pop(stored, _MISSING)
        if value is _MISSING:
            return _FAILED
        return True, value

    def contains_item(self, item: tuple[K, V]) -> bool:
        """Whether ``item[0]`` maps to a value equal to ``item[1]`` (.NET ``ICollection<KeyValuePair>.Contains``)."""
        key, value = item
        current = self._map.get(self._k(key, "item"), _MISSING)
        return current is not _MISSING and (current is value or current == value)

    def try_remove_item(self, item: tuple[K, V]) -> bool:
        """Remove ``item[0]`` only while it maps to a value equal to ``item[1]``
        (.NET ``TryRemove(KeyValuePair)``)."""
        key, value = item
        stored = self._k(key, "item")
        with self._lock:
            current = self._map.get(stored, _MISSING)
            if current is _MISSING or not (current is value or current == value):
                return False
            del self._map[stored]
            return True

    def try_update(self, key: K, new_value: V, comparison_value: V) -> bool:
        """Set ``key`` to ``new_value`` only while it maps to a value equal to ``comparison_value``."""
        stored = self._k(key)
        with self._lock:
            current = self._map.get(stored, _MISSING)
            if current is _MISSING or not (current is comparison_value or current == comparison_value):
                return False
            self._map[stored] = new_value
            return True

    def _as_factory(self, value: Any, factory_argument: Any) -> bool:
        """Whether a positional ``value`` is a factory (C# overload resolution, see the class docs)."""
        if factory_argument is not _MISSING:
            if not callable(value):
                raise TypeError("factory_argument needs a value factory")
            return True
        return callable(value) and not self._values_are_callable

    @overload
    def get_or_add(self, key: K, value: V, /) -> V: ...

    @overload
    def get_or_add(self, key: K, value_factory: Callable[[K], V], /) -> V: ...

    @overload
    def get_or_add[A](self, key: K, value_factory: Callable[[K, A], V], /, factory_argument: A) -> V: ...

    @overload
    def get_or_add(self, key: K, /, *, value_factory: Callable[[K], V]) -> V: ...

    @overload
    def get_or_add[A](self, key: K, /, *, value_factory: Callable[[K, A], V], factory_argument: A) -> V: ...

    def get_or_add(
            self,
            key: K,
            value: Any = _MISSING,
            /,
            factory_argument: Any = _MISSING,
            *,
            value_factory: Any = _MISSING,
    ) -> V:
        """The value of ``key``, adding ``value`` (or ``value_factory(key[, factory_argument])``) first
        if it is absent (.NET ``GetOrAdd``). A callable ``value`` is the factory unless ``V`` is
        callable; ``value_factory=`` says so explicitly."""
        stored = self._k(key)
        if value is not _MISSING:
            if value_factory is not _MISSING:
                raise TypeError("pass either value or value_factory, not both")
            if self._as_factory(value, factory_argument):
                value, value_factory = _MISSING, value
        elif value_factory is _MISSING or value_factory is None:
            raise ArgumentNullError("valueFactory")
        current = self._map.get(stored, _MISSING)
        if current is not _MISSING:
            return current
        if value is _MISSING:
            value = value_factory(key) if factory_argument is _MISSING else value_factory(key, factory_argument)
        with self._lock:
            current = self._map.get(stored, _MISSING)
            if current is not _MISSING:
                return current
            self._map[stored] = value
            return value

    @overload
    def add_or_update(self, key: K, add_value: V, /, update_value_factory: Callable[[K, V], V]) -> V: ...

    @overload
    def add_or_update(
            self, key: K, add_value_factory: Callable[[K], V], /, update_value_factory: Callable[[K, V], V],
    ) -> V: ...

    @overload
    def add_or_update[A](
            self, key: K, add_value_factory: Callable[[K, A], V], /,
            update_value_factory: Callable[[K, V, A], V], factory_argument: A,
    ) -> V: ...

    @overload
    def add_or_update(
            self, key: K, /, *, add_value_factory: Callable[[K], V], update_value_factory: Callable[[K, V], V],
    ) -> V: ...

    @overload
    def add_or_update[A](
            self, key: K, /, *, add_value_factory: Callable[[K, A], V],
            update_value_factory: Callable[[K, V, A], V], factory_argument: A,
    ) -> V: ...

    def add_or_update(
            self,
            key: K,
            add_value: Any = _MISSING,
            /,
            update_value_factory: Any = _MISSING,
            factory_argument: Any = _MISSING,
            *,
            add_value_factory: Any = _MISSING,
    ) -> V:
        """Add ``key`` with ``add_value`` (or ``add_value_factory(key[, factory_argument])``), or, if it
        is present, replace its value with ``update_value_factory(key, old_value[, factory_argument])``
        (.NET ``AddOrUpdate``). Returns the value stored. A callable ``add_value`` is the factory
        unless ``V`` is callable; ``add_value_factory=`` says so explicitly."""
        stored = self._k(key)
        if update_value_factory is _MISSING or update_value_factory is None:
            raise ArgumentNullError("updateValueFactory")
        if add_value is not _MISSING:
            if add_value_factory is not _MISSING:
                raise TypeError("pass either add_value or add_value_factory, not both")
            if self._as_factory(add_value, factory_argument):
                add_value, add_value_factory = _MISSING, add_value
        elif add_value_factory is _MISSING or add_value_factory is None:
            raise ArgumentNullError("addValueFactory")
        with_argument = factory_argument is not _MISSING
        while True:
            current = self._map.get(stored, _MISSING)
            if current is _MISSING:
                if add_value is not _MISSING:
                    new_value = add_value
                elif with_argument:
                    new_value = add_value_factory(key, factory_argument)
                else:
                    new_value = add_value_factory(key)
                with self._lock:
                    if stored not in self._map:
                        self._map[stored] = new_value
                        return new_value
            else:
                if with_argument:
                    new_value = update_value_factory(key, current, factory_argument)
                else:
                    new_value = update_value_factory(key, current)
                with self._lock:
                    if self._map.get(stored, _MISSING) is current:
                        self._map[stored] = new_value
                        return new_value

    def to_array(self) -> list[tuple[K, V]]:
        """A snapshot of the ``(key, value)`` pairs."""
        return list(self._pairs())

    def copy_to(self, array: list[tuple[K, V]], index: int = 0) -> None:
        """Copy the ``(key, value)`` pairs into ``array`` from ``index`` on (.NET ``ICollection.CopyTo``)."""
        _copy_into(self.to_array(), array, index)

    @override
    def clear(self) -> None:
        with self._lock:
            self._map.clear()

    # --- MutableMapping ---------------------------------------------------------------------

    def __getitem__(self, key: K) -> V:
        value = self._map.get(self._k(key), _MISSING)
        if value is _MISSING:
            raise KeyNotFoundError(key)
        return value

    def __setitem__(self, key: K, value: V) -> None:
        stored = self._k(key)
        with self._lock:
            self._map[stored] = value

    def __delitem__(self, key: K) -> None:
        if not self.try_remove(key)[0]:
            raise KeyNotFoundError(key)

    @override
    def __contains__(self, key: object) -> bool:
        return self.contains_key(cast(K, key))

    def __len__(self) -> int:
        return len(self._map)

    def _pairs(self) -> Iterator[tuple[K, V]]:
        snapshot = self._map.copy()  # atomic
        if self._wrap is None:
            return iter(snapshot.items())
        return ((stored.key, value) for stored, value in snapshot.items())

    def __iter__(self) -> Iterator[K]:
        snapshot = self._map.copy()
        if self._wrap is None:
            return iter(snapshot)
        return (stored.key for stored in snapshot)

    def keys(self) -> tuple[K, ...]:  # type: ignore[override]
        """A snapshot of the keys."""
        return tuple(self)

    def values(self) -> tuple[V, ...]:  # type: ignore[override]
        """A snapshot of the values."""
        return tuple(self._map.copy().values())

    def items(self) -> tuple[tuple[K, V], ...]:  # type: ignore[override]
        """A snapshot of the ``(key, value)`` pairs (.NET's enumeration)."""
        return tuple(self._pairs())

    @override
    def get(self, key: K, default: Any = None) -> Any:
        value = self._map.get(self._k(key), _MISSING)
        return default if value is _MISSING else value

    @override
    def setdefault(self, key: K, default: Any = None) -> Any:
        return self.get_or_add(key, value_factory=lambda _: default)  # always the value, even a callable

    @override
    def pop(self, key: K, default: Any = _MISSING) -> Any:
        removed, value = self.try_remove(key)
        if removed:
            return value
        if default is _MISSING:
            raise KeyNotFoundError(key)
        return default

    @override
    def popitem(self) -> tuple[K, V]:
        with self._lock:
            if not self._map:
                raise KeyError("popitem(): dictionary is empty")
            stored, value = self._map.popitem()
        return self._unwrap(stored), value

    def __repr__(self) -> str:
        return f"ConcurrentDictionary({dict(self._pairs())!r})"


# Short names: the same classes.
CDict = ConcurrentDictionary
CQueue = ConcurrentQueue
CStack = ConcurrentStack
CBag = ConcurrentBag
