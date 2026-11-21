"""Helpers shared by the LINQ examples (not shown as examples themselves)."""
from collections.abc import Iterable, Iterator
from contextlib import contextmanager


# --8<-- [start:tracked]
class Tracked:
    """A one-shot source that counts how many elements it has handed out."""

    def __init__(self, items: Iterable[int]) -> None:
        self._items = iter(items)
        self.pulled = 0

    def __iter__(self) -> Iterator[int]:
        for item in self._items:
            self.pulled += 1
            yield item
# --8<-- [end:tracked]


@contextmanager
def raises(exc: type[BaseException]):
    """Assert that the block raises ``exc``."""
    try:
        yield
    except exc:
        return
    raise AssertionError(f"{exc.__name__} was not raised")
