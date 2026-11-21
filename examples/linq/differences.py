"""Where flpit deliberately differs from .NET LINQ."""
from flpit import flp

# --8<-- [start:index]
names = ["Ada", "Tim", "Grace"]

# index() pairs every element with its position (.NET 9 Index).
assert flp.it(names).index().to_list() == [(0, "Ada"), (1, "Tim"), (2, "Grace")]

for position, name in flp.it(names).index():       # it unpacks like a tuple
    assert names[position] == name
# --8<-- [end:index]

# --8<-- [start:indexed_select]
# .NET: names.Select((name, i) => $"{i}: {name}")
numbered = (
    flp.it(names)
        .index()
        .select(lambda t: f"{t.index}: {t.item}")
        .to_list()
)
assert numbered == ["0: Ada", "1: Tim", "2: Grace"]

# .NET: names.Where((name, i) => i % 2 == 0)
even_positions = (
    flp.it(names)
        .index()
        .where(lambda t: t.index % 2 == 0)
        .select(lambda t: t.item)
        .to_list()
)
assert even_positions == ["Ada", "Grace"]
# --8<-- [end:indexed_select]

# --8<-- [start:ends]
numbers = flp.it([4, 8, 15])

assert numbers.first_or_default(-1) == 4
assert numbers.first_or_default(-1, lambda x: x > 10) == 15       # the default comes first, then the predicate
assert numbers.first_or_default(-1, lambda x: x > 100) == -1      # no match: the default, no exception

assert flp.it([]).first_or_default(None) is None                  # .NET: FirstOrDefault() on a reference type
# --8<-- [end:ends]
