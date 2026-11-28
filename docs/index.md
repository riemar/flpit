---
description: "Python that feels like .NET, until you miss the real thing. LINQ, Tasks, async streams and channels, verified by 10,000+ .NET runtime tests."
---
# FlpIt

**The .NET programming model for Python: LINQ, Tasks, async streams and channels, with .NET's semantics.**

If you know C#, you already know FlpIt. `where` and `select`, `Task.run` and `Task.when_all`,
`CancellationTokenSource`, `Channel.create_bounded`: the names are the ones you expect, and so is the behaviour,
down to when work happens, which exception is raised and what a cancelled task reports. On free-threaded Python
the work runs in parallel, on real threads, without `asyncio`.

- **Verified by .NET's own tests.** More than 10,000 unit tests of the .NET runtime, migrated to Python, run on
  every commit. [How it's checked](semantics/verification.md)
- **One runtime for blocking and async code.** Plain functions, `async def` and asyncio libraries run on one
  worker pool, with .NET's cancellation and exception rules. [Task runtime](task/index.md)
- **Built for free-threaded Python.** Tested on Linux, macOS and Windows with Python 3.12 to 3.15, including the
  free-threaded 3.14t and 3.15t.
- **Docs that cannot lie.** Every snippet on these pages is a real file that runs in CI.

```bash
uv add flpit
```

## Queries

A lazy, typed pipeline, read top to bottom:

```python
--8<-- "examples/linq/quickstart.py:quickstart"
```

## Tasks

Blocking functions, started together on the worker pool, awaited like `Task.WhenAll`:

```python
--8<-- "examples/task/overview.py:when_all"
```

## Coming from .NET

| .NET | FlpIt |
|---|---|
| `source.Where(...).Select(...).ToList()` | `flp.it(source).where(...).select(...).to_list()` |
| `IAsyncEnumerable<T>` with LINQ | `AsyncFlpIt` |
| `Task.Run`, `Task.WhenAll`, `Task.WhenAny` | `Task.run`, `Task.when_all`, `Task.when_any` |
| `CancellationTokenSource`, `TaskCompletionSource` | `CancellationTokenSource`, `TaskCompletionSource` |
| `Channel.CreateBounded<T>(n)` | `Channel.create_bounded(n)` |
| `ConcurrentDictionary`, `SemaphoreSlim` | `ConcurrentDictionary`, `SemaphoreSlim` |
| `JsonConvert.SerializeObject` | `JsonConvert.serialize` |

Where Python forces a difference, it is documented: [Where FlpIt differs](semantics/differences.md).

## Built on FlpIt

[flpit-stoop](https://github.com/riemar/flpit-stoop) is a web framework on FlpIt's Task runtime, in the style of
ASP.NET Core's minimal APIs, served by Granian with threads. On 4 cores of one machine, with free-threaded
Python 3.14, it answers about 113,000 plaintext requests per second; ASP.NET Core on Kestrel reached about 217,000
on the same cores and load.

<div class="grid cards" markdown>

- **[Why FlpIt](why-flpit.md)**: the goal behind the library.
- **[Guide](guide/getting-started.md)**: from the first query to joins, JSON and CSV.
- **[Async queries](async/index.md)**: the same operators over `async for`.
- **[Semantics](semantics/index.md)**: what behaves like LINQ, with running proof.
- **[Task runtime](task/index.md)**: tasks, cancellation, channels and concurrent collections.
- **[Explore .NET](dotnet.md)**: where all of this comes from, and how to try it.

</div>
