"""Helpers shared by the LINQ examples (not shown as examples themselves)."""

# --8<-- [start:tracked]
from collections.abc import Iterable, Iterator


class Tracked[T]:
    """A one-shot source that records every element it hands out."""

    def __init__(self, items: Iterable[T]) -> None:
        self._items = iter(items)
        self.pulled = 0

    def __iter__(self) -> Iterator[T]:
        for item in self._items:
            self.pulled += 1
            yield item
# --8<-- [end:tracked]


from contextlib import contextmanager


@contextmanager
def raises(exc: type[BaseException]):
    """Assert that the block raises ``exc`` (kept tiny so examples stay readable)."""
    try:
        yield
    except exc:
        return
    raise AssertionError(f"{exc.__name__} was not raised")
