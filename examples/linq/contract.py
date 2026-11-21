"""The behaviours flpit shares with .NET LINQ, one at a time."""
from _support import Tracked, raises

from flpit import (
    flp, EmptySequenceError, InvalidOperationError,
    MultipleMatchesError, NoMatchError,
)

# --8<-- [start:deferred]
source = Tracked(range(100))
query = flp.it(source).where(lambda x: x % 2 == 1).select(lambda x: x * 10)

assert source.pulled == 0          # building a query reads nothing
assert query.first() == 10         # enumeration does the work
# --8<-- [end:deferred]

# --8<-- [start:callbacks]
seen: list[int] = []
query = flp.it([1, 2, 3]).select(lambda x: seen.append(x) or x)

assert seen == []                  # callbacks do not run at construction
query.take(2).to_list()
assert seen == [1, 2]              # ... only as far as enumeration goes
# --8<-- [end:callbacks]

# --8<-- [start:short_circuit]
source = Tracked(range(100))
assert flp.it(source).any(lambda x: x >= 3)
assert source.pulled == 4          # stopped at the first match: 0, 1, 2, 3

source = Tracked(range(100))
with raises(MultipleMatchesError):
    flp.it(source).single(lambda x: x >= 3)
assert source.pulled == 5          # stopped at the second match: 3 and 4
# --8<-- [end:short_circuit]

# --8<-- [start:exceptions]
with raises(EmptySequenceError):
    flp.it([]).first()

with raises(NoMatchError):
    flp.it([1]).first(lambda x: x > 5)

# All of them are InvalidOperationError, mirroring InvalidOperationException.
assert issubclass(EmptySequenceError, InvalidOperationError)
assert issubclass(NoMatchError, InvalidOperationError)
assert issubclass(MultipleMatchesError, InvalidOperationError)

# The *_or_default variants return a default instead of raising.
assert flp.it([]).first_or_default(-1) == -1
# --8<-- [end:exceptions]

# --8<-- [start:sources]
repeatable = flp.it([1, 2, 3])
assert repeatable.to_list() == [1, 2, 3]
assert repeatable.to_list() == [1, 2, 3]   # a list can be enumerated again

one_shot = flp.it(x for x in range(3))
assert one_shot.to_list() == [0, 1, 2]
assert one_shot.to_list() == []            # a generator stays one-shot
# --8<-- [end:sources]

# --8<-- [start:set_ops]
assert flp.it([3, 1, 3, 2, 1]).distinct().to_list() == [3, 1, 2]   # first occurrence wins

pairs = flp.it([1, 2, 3]).zip(["a", "b"]).to_list()
assert [(p.first, p.second) for p in pairs] == [(1, "a"), (2, "b")]  # stops at the shorter
# --8<-- [end:set_ops]
