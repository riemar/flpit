# FlpIt

> **Fluent LINQ for Python — LINQ semantics, Python-native execution**

`FlpIt` brings a strongly typed, LINQ-style API to standard Python iterables. It combines the fluent query model and semantics of .NET LINQ with Python's native iterable and generator model.

> **Semantic goal:** `flp` strives to faithfully reproduce .NET LINQ semantics.  
> Where Python's language or type system requires a different API contract, the contract is adapted accordingly. 
> The implementation is actively developed, and semantic deviations may still exist.

## ⚡ Key Features

* **⚡ Lazy Evaluation (`FlpIt`):** Deferred, streaming execution where the underlying operation permits it. `FlpIt` wraps a standard Python `Iterable[T]`.
* **📦 Materialized Container (`FlpList`):** Eager, mutable container backed by `collections.UserList`.
* **🎯 LINQ Semantics:** Operators such as `.any()`, `.first()`, `.single()`, `.order_by()`, and `.then_by()` follow .NET LINQ semantics.
* **🔀 Independent Query Pipelines:** Derived queries are independent and never mutate or retroactively affect separately created queries.
* **🧠 Lazy Internal Materialization:** Some operators, such as ordering and grouping, require internal materialization during deferred execution, while the query itself remains lazy.
* **🔄 Source Enumeration Semantics** — FlpIt preserves the enumeration characteristics of its source. A query over a re-enumerable source can be enumerated repeatedly; a one-shot source such as a Python generator remains one-shot. FlpIt does not clone or rewind arbitrary Python iterators.
* **🔹 Static-First Typing:** Designed for precise `pyrefly` inference without plugins (mypy and pyright might give varying results).
* **🐍 Python-Native:** Built on standard Python iterables, iterators, generators, and callable semantics.

## Scope & Intent

FlpIt focuses exclusively on replicating the **`IEnumerable` (`System.Linq.Enumerable`)** model.

* **Direct Execution:** It operates directly on standard Python callables (lambdas and functions) over Python iterables.
* **No Provider Abstraction:** It does not model or emit Expression Trees (`IQueryable`) for translation by external providers. There is no query-provider layer that rewrites FlpIt operations into database queries or other backend-specific operations.

FlpIt therefore follows the execution model of in-memory LINQ: query operators build a pipeline, execution is deferred where the operator permits it, and each operator's actual enumeration and buffering behavior is part of the query semantics.

## 🤸 Flipping the Pipeline

Native Python functional operations tend to produce an inside-out, right-to-left reading pattern...

```python
# 🔁 Native Built-ins
result = list(map(lambda x: x * 10, filter(lambda x: x % 2 == 0, range(1, 11))))

# 🤸 FlpIt Pipeline
result = (
    flp.it(range(1, 11))
    .where(lambda x: x % 2 == 0)
    .select(lambda x: x * 10)
    .to_list()
)
```

## 💡 Quick Start

```python
from flpit import flp, FlpIt, FlpList

# Deferred iterable via shorthand
data: FlpIt[int] = flp.it(range(1, 11))

# Lazy, streaming pipeline
query: FlpIt[int] = (
    data
    .where(lambda x: x % 2 == 0)
    .select(lambda x: x * 10)
)

# Explicit materialization
result: FlpList[int] = query.to_list()
# [20, 40, 60, 80, 100]

# Or start directly with an eager container
eager_list: FlpList[int] = flp.lst([1, 2, 3, 4])
```

## Typed Domain Objects

```python
from dataclasses import dataclass
from flpit import flp


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
    Department(
        "Engineering",
        [
            Employee("Alice", "Backend Engineer", 95_000),
            Employee("Bob", "Frontend Engineer", 90_000),
        ],
    ),
    Department(
        "Design",
        [
            Employee("Charlie", "UI Designer", 82_000),
        ],
    ),
]

# Extract the names of backend engineers earning at least 90,000.
backend_engineers = (
    flp.it(company)
    .select_many(lambda dept: dept.employees)
    .where(lambda emp: emp.role == "Backend Engineer")
    .where(lambda emp: emp.salary >= 90_000)
    .select(lambda emp: emp.name)
)

# The query is evaluated when it is enumerated.
print(list(backend_engineers))
# ['Alice']
```

## 🔬 LINQ Semantics, Python Runtime

`flpit` deliberately separates the two:

- **LINQ defines the query semantics.**
- **Python provides the underlying iterable and execution model.**

For example:

```python
query = flp.range(1, 11).where(lambda x: x % 2 == 0)

query.any()       # LINQ-style terminal operation
query.first()     # LINQ-style terminal operation
query.single()    # LINQ-style terminal operation
```

The query can also be consumed through normal Python built-ins:

```python
any(query)
list(query)
```

The two forms serve different purposes: LINQ-style operators provide the query API and its associated semantics, while Python built-ins continue to operate through the normal iterable protocol.

## Source Repeatability

FlpIt does not imply that every source is repeatable. Re-enumeration depends on the underlying source:

```python
source = [1, 2, 3]
query = flp.it(source)

list(query)  # [1, 2, 3]
list(query)  # [1, 2, 3]
```

A one-shot iterator remains one-shot:

```python
source = (x for x in range(3))
query = flp.it(source)

list(query)  # [0, 1, 2]
list(query)  # []
```

## Intentional Deviation from Python List Contracts (`.count()`)

To faithfully provide standard .NET LINQ semantics, `FlpList` deliberately uses LINQ-style count() semantics instead of Python list.count(value) semantics of Python's standard `list.count(value)`.

* **Vanilla Python `list.count(value)`** counts occurrences of a specific *value*.
* **FlpIt `FlpList.count()`** counts all elements.
* **FlpIt `FlpList.count(predicate)`** counts elements matching the predicate.

```python
# Pure LINQ semantics instead of standard list behavior
total_evens = eager_list.count(lambda x: x % 2 == 0)
```

Because `FlpList` is an explicit, fluent wrapper designed to enforce LINQ behavior, this signature change is a deliberate design choice. If you need the native Python behavior to count occurrences of a specific item value, use the explicitly provided fallback method:

```python
# Use the fallback for traditional Python value-counting
occurrences = eager_list.count_item(4)
```

## 🔗 Independent Query Pipelines

Query pipelines can be composed independently without mutating the queries they were derived from:

For example:

```python
@dataclass
class Item: 
    group: str 
    value: int

original = flp.it([Item("A", 2), Item("B", 1)])

ordered = original.order_by(lambda x: x.group)

extended = original.concat([Item("A", 1), Item("B", 2)])

ordered_by_group_and_value = ordered.then_by(lambda x: x.value)
```

The resulting query graph is:

```text
original
   │
   ├── order_by ──→ ordered
   │                  │
   │                  └── then_by ──→ ordered_by_group_and_value
   │
   └── concat ─────→ extended
```

`ordered_by_group_and_value` is derived from `ordered`.  
It does not modify `original`, and it is not affected by the separately created `extended` query.

This matches the independent-query behavior of .NET LINQ.

## Execution Characteristics

Lazy execution does not mean that every operator is streaming. Some operators must consume and buffer their input before they can produce their result.
**Sorting requires buffering:** Any exact sort of an arbitrary input must inspect its elements before it can produce the ordered result. This is not specific to FlpIt; it is an inherent characteristic of sorting and applies equally to native Python sorting and .NET LINQ `OrderBy()`.

| Operator               | Execution deferred | Processes incrementally | Buffers input |
| ---------------------- | ------------------ | ----------------------- | ------------- |
| `where()` / `select()` | Yes                | Yes                     | No            |
| `order_by()`           | Yes                | No                      | Yes           |
| `group_by()`           | Yes                | No                      | Yes           |

`order_by()` and `group_by()` therefore remain deferred at query construction time, but enumeration of either operator requires buffering its upstream input.

`group_by()` produces a query of groupings rather than terminating the pipeline:

```python
groups = query.group_by(lambda x: x % 3)

result = (
    groups(...)
    .where(...)
    .select(...)
    .to_list()
)
```

Terminal operators instead evaluate the query and return a result rather than another query:

```python
query.any()
query.first()
query.single()
query.count()
query.aggregate(...)
query.to_list()
```

For example, `aggregate()` processes its source incrementally but must consume the source completely to produce its final accumulated value.

## 🧠 Lazy Pipelines

Streaming operators do not materialize their upstream input:

```python
query = (
    flp.it(source)
    .where(predicate)
    .select(selector)
    .order_by(key_selector)
    .take(100)
)
```

Conceptually:

```text
source
  │
  ▼
where       ← streaming
  │
  ▼
select      ← streaming
  │
  ▼
order_by    ← lazy, internally buffers when enumerated
  │
  ▼
take        ← streaming
  │
  ▼
to_list     ← terminal materialization
```

Operations such as `order_by()` necessarily materialize their input internally to establish ordering.

## ⚙️ Installation

```bash
uv add flpit
```

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.


### Migrated .NET Unit Tests

> Migrated from the official .NET Runtime LINQ Tests.
> Note: The test cases exercise both core types, `FlpIt` and `FlpList`, with transitions between lazy and eager execution occurring as part of the individual test cases.

```
================================================================
| Test Module File                               |  Test Cases |
----------------------------------------------------------------
| tests/nettests/test_all.py                     |          80 |
| tests/nettests/test_any.py                     |          90 |
| tests/nettests/test_average.py                 |         572 |
| tests/nettests/test_count.py                   |          37 |
| tests/nettests/test_last.py                    |          29 |
| tests/nettests/test_order_by.py                |         100 |
| tests/nettests/test_order_descending_by.py     |          45 |
| tests/nettests/test_sum.py                     |         134 |
| tests/nettests/test_take.py                    |          39 |
| tests/nettests/test_then_by.py                 |          40 |
| tests/nettests/test_then_descending_by.py      |          34 |
----------------------------------------------------------------
| GRAND TOTALS                                   |        1200 |
================================================================
```