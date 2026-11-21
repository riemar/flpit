"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Helpers for the shared collection suites, ported from
https://github.com/dotnet/runtime/tree/main/src/libraries/Common/tests/System/Collections
(TestBase.NonGeneric.cs, TestBase.Generic.cs, TestingTypes.cs).

.NET -> Python mapping used by tests/nettests/common and tests/nettests/concurrent:
    IEnumerator<T> (MoveNext / Current / Dispose)  -> Enumerator over a Python iterator
    enumerator.Reset()                             -> not portable: Python iterators cannot rewind
    KeyValuePair<TKey, TValue>                     -> (key, value) tuple
    default(T)                                     -> DEFAULT_* of the suite (None for reference types)
    new Random(seed).Next()                        -> random.Random(seed).randrange(2**31 - 1)
                                                      (a different sequence; tests only need determinism)
    ArgumentException / ArgumentNullException      -> ArgumentError / ArgumentNullError
    KeyNotFoundException                           -> KeyNotFoundError
    NotSupportedException                          -> NotSupportedError
"""
from __future__ import annotations

import base64
import random
from collections.abc import Iterator
from enum import Enum, IntFlag, KEEP, auto
from typing import Any

import pytest

from flpit.core.comparers import EqualityComparer, IEqualityComparer
from flpit.core.linq import NotSupportedError

VALID_COLLECTION_SIZES = [0, 1, 75]
VALID_POSITIVE_COLLECTION_SIZES = [1, 75]


def not_portable(reason: str) -> None:
    pytest.skip(f"Not portable to Python: {reason}")


def unsupported(feature: str) -> None:
    pytest.skip(f"Upstream .NET test requires unsupported FlpIt API: {feature}")


NO_RESET = "Python iterators have no Reset(); they cannot rewind"
NO_CURRENT = "Python iterators have no Current outside MoveNext, so 'undefined behavior' has nothing to probe"
NO_WEAKREF = "Python ints and strings do not support weak references"


def next_int(seed: int) -> int:
    """.NET ``new Random(seed).Next()``."""
    return random.Random(seed).randrange(2**31 - 1)


def random_base64(seed: int) -> str:
    """The upstream string factory: ``Convert.ToBase64String`` of ``seed % 10 + 5`` random bytes."""
    rand = random.Random(seed)
    return base64.b64encode(rand.randbytes(seed % 10 + 5)).decode("ascii")


class SimpleEnum(IntFlag, boundary=KEEP):
    """Upstream ``SimpleEnum`` keys are arbitrary ints cast to the enum: a KEEP flag holds any int."""

    FOO = 1
    BAR = 2


class ModifyOperation(IntFlag):
    NONE = 0
    ADD = 1
    INSERT = 2
    OVERWRITE = 4
    REMOVE = 8
    CLEAR = 16


class EnumerableOrder(Enum):
    UNSPECIFIED = auto()
    SEQUENTIAL = auto()


class EqualityComparerConstantHashCode[T](EqualityComparer[T]):
    """Every key hashes to 0: forces collisions."""

    def __init__(self, comparer: IEqualityComparer[T]) -> None:
        self._comparer = comparer

    def equals(self, x: T, y: T) -> bool:
        return self._comparer.equals(x, y)

    def get_hash_code(self, obj: T) -> int:
        return 0


class Enumerator[T]:
    """.NET ``IEnumerator<T>`` over a Python iterator: ``move_next()``, ``current``, ``dispose()``."""

    def __init__(self, iterator: Iterator[T]) -> None:
        self.iterator = iterator
        self._current: Any = None
        self._done = False

    def move_next(self) -> bool:
        if self._done:
            return False
        try:
            self._current = next(self.iterator)
        except StopIteration:
            self._done = True
            self._current = None
            return False
        return True

    @property
    def current(self) -> T:
        return self._current

    def reset(self) -> None:
        raise NotSupportedError("Python iterators cannot rewind.")

    def dispose(self) -> None:
        close = getattr(self.iterator, "close", None)
        if close is not None:
            close()
        self._done = True

    def __enter__(self) -> Enumerator[T]:
        return self

    def __exit__(self, *_: Any) -> None:
        self.dispose()
