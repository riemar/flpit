"""Behaviour of composed queries."""
from dataclasses import dataclass

from _support import Tracked

from flpit import flp

# --8<-- [start:streaming_chain]
source = Tracked(range(100))
first_big_even = (
    flp.it(source)
    .where(lambda x: x % 2 == 0)
    .select(lambda x: x * x)
    .where(lambda x: x > 20)
    .first()
)

assert first_big_even == 36
assert source.pulled == 7          # 0..6: no more than needed
# --8<-- [end:streaming_chain]

# --8<-- [start:take]
source = Tracked(range(100))
assert flp.it(source).select(lambda x: x + 1).take(3).to_list() == [1, 2, 3]
assert source.pulled == 3          # take(3) does not read a fourth element
# --8<-- [end:take]

# --8<-- [start:buffering]
source = Tracked([5, 3, 9, 1, 7])
ordered = flp.it(source).order_by(lambda x: x).take(2)

assert source.pulled == 0          # still deferred
assert ordered.to_list() == [1, 3]
assert source.pulled == 5          # ordering had to see every element
# --8<-- [end:buffering]


# --8<-- [start:independent]
@dataclass
class Item:
    group: str
    value: int


original = flp.it([Item("A", 2), Item("B", 1)])
ordered_q = original.order_by(lambda x: x.group)
extended = original.concat([Item("A", 1), Item("B", 2)])
refined = ordered_q.then_by(lambda x: x.value)

assert len(original.to_list()) == 2        # untouched by anything derived from it
assert len(extended.to_list()) == 4
assert [(i.group, i.value) for i in refined.to_list()] == [("A", 2), ("B", 1)]
# --8<-- [end:independent]
