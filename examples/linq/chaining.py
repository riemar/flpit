"""Behaviour of composed queries."""
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

assert first_big_even == 36     # 6 * 6
assert source.pulled == 7       # read 0..6, nothing more
# --8<-- [end:streaming_chain]

# --8<-- [start:take]
source = Tracked(range(100))
assert flp.it(source).select(lambda x: x + 1).take(3).to_list() == [1, 2, 3]
assert source.pulled == 3       # take(3) does not read a fourth element
# --8<-- [end:take]

# --8<-- [start:buffering]
source = Tracked([5, 3, 9, 1, 7])
smallest_two = flp.it(source).order_by(lambda x: x).take(2)

assert source.pulled == 0       # still deferred
assert smallest_two.to_list() == [1, 3]
assert source.pulled == 5       # ordering had to see every element
# --8<-- [end:buffering]

# --8<-- [start:independent]
original = flp.it([3, 1, 2])
ordered = original.order_by(lambda x: x)
extended = original.concat([9])

assert original.to_list() == [3, 1, 2]      # untouched by the queries derived from it
assert ordered.to_list() == [1, 2, 3]
assert extended.to_list() == [3, 1, 2, 9]
# --8<-- [end:independent]
