"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Shared test data and helpers for the SkipLast / TakeLast ports.

Ported to Python from the .NET Runtime System.Linq test infrastructure:
https://github.com/dotnet/runtime/blob/main/src/libraries/Common/tests/System/Linq/SkipTakeData.cs
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/SkipLastTests.cs
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/TakeLastTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.

Mapping:
    SkipTakeData.EnumerableData()          -> ENUMERABLE_DATA, a list of (source_count, count) pairs.
                                              .NET passes ``Enumerable.Range(0, sourceCount)``; the tests rebuild
                                              ``range(0, source_count)`` for every case instead.
    SkipTakeData.EvaluationBehaviorData()  -> EVALUATION_BEHAVIOR_DATA
    SkipTakeData.QueryableData()           -> not ported: FlpIt has no IQueryable counterpart.
    DelegateIterator<T>                    -> DelegateIterator (a re-enumerable whose iterator is driven by callbacks).
    List<int> + RemoveAt                   -> mutable_list(): a live list that queries built earlier still observe.
"""
from collections.abc import Callable, Iterator

from flpit import FlpList

INT_MAX = 2147483647
INT_MIN = -2147483648

_SOURCE_COUNTS = [0, 1, 2, 3, 5, 8, 13, 55, 100, 250]

_POSITIVE_COUNTS = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 100, 250, 500, INT_MAX]
# counts.Concat(counts.Select(c => -c)).Append(0).Append(int.MinValue)
_COUNTS = _POSITIVE_COUNTS + [-c for c in _POSITIVE_COUNTS] + [0, INT_MIN]

ENUMERABLE_DATA = [
    (source_count, count)
    for source_count in _SOURCE_COUNTS
    for count in _COUNTS
]
ENUMERABLE_DATA_IDS = [f"src{source_count}-count{count}" for source_count, count in ENUMERABLE_DATA]

# Enumerable.Range(-1, 15)
EVALUATION_BEHAVIOR_DATA = list(range(-1, 14))


class DelegateIterator[TItem]:
    """
    Re-enumerable source whose iterator is driven by callbacks, like .NET's ``DelegateIterator<T>``.

    ``move_next`` is called before every element and ends the enumeration by returning False,
    ``current`` supplies the element after a successful ``move_next`` and ``dispose`` runs when the
    iterator finishes or is closed. An iterator that was never advanced never calls ``dispose``.
    """

    def __init__(
            self,
            move_next: Callable[[], bool],
            current: Callable[[], TItem],
            dispose: Callable[[], None],
    ) -> None:
        self._move_next = move_next
        self._current = current
        self._dispose = dispose

    def __iter__(self) -> Iterator[TItem]:
        try:
            while self._move_next():
                yield self._current()
        finally:
            self._dispose()


def mutable_list(flp_type, items):
    """
    Stand-in for .NET's ``List<int>`` in the "changes after the query was built" tests.

    Returns ``(source, remove_at)``. Queries built from ``source`` must observe elements removed
    through ``remove_at`` later: ``FlpList`` is itself mutable, ``FlpIt`` wraps a live Python list.
    """
    if flp_type is FlpList:
        source = FlpList(items)
        return source, source.remove_at

    backing = list(items)
    return flp_type(backing), backing.pop
