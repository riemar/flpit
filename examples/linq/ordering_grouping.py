"""Ordering and grouping."""
from flpit import flp

words = ["pear", "fig", "apple", "kiwi"]

# --8<-- [start:order]
by_length = flp.it(words).order_by(len)

# order_by is stable: equal keys keep their original order.
assert by_length.to_list() == ["fig", "pear", "kiwi", "apple"]

# then_by adds a secondary key; it does not replace the primary one.
assert by_length.then_by(lambda w: w).to_list() == ["fig", "kiwi", "pear", "apple"]
# --8<-- [end:order]

# --8<-- [start:group]
groups = (
    flp.it(words)
    .group_by(len)
    .select(lambda g: (g.key, g.to_list()))
    .to_list()
)

# Groups appear in order of first occurrence; elements keep their order.
assert groups == [(4, ["pear", "kiwi"]), (3, ["fig"]), (5, ["apple"])]
# --8<-- [end:group]
