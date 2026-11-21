"""Ordering and grouping."""
from typing import NamedTuple

from flpit import flp

words = ["pear", "fig", "apple", "kiwi", "plum", "date"]

# --8<-- [start:order]
by_length = flp.it(words).order_by(lambda w: len(w))

# order_by is stable: equal keys keep their original order.
assert by_length.to_list() == ["fig", "pear", "kiwi", "plum", "date", "apple"]

# then_by adds a secondary key; it does not replace the primary one.
tie_broken = by_length.then_by(lambda w: w)
assert tie_broken.to_list() == ["fig", "date", "kiwi", "pear", "plum", "apple"]
# --8<-- [end:order]


# --8<-- [start:group]
class LengthGroup(NamedTuple):
    length: int
    words: list[str]


groups = (
    flp.it(words)
    .group_by(lambda w: len(w))
    .select(lambda g: LengthGroup(length=g.key, words=list(g)))
    .to_list()
)

# Groups appear in order of first occurrence; elements keep their order.
assert groups == [
    LengthGroup(4, ["pear", "kiwi", "plum", "date"]),
    LengthGroup(3, ["fig"]),
    LengthGroup(5, ["apple"]),
]
# --8<-- [end:group]
