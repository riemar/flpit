# flp

> **Fluent LINQ for Python – flip your iterables**

`flp` brings .NET's LINQ fluent API to standard Python iterables with full static typing.

## ⚡ Key Features

* **⚡ Lazy Evaluation (`FlpIt`):** Deferred evaluation via pure Python generator expressions.
* **📦 Eager Container (`FlpList`):** Persisted state backed by `collections.UserList`.
* **🔹 Static-First Typing:** Built for full `mypy` and `pyright` inference without plugins.
* **🟢 O(1) Boundary Validation:** Boundary checks rely on O(1) sampling instead of O(N) scans.

## ⚙️ Installation

```bash
uv add flp
```

## 💡 Quick Start

```python
from flp import FlpList, FlpIt

# Eager collection
data = FlpList([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

# Deferred / lazy pipeline
query: FlpIt[int] = (
    data
    .where(lambda x: x % 2 == 0)
    .select(lambda x: x * 10)
)

# Materialization happens explicitly
result: FlpList[int] = query.to_list()  # [20, 40, 60, 80, 100]
```

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.
