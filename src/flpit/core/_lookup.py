from typing import override

from flpit.core.linq import FlpIt, FlpList
from flpit.core._grouping import Grouping


class Lookup[TKey, TElement](FlpIt[Grouping[TKey, TElement]]):
    """
    Read-only, materialized one-to-many map of keys to groupings (.NET ``ILookup<TKey, TElement>``).

    Enumerates its groupings in the order their keys first appeared in the source and can be enumerated
    repeatedly. ``None`` is a valid key. Indexing a missing key yields an empty sequence instead of raising.
    """
    __slots__ = ("_groups",)

    def __init__(self, groups: dict[TKey, Grouping[TKey, TElement]]) -> None:
        self._groups: dict[TKey, Grouping[TKey, TElement]] = groups
        super().__init__(groups.values())

    def __len__(self) -> int:
        """Number of key/grouping pairs (.NET ``ILookup.Count``)."""
        return len(self._groups)

    def __getitem__(self, key: TKey) -> FlpList[TElement]:
        """Elements of ``key``, or an empty sequence if the key is missing (.NET ``ILookup[key]``)."""
        grouping = self._groups.get(key)
        return FlpList[TElement]() if grouping is None else grouping

    def __contains__(self, key: object) -> bool:
        """``key in lookup`` tests for a key (.NET ``ILookup.Contains(key)``)."""
        return key in self._groups

    @override
    def contains(self, key: TKey) -> bool:  # type: ignore[override]
        """Determines whether ``key`` is in the lookup (.NET ``ILookup.Contains(key)``, hides LINQ ``Contains``)."""
        return key in self._groups

    @override
    def __repr__(self) -> str:
        return f"Lookup({list(self._groups.values())!r})"
