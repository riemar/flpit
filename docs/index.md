# FlpIt

**Fluent LINQ for Python — flip your iterables.**

FlpIt brings the .NET LINQ query model to ordinary Python iterables, with its behaviour kept as close to
`System.Linq.Enumerable` as Python allows. If you know C# LINQ, you already know most of FlpIt.

```bash
uv add flpit
```

```python
--8<-- "examples/linq/quickstart.py:quickstart"
```

<div class="grid cards" markdown>

- **[Why FlpIt](why-flpit.md)** — the goal behind the library.
- **[Guide](guide/getting-started.md)** — from the first query to JSON.
- **[Semantics](semantics/index.md)** — what behaves like LINQ, with running proof.
- **[Task runtime](task/index.md)** — structured concurrency for sync and async code.

</div>
