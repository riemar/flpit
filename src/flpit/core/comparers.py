"""
Equality comparers (.NET ``IEqualityComparer<T>`` / ``EqualityComparer<T>``).

A comparer decides when two keys are the same: ``equals(x, y)`` and a matching
``get_hash_code(obj)`` (equal objects must have equal hash codes)::

    ignore_case = EqualityComparer.create(
        lambda x, y: x.casefold() == y.casefold(),
        lambda s: hash(s.casefold()),
    )
    ages = ConcurrentDictionary(comparer=ignore_case)

Any object with these two methods works as a comparer; ``EqualityComparer`` is the
convenient base class. ``EqualityComparer.default()`` uses ``==`` and ``hash()``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, override, runtime_checkable

from flpit.core.linq import ArgumentNullError, NotSupportedError

__all__ = ["EqualityComparer", "IEqualityComparer"]


@runtime_checkable
class IEqualityComparer[T](Protocol):
    """What a comparer provides (.NET ``IEqualityComparer<T>``)."""

    def equals(self, x: T, y: T) -> bool: ...

    def get_hash_code(self, obj: T) -> int: ...


class EqualityComparer[T]:
    """Base class for comparers (.NET ``EqualityComparer<T>``)."""

    def equals(self, x: T, y: T) -> bool:
        raise NotImplementedError

    def get_hash_code(self, obj: T) -> int:
        raise NotImplementedError

    @staticmethod
    def default() -> EqualityComparer[Any]:
        """The comparer using ``==`` and ``hash()`` (.NET ``EqualityComparer<T>.Default``)."""
        return _DEFAULT

    @staticmethod
    def create[U](
            equals: Callable[[U, U], bool],
            get_hash_code: Callable[[U], int] | None = None,
    ) -> EqualityComparer[U]:
        """A comparer from two functions (.NET ``EqualityComparer<T>.Create``).

        Without ``get_hash_code``, hashing raises ``NotSupportedError``: such a comparer
        can compare but not key a dictionary.
        """
        if equals is None:
            raise ArgumentNullError("equals")
        return _DelegateEqualityComparer(equals, get_hash_code)


class _DefaultEqualityComparer(EqualityComparer[Any]):
    __slots__ = ()

    @override
    def equals(self, x: Any, y: Any) -> bool:
        return bool(x == y)

    @override
    def get_hash_code(self, obj: Any) -> int:
        return hash(obj)

    def __repr__(self) -> str:
        return "EqualityComparer.default()"


_DEFAULT = _DefaultEqualityComparer()


class _DelegateEqualityComparer[T](EqualityComparer[T]):
    __slots__ = ("_equals", "_get_hash_code")

    def __init__(self, equals: Callable[[T, T], bool], get_hash_code: Callable[[T], int] | None) -> None:
        self._equals = equals
        self._get_hash_code = get_hash_code

    @override
    def equals(self, x: T, y: T) -> bool:
        return bool(self._equals(x, y))

    @override
    def get_hash_code(self, obj: T) -> int:
        if self._get_hash_code is None:
            raise NotSupportedError("This comparer was created without a get_hash_code function.")
        return self._get_hash_code(obj)
