"""FlpIt (deferred) versus FlpList (materialized)."""
from flpit import flp, FlpIt, FlpList

# --8<-- [start:deferred]
numbers = [1, 2]
doubled: FlpIt[int] = flp.it(numbers).select(lambda x: x * 2)

numbers.append(3)  # the query has not run yet, so it sees the change

assert doubled.to_list() == [2, 4, 6]
# --8<-- [end:deferred]

# --8<-- [start:eager]
snapshot: FlpList[int] = flp.it([1, 2, 3]).select(lambda x: x * 2).to_list()

assert snapshot[0] == 2          # a FlpList is a normal indexable collection
assert snapshot[1:] == [4, 6]    # ... that also speaks LINQ
assert snapshot.where(lambda x: x > 2).to_list() == [4, 6]
# --8<-- [end:eager]

# --8<-- [start:count]
values = flp.lst([1, 2, 2, 3])

assert values.count() == 4                       # LINQ Count(): all elements
assert values.count(lambda x: x > 1) == 3        # LINQ Count(predicate)
assert list(values).count(2) == 2                # Python's list.count(value)
# --8<-- [end:count]
