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
* **🧠 Lazy Internal Materialization:** Some operators, such as ordering, require internal materialization during deferred execution, while the query itself remains lazy.
* **🔹 Static-First Typing:** Designed for precise `pyrefly` inference without plugins (mypy and pyright might give varying results).
* **🐍 Python-Native:** Built on standard Python iterables, iterators, generators, and callable semantics.

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

## 🔬 LINQ Semantics, Python Runtime

`flpit` deliberately separates the two:

- **LINQ defines the query semantics.**
- **Python provides the underlying iterable and execution model.**

For example:

```python
query.any()
query.first()
query.single()
```

use LINQ semantics, while native Python operations remain Pythonic:

```python
any(query)
list(query)
```

This provides a predictable LINQ vocabulary without attempting to replace Python's native iteration model.

## 🔗 Independent Queries

LINQ queries are composable without mutating the query they were derived from.

For example:

```python
@dataclass
class Item: group: str; value: int

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

## 🧠 Lazy Pipelines

Streaming operations do not materialize intermediate results:

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
to_list     ← consumer-facing materialization
```

Operations such as `order_by()` necessarily materialize their input internally to establish ordering.

## ⚙️ Installation

```bash
uv add flpit
```

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.