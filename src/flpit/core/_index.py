from typing import NamedTuple


class IndexTuple[TItem](NamedTuple):
    """
    Result of ``index()``: the zero-based position of an element together with the element itself.

    Mirrors the .NET ``(int Index, TSource Item)`` tuple.
    The `index` field hides the tuple.index(...) function.
    It doesn't serve a practical purpose in this scenario anyway
    """
    index: int
    item: TItem
