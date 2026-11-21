"""Quick start: the first example on the home page."""

# --8<-- [start:quickstart]
from flpit import flp, FlpIt, FlpList

data: FlpIt[int] = flp.it(range(1, 11))

# A lazy, streaming pipeline: nothing has run yet.
query: FlpIt[int] = data.where(lambda x: x % 2 == 0).select(lambda x: x * 10)

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


@dataclass
class Employee:
    name: str
    role: str
    salary: int


@dataclass
class Department:
    name: str
    employees: list[Employee]


company = [
    Department("Engineering", [
        Employee("Alice", "Backend Engineer", 95_000),
        Employee("Bob", "Frontend Engineer", 90_000),
    ]),
    Department("Design", [Employee("Charlie", "UI Designer", 82_000)]),
]

# Names of backend engineers earning at least 90,000.
backend_engineers = (
    flp.it(company)
    .select_many(lambda dept: dept.employees)
    .where(lambda emp: emp.role == "Backend Engineer")
    .where(lambda emp: emp.salary >= 90_000)
    .select(lambda emp: emp.name)
)

assert list(backend_engineers) == ["Alice"]
# --8<-- [end:domain]
