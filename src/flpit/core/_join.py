from typing import NamedTuple


class JoinTuple[TOuter, TInner](NamedTuple):
    """Default result of join / left_join / full_join when no result selector is given."""
    outer: TOuter
    inner: TInner
