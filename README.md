# FlpIt

**[🌐 View on GitHub](https://github.com/riemar/flpit)** | [📦 View on PyPI](https://pypi.org/project/flpit/)


> **Fluent LINQ for Python — LINQ semantics, Python-native execution**

`FlpIt` brings a strongly typed, LINQ-style API to standard Python iterables. It combines the fluent query model and semantics of .NET LINQ with Python's native iterable and generator model.

> **Semantic goal:** `flp` strives to faithfully reproduce .NET LINQ semantics.  
> Where Python's language or type system requires a different API contract, the contract is adapted accordingly. 
> The implementation is actively developed, and semantic deviations may still exist.

## Familiar LINQ, Now in Python

FlpIt is a Python implementation of the popular .NET Language Integrated Query (LINQ), adapted to Python.

If you know C# LINQ, you already know most of FlpIt. Existing LINQ examples, query patterns, and documentation can generally be translated directly.
FlpIt aims to make its implemented LINQ operators behave like their corresponding .NET `System.Linq.Enumerable` counterparts.

This makes the extensive .NET LINQ ecosystem a valuable reference for developers and AI coding assistants alike.

## ⚡ Key Features

* **⚡ Lazy Evaluation (`FlpIt`):** Deferred, streaming execution wrapping any standard Python `Iterable[T]`.
* **📦 Materialized Container (`FlpList`):** Eager collection implementing Python's `Collection` protocol (with indexing and slicing), retaining familiar collection access while providing .NET `List<T>`-style semantics and fluent LINQ query operations.
* **🎯 LINQ Semantics:** Familiar operators like `.any()`, `.first()`, `.single()`, `.order_by()`, and `.then_by()` with predictable, composable behavior.
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

## JSON Serialization

FlpIt provides typed JSON serialization and deserialization through `flpit.json.JsonConvert`, 
backed by [`msgspec`](https://github.com/jcrist/msgspec). 

It supports dataclasses, nested models, generic containers, configurable property naming, and explicit field metadata.

```python
from dataclasses import dataclass
from typing import Annotated

from flpit import FlpList
from flpit.json import JProp, JIgnore, JsonConvert

@dataclass
class Person:
    first_name: str
    internal_id: Annotated[str, JProp("id")]
    password: Annotated[str, JIgnore] = ""


person = Person("Ada", "usr-42", "secret")
raw = JsonConvert.serialize(person, Person)
# {"firstName":"Ada","id":"usr-42"}

people_json = """
[
    {"firstName": "Ada", "id": "usr-42"},
    {"firstName": "Grace", "id": "usr-43"}
]
"""

people: FlpList[Person] = FlpList.from_json(people_json, Person)
```

### Mapping and conversion

- **Naming policies:** Configure automatic property naming with `JsonSerializerOptions`. The default is camel case.
- **Explicit metadata:** `JProp` assigns a specific JSON property name, `JIgnore` excludes a field, and `JInclude` explicitly includes otherwise excluded underscore-prefixed fields.
- **Serialization options:** Control default-value omission and whether unknown JSON fields are accepted or rejected.
- **Typed collections:** Pass the complete target type, such as `list[Person]`, so nested and generic values can be decoded against the intended schema.

For large outputs, `JsonConvert.serialize_to()` writes a JSON array to a file-like stream without first materializing the entire serialized document.

By default, deserialization returns instances of the requested model type. Setting `native=True` opts into the generated `msgspec.Struct` representation instead, trading the original model type for the native representation and its performance characteristics.

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

## Intentional Semantic Deviation: `count()`

`FlpList` is a LINQ-oriented collection. Its query methods follow LINQ semantics even when those semantics differ from Python's built-in collection methods.

In Python, `list.count(value)` counts occurrences of a specific value:

```
[1, 2, 2, 3].count(2)  # 2
```

In LINQ, `Count()` returns the total number of elements, or elements matching a predicate:

```
FlpList([1, 2, 2, 3]).count()                 # 4
FlpList([1, 2, 2, 3]).count(lambda x: x > 1)  # 3
```

`FlpList.count()` deliberately follows the LINQ meaning. Python-style value counting remains available through normal Python operations when needed:

```
list(FlpList([1, 2, 2, 3])).count(2)  # 2
```

This behavior is a core part of `FlpList`'s LINQ-oriented contract, not an incomplete `list` implementation.

## Indexed Elements: `index()`

`index()` is the **.NET 9 `Index()` operator**. It pairs every element with its zero-based position and yields `IndexTuple(index, item)`. `IndexTuple` is a `NamedTuple`, so it unpacks and compares like a plain `(index, item)` tuple:

```python
flp.it(["a", "b", "c"]).index()
# [(0, "a"), (1, "b"), (2, "c")]                               (.NET 9 Index)

for i, name in flp.it(["a", "b"]).index():
  ...

flp.it(names).index().where(lambda t: t.index % 2 == 0).select(lambda t: t.item)
# every second name, starting with the first
```

* Execution is deferred and the source is streamed element by element; nothing is buffered.
* The .NET `OverflowException` after `int.MaxValue` elements does not apply: Python integers do not overflow.

### No indexed `select()` / `where()` overloads

.NET also offers `Select((item, index) => ...)` and `Where((item, index) => ...)`. 
With `index()` available, these overloads are **not planned** for `select()` and `where()`. 
This is a consequence of the Python runtime rather than an oversight: .NET picks between `x => ...` and `(x, i) => ...` at compile time through overload resolution, 
but Python has no overloads at runtime. A method receives one callable, and the only way to tell the two shapes apart would be to inspect that callable's signature on every call. 
That is fragile (builtins, `functools.partial`, `*args`, C-implemented callables) and would make behavior depend on how a function happens to be written. 
Keeping a single, unambiguous signature per operator and composing with `index()` expresses the same thing explicitly:

```python
flp.it(source).index().select(lambda t: f"{t.index}: {t.item}")  # instead of Select((x, i) => ...)
flp.it(source).index().where(lambda t: t.index >= 2).select(lambda t: t.item)  # instead of Where((x, i) => ...)
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

### Joins

```python
customers = [("Prakash", 1), ("Tim", 2), ("Robert", 3)]
orders    = [(10, 1), (11, 1), (12, 4)]          # (order_id, customer_id)

flp.it(customers).join(orders, lambda c: c[1], lambda o: o[1], lambda c, o: (c[0], o[0]))
# [("Prakash", 10), ("Prakash", 11)]                          inner join   (.NET Join)

flp.it(customers).left_join(orders, lambda c: c[1], lambda o: o[1], lambda c, o: (c[0], o and o[0]))
# [("Prakash", 10), ("Prakash", 11), ("Tim", None), ("Robert", None)]   (.NET 10 LeftJoin)

flp.it(customers).full_join(orders, lambda c: c[1], lambda o: o[1], lambda c, o: (c and c[0], o and o[0]))
# [("Prakash", 10), ("Prakash", 11), ("Tim", None), ("Robert", None), (None, 12)]   (.NET 11 FullJoin)

flp.it(customers).group_join(orders, lambda c: c[1], lambda o: o[1], lambda c, os: (c[0], os.select(lambda o: o[0]).to_list()))
# [("Prakash", [10, 11]), ("Tim", []), ("Robert", [])]        group join  (.NET GroupJoin)

flp.it([1, 2]).cross_join(["a", "b"], lambda n, c: f"{n}{c}")
# ["1a", "1b", "2a", "2b"]                                    cross join   (no .NET equivalent)
```

Without a result selector `join()`, `left_join()`, `full_join()` and `cross_join()` yield `JoinTuple(outer, inner)`; `group_join()` yields a `Grouping` whose `key` is the outer element and whose items are its matching inner elements.

* Elements whose key is `None` never match. `left_join()` / `full_join()` still emit them as unmatched; `group_join()` still emits them with an empty group.
* An unmatched side is passed to the result selector as `None` (the Python equivalent of .NET `default`).
* `full_join()` follows .NET 11 `FullJoin` (`join()` / `left_join()` follow .NET 10 and earlier). It yields the `left_join()` rows in outer order, followed by every inner element that was never matched (in inner order).
* `group_join()` follows .NET `GroupJoin`: it yields exactly one result per outer element, in outer order. Outer elements without a match get an empty group. The result selector receives the matching inner elements as a re-enumerable `FlpList` (a snapshot, in inner order). Like .NET, `inner` is only enumerated once the outer sequence yields its first element, so an empty outer sequence never touches `inner`.
* `cross_join()` has no .NET LINQ equivalent. It yields the cartesian product: outer order, then inner order for each outer element. There are no keys, so only `inner` and an optional result selector are taken. If `inner` is empty the result is empty and the outer sequence is not enumerated.
* Argument validation is eager (`InnerNoneError`, `OuterKeySelectorNoneError`, `InnerKeySelectorNoneError`, `ResultSelectorNoneError`; `cross_join()` has no key selectors); everything else is deferred.
* Custom equality comparers are not supported yet (keys are compared with `==` / `hash`, like `group_by()`).

## Execution Characteristics

Lazy execution does not mean that every operator is streaming. Some operators must consume and buffer their input before they can produce their result.
**Sorting requires buffering:** Any exact sort of an arbitrary input must inspect its elements before it can produce the ordered result. This is not specific to FlpIt; it is an inherent characteristic of sorting and applies equally to native Python sorting and .NET LINQ `OrderBy()`.

| Operator               | Execution deferred | Processes incrementally | Buffers input |
| ---------------------- | ------------------ | ----------------------- | ------------- |
| `where()` / `select()` | Yes                | Yes                     | No            |
| `index()`              | Yes                | Yes                     | No            |
| `skip_last()`          | Yes                | Yes                     | `count` elements (none on `FlpList`) |
| `take_last()`          | Yes                | No (`FlpList`: Yes)     | `count` elements (none on `FlpList`) |
| `order_by()`           | Yes                | No                      | Yes           |
| `group_by()`           | Yes                | No                      | Yes           |
| `join()`               | Yes                | Yes (outer)             | Yes (inner)   |
| `left_join()`          | Yes                | Yes (outer)             | Yes (inner)   |
| `full_join()`          | Yes                | Yes (outer)             | Yes (inner)   |
| `group_join()`         | Yes                | Yes (outer)             | Yes (inner)   |
| `cross_join()`         | Yes                | Yes (outer)             | Yes (inner)   |

`order_by()` and `group_by()` therefore remain deferred at query construction time, but enumeration of either operator requires buffering its upstream input.

On `FlpIt`, `skip_last()` streams with a look-ahead of `count` elements: it holds back at most `count` elements and releases each one as soon as `count` newer elements have been read. `take_last()` cannot know which elements are last before the source is exhausted, so its first element is produced only after the whole source was consumed (once); it keeps at most `count` elements in memory. `FlpList` knows its length, so both operators index directly (no buffering, no read-ahead), reading the length when enumeration starts. With `count <= 0`, `skip_last()` returns every element and `take_last()` is empty without enumerating the source.

`join()`, `left_join()`, `full_join()` and `group_join()` build a hash lookup of the `inner` sequence when enumeration starts and stream the outer sequence (O(N + M)); `group_join()` builds it once the outer sequence yields its first element. `cross_join()` buffers `inner` into a list once (it is traversed again for every outer element) and streams the outer sequence; the output size is N × M.

`group_by()` produces a query of groupings rather than terminating the pipeline:

```python
from typing import NamedTuple

class GroupResult(NamedTuple):
    remainder: int
    values: list[int]

result = (
    flp.it(range(1, 11))
    .group_by(lambda x: x % 2)
    .select(lambda group: GroupResult(
        remainder=group.key,
        values=list(group),
    ))
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

## ⚙️ Task Runtime

FlpIt includes a lightweight, `asyncio`-free task runtime for scheduling and coordinating concurrent work, with synchronous callables executed through a bounded worker pool.

Key features:

- **Task scheduling:** `Task.run()` schedules coroutines, awaitables, and synchronous callables.
- **Task coordination:** `Task.when_all()` waits for all tasks while preserving input order; `Task.when_any()` returns the first completed task; `Task.collect()` yields tasks as they complete.
- **Cancellation:** `CancellationToken` and `CancellationTokenSource` support cooperative cancellation, cancellation callbacks, timeouts, and linked cancellation tokens.
- **Resource management:** Configure worker capacity and pending background-work limits, handle queue saturation explicitly, and shut down the process-wide runtime with an observable shutdown report.
- **Asyncio interoperability:** FlpIt Tasks can be awaited directly inside asyncio coroutines when Task.asyncio_interop is enabled. 
  - This is disabled by default. 
  - Enabling it adds runtime-detection overhead to every pending await.
    - await in flpit runtime: 200ish nano sec (just loop detection)
    - await in asyncio loop: 

The runtime starts lazily and manages its own lifecycle. Cancellation of running synchronous functions is cooperative.

See the [Task Runtime examples](https://github.com/riemar/flpit/tree/main/examples/task) for usage examples.

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
================================================================================
| Test Module File                                               |  Test Cases |
--------------------------------------------------------------------------------
| tests/nettests/                                                |             |
| ├── linq/                                                      |             |
| │   ├── test_aggregate.py                                      |          42 |
| │   ├── test_all.py                                            |          80 |
| │   ├── test_any.py                                            |          90 |
| │   ├── test_append_prepend.py                                 |          36 |
| │   ├── test_average.py                                        |         572 |
| │   ├── test_cast.py                                           |          45 |
| │   ├── test_chunk.py                                          |          22 |
| │   ├── test_concat.py                                         |          64 |
| │   ├── test_contains.py                                       |         108 |
| │   ├── test_count.py                                          |          37 |
| │   ├── test_distinct.py                                       |          87 |
| │   ├── test_element_at.py                                     |          43 |
| │   ├── test_except.py                                         |          68 |
| │   ├── test_first.py                                          |          29 |
| │   ├── test_first_or_default.py                               |          50 |
| │   ├── test_full_join.py                                      |          37 |
| │   ├── test_generic_list.py                                   |          95 |
| │   ├── test_group_by.py                                       |          23 |
| │   ├── test_group_join.py                                     |          53 |
| │   ├── test_index.py                                          |           6 |
| │   ├── test_intersect.py                                      |          42 |
| │   ├── test_join.py                                           |          47 |
| │   ├── test_last.py                                           |          29 |
| │   ├── test_last_or_default.py                                |          45 |
| │   ├── test_left_join.py                                      |          47 |
| │   ├── test_max.py                                            |        1100 |
| │   ├── test_min.py                                            |         968 |
| │   ├── test_of_type.py                                        |          38 |
| │   ├── test_order_by.py                                       |         100 |
| │   ├── test_order_descending_by.py                            |          45 |
| │   ├── test_reverse.py                                        |          35 |
| │   ├── test_select.py                                         |         140 |
| │   ├── test_select_many.py                                    |          85 |
| │   ├── test_single.py                                         |          34 |
| │   ├── test_single_or_default.py                              |          48 |
| │   ├── test_skip.py                                           |          75 |
| │   ├── test_skip_last.py                                      |        1221 |
| │   ├── test_sum.py                                            |         134 |
| │   ├── test_take.py                                           |          39 |
| │   ├── test_take_last.py                                      |        1221 |
| │   ├── test_then_by.py                                        |          40 |
| │   ├── test_then_descending_by.py                             |          34 |
| │   ├── test_to_dictionary.py                                  |          32 |
| │   ├── test_to_list.py                                        |          40 |
| │   ├── test_union.py                                          |          62 |
| │   ├── test_where.py                                          |          76 |
| │   └── test_zip.py                                            |         101 |
| └── task/                                                      |             |
|     ├── test_cancellation.py                                   |          69 |
|     ├── test_task_completion_source.py                         |          26 |
|     ├── test_task_factory.py                                   |           3 |
|     ├── test_task_rt.py                                        |          12 |
|     └── test_task_rt_core.py                                   |          22 |
--------------------------------------------------------------------------------
| GRAND TOTALS                                                   |        7597 |
================================================================================
```