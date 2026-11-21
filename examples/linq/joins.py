"""Joins and lookups."""
from flpit import flp

# --8<-- [start:data]
people = [("Ada", 1), ("Tim", 2), ("Grace", 3)]   # (name, id)
orders = [(10, 1), (11, 1), (12, 4)]              # (order_id, person_id)
# --8<-- [end:data]

# --8<-- [start:join]
# Inner join: only people with orders (.NET Join).
pairs = (
    flp.it(people)
    .join(orders, lambda p: p[1], lambda o: o[1], lambda p, o: (p[0], o[0]))
    .to_list()
)
assert pairs == [("Ada", 10), ("Ada", 11)]
# --8<-- [end:join]

# --8<-- [start:left_join]
# Left join: everyone, with None where there is no order (.NET 10 LeftJoin).
pairs = (
    flp.it(people)
    .left_join(orders, lambda p: p[1], lambda o: o[1], lambda p, o: (p[0], o and o[0]))
    .to_list()
)
assert pairs == [("Ada", 10), ("Ada", 11), ("Tim", None), ("Grace", None)]
# --8<-- [end:left_join]

# --8<-- [start:full_join]
# Full join: unmatched orders are appended at the end (.NET 11 FullJoin).
pairs = (
    flp.it(people)
    .full_join(orders, lambda p: p[1], lambda o: o[1], lambda p, o: (p and p[0], o and o[0]))
    .to_list()
)
assert pairs[-1] == (None, 12)
# --8<-- [end:full_join]

# --8<-- [start:group_join]
# Group join: one result per person, with all of their orders (.NET GroupJoin).
grouped = (
    flp.it(people)
    .group_join(orders, lambda p: p[1], lambda o: o[1],
                lambda p, os: (p[0], os.select(lambda o: o[0]).to_list()))
    .to_list()
)
assert grouped == [("Ada", [10, 11]), ("Tim", []), ("Grace", [])]
# --8<-- [end:group_join]

# --8<-- [start:cross_join]
# Cross join: every combination. There is no .NET equivalent.
assert flp.it([1, 2]).cross_join(["a", "b"], lambda n, c: f"{n}{c}").to_list() == ["1a", "1b", "2a", "2b"]
# --8<-- [end:cross_join]

# --8<-- [start:lookup]
by_length = flp.it(["pear", "fig", "kiwi"]).to_lookup(len)   # enumerates the source right away

assert len(by_length) == 2                    # number of keys
assert by_length[4].to_list() == ["pear", "kiwi"]
assert by_length[9].to_list() == []           # a missing key gives an empty sequence
assert 3 in by_length
# --8<-- [end:lookup]
