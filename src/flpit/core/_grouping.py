from typing import Any
from flpit.core.linq import FlpIt
from collections.abc import Iterable

class Grouping[TKey, TItem](FlpIt[TItem]):
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
