# flp

> **Fluent LINQ for Python – flip your iterables**

`flp` brings a LINQ-inspired fluent API to standard Python iterables with full static typing.

## ⚡ Key Features

* **⚡ Lazy Evaluation (`FlpIt`):** Deferred execution using Python iterators and generators.
* **📦 Materialized Container (`FlpList`):** Eager, mutable container backed by `collections.UserList`.
* **🔹 Static-First Typing:** Built for full `mypy` and `pyright` inference without plugins.
* **🔄 No Implicit Caching:** Query results are not cached unless explicitly documented, such as `order_by`.

## ⚙️ Installation

```bash
uv add flpit
```

## 💡 Quick Start

```python
import flp
from flp import FlpIt, FlpList

# Deferred iterable via shorthand
data: FlpIt[int] = flp.it([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

# Deferred / lazy pipeline
query: FlpIt[int] = (
    data
    .where(lambda x: x % 2 == 0)
    .select(lambda x: x * 10)
)

# Materialize query results explicitly
result: FlpList[int] = query.to_list()  # [20, 40, 60, 80, 100]

# Or start directly with an eager container
eager_list: FlpList[int] = flp.lst([1, 2, 3, 4])
```

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.
