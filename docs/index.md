---
description: "Flip your iterables: fluent, typed, lazy LINQ for Python with .NET semantics, async streams, JSON/CSV and an asyncio-free task runtime."
---
# FlpIt

**Fluent LINQ for Python — flip your iterables.**

FlpIt brings the .NET LINQ query model to ordinary Python iterables, with its behaviour kept as close to
`System.Linq.Enumerable` as Python allows. If you know C# LINQ, you already know most of FlpIt.

Queries are the doorway. Around them FlpIt carries over other parts of the .NET programming model: async streams
(`AsyncFlpIt`), typed JSON and CSV serialization, an `asyncio`-free task runtime, channels and concurrent collections. It is
tested on free-threaded Python (>=3.14t) in CI.

```bash
uv add flpit
```

```python
--8<-- "examples/linq/quickstart.py:quickstart"
```

<div class="grid cards" markdown>

- **[Why FlpIt](why-flpit.md)**: the goal behind the library.
- **[Guide](guide/getting-started.md)**: from the first query to joins, JSON and CSV.
- **[Async queries](async/index.md)**: the same operators over `async for`.
- **[Semantics](semantics/index.md)**: what behaves like LINQ, with running proof.
- **[Task runtime](task/index.md)**: tasks, cancellation, channels and concurrent collections.
- **[Explore .NET](dotnet.md)**: where all of this comes from, and how to try it.

</div>
