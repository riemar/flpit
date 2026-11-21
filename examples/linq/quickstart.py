"""Quick start: the first examples of the docs."""

# --8<-- [start:quickstart]
from flpit import flp, FlpIt, FlpList

# A lazy, streaming pipeline: nothing has run yet.
query: FlpIt[int] = (
    flp
        .it(range(1, 11))
        .where(lambda x: x % 2 == 0)
        .select(lambda x: x * 10)
)

# Explicit materialization.
result: FlpList[int] = query.to_list()
assert result == [20, 40, 60, 80, 100]
# --8<-- [end:quickstart]

# --8<-- [start:flip]
# Native built-ins read inside-out ...
native = list(map(lambda x: x * 10, filter(lambda x: x % 2 == 0, range(1, 11))))

# ... a FlpIt pipeline reads top to bottom.
piped = (
    flp.it(range(1, 11))
    .where(lambda x: x % 2 == 0)
    .select(lambda x: x * 10)
    .to_list()
)
assert piped == native
# --8<-- [end:flip]

# --8<-- [start:domain]
from dataclasses import dataclass

from flpit import flp


@dataclass
class Employee:
    name: str
    salary: int


@dataclass
class Department:
    name: str
    employees: list[Employee]


company = [
    Department("Engineering", [Employee("Alice", 95_000), Employee("Bob", 70_000)]),
    Department("Design", [Employee("Charlie", 82_000)]),
]

# Everyone earning at least 80,000, across all departments.
well_paid = (
    flp.it(company)
    .select_many(lambda dept: dept.employees)
    .where(lambda emp: emp.salary >= 80_000)
    .select(lambda emp: emp.name)
)

assert list(well_paid) == ["Alice", "Charlie"]
# --8<-- [end:domain]

# --8<-- [start:builtins]
query = flp.range(1, 11).where(lambda x: x % 2 == 0)

assert query.first() == 2                  # LINQ-style terminal operators ...
assert query.any()

assert list(query) == [2, 4, 6, 8, 10]     # ... and plain Python built-ins both work
assert any(query)
# --8<-- [end:builtins]
