# FlpIt

**[📖 Documentation](https://riemar.github.io/flpit/)** | **[🌐 GitHub](https://github.com/riemar/flpit)** | **[📦 PyPI](https://pypi.org/project/flpit/)**

> **Fluent LINQ for Python — LINQ semantics, Python-native execution**

`FlpIt` brings a strongly typed, LINQ-style API to standard Python iterables. It combines the fluent query model and semantics of .NET LINQ with Python's native iterable and generator model.

If you know C# LINQ, you already know most of FlpIt. Existing LINQ examples, query patterns and documentation can generally be translated directly, which makes the .NET LINQ ecosystem a valuable reference for developers and AI coding assistants alike.

Queries are the doorway. Around them FlpIt carries over other parts of the .NET programming model: async streams
(`AsyncFlpIt`), typed JSON and CSV serialization, an `asyncio`-free task runtime, channels and concurrent collections. It is
tested on free-threaded Python (>=3.14t) in CI.

> **Semantic goal:** `flp` strives to faithfully reproduce .NET LINQ semantics.
> Where Python's language or type system requires a different API contract, the contract is adapted accordingly,
> and [each deviation is documented](https://riemar.github.io/flpit/semantics/differences/).
> The implementation is actively developed, and further deviations may still exist.

## 💡 Quick Start

```bash
uv add flpit        # or: pip install flpit
```

```python
from flpit import flp, FlpIt, FlpList

# A lazy, streaming pipeline: nothing has run yet.
query: FlpIt[int] = (
    flp.it(range(1, 11))
    .where(lambda x: x % 2 == 0)
    .select(lambda x: x * 10)
)

# Explicit materialization.
result: FlpList[int] = query.to_list()
# [20, 40, 60, 80, 100]
```

## 🤸 Flipping the Pipeline

Native Python functional operations read inside-out. A FlpIt pipeline reads in the order things happen:

```python
# 🔁 Native built-ins
result = list(map(lambda x: x * 10, filter(lambda x: x % 2 == 0, range(1, 11))))

# 🤸 FlpIt pipeline
result = (
    flp.it(range(1, 11))
    .where(lambda x: x % 2 == 0)
    .select(lambda x: x * 10)
    .to_list()
)
```

## ⚡ What's in the Box

* **Lazy queries (`FlpIt`)** and **materialized lists (`FlpList`)**: deferred, streaming execution over any `Iterable[T]`, with `where`, `select`, `select_many`, `order_by`, `group_by`, joins and the rest of `System.Linq.Enumerable`. [Guide](https://riemar.github.io/flpit/guide/getting-started/)
* **Async queries (`AsyncFlpIt`)**: the `IAsyncEnumerable<T>` counterpart, with async callbacks, cancellation and cleanup. [Docs](https://riemar.github.io/flpit/async/)
* **Faithful semantics**: when work happens, how much is read, what comes out and how it fails match .NET, also when operators are chained. Derived queries never affect each other. [Semantics](https://riemar.github.io/flpit/semantics/)
* **Typed JSON and CSV**: dataclasses to and from JSON and CSV, with `msgspec` or a pure-Python backend. [JSON](https://riemar.github.io/flpit/guide/json/), [CSV](https://riemar.github.io/flpit/guide/csv/)
* **Task runtime**: an `asyncio`-free runtime modelled on the .NET thread pool, built for free-threaded Python, with `Task.when_all`, `when_each`, continuations and cooperative cancellation. Blocking and `async def` functions mix freely. [Docs](https://riemar.github.io/flpit/task/), [sync and async](https://riemar.github.io/flpit/task/sync-and-async/)
* **Channels, concurrent collections and threading primitives**: `Channel[T]`, `ConcurrentDictionary`, `SemaphoreSlim` and friends. [Docs](https://riemar.github.io/flpit/concurrency/channels/)
* **Static-first typing**: designed for precise `pyrefly` inference without plugins (mypy and pyright may give varying results).

FlpIt models in-memory LINQ (`IEnumerable`). It does not model `IQueryable` or expression trees.

## ⚙️ Installation

```bash
uv add flpit
```

msgspec is installed automatically on CPython. On other interpreters (PyPy, Pyodide) flpit
installs without it and uses the native JSON backend. Free-threaded CPython 3.13t is not
supported by msgspec: install there with `--no-deps`, or use 3.14t.

## 💬 Feedback

FlpIt is in beta. Bug reports and questions are welcome as [GitHub issues](https://github.com/riemar/flpit/issues).

## 🧭 Like FlpIt? Give .NET a try.

Enjoying FlpIt's .NET-inspired programming model? [Here's where it comes from](https://riemar.github.io/flpit/dotnet/): try C# in your browser, explore LINQ, or keep your Python and call it from .NET.

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.

## Migrated .NET Unit Tests

> Migrated from the official .NET Runtime LINQ Tests.
> Note: The test cases exercise both core types, `FlpIt` and `FlpList`, with transitions between lazy and eager execution occurring as part of the individual test cases.
> `async_linq/` is migrated from the .NET 10 `System.Linq.AsyncEnumerable` tests and exercises `AsyncFlpIt` on the flpit task runtime.
> `channels/` is migrated from the `System.Threading.Channels` tests; `concurrent/` from the `System.Collections.Concurrent` tests, including the shared `IEnumerable` / `ICollection` / `IDictionary` suites of `Common/tests` (ported to `common/`).

```
================================================================================
| Test Module File                                               |  Test Cases |
--------------------------------------------------------------------------------
| tests/nettests/                                                |             |
| ├── async_linq/                                                |             |
| │   ├── test_aggregate.py                                      |          11 |
| │   ├── test_all.py                                            |           7 |
| │   ├── test_any.py                                            |           8 |
| │   ├── test_append.py                                         |          20 |
| │   ├── test_average.py                                        |          10 |
| │   ├── test_cast.py                                           |           6 |
| │   ├── test_chunk.py                                          |           5 |
| │   ├── test_concat.py                                         |          24 |
| │   ├── test_contains.py                                       |          11 |
| │   ├── test_count.py                                          |           8 |
| │   ├── test_default_if_empty.py                               |           7 |
| │   ├── test_distinct.py                                       |          10 |
| │   ├── test_distinct_by.py                                    |          11 |
| │   ├── test_element_at.py                                     |           8 |
| │   ├── test_empty.py                                          |           2 |
| │   ├── test_except.py                                         |          12 |
| │   ├── test_except_by.py                                      |          13 |
| │   ├── test_first.py                                          |           8 |
| │   ├── test_first_or_default.py                               |           8 |
| │   ├── test_full_join.py                                      |          11 |
| │   ├── test_group_by.py                                       |           6 |
| │   ├── test_group_join.py                                     |           9 |
| │   ├── test_index.py                                          |           8 |
| │   ├── test_intersect.py                                      |          12 |
| │   ├── test_join.py                                           |           9 |
| │   ├── test_last.py                                           |           8 |
| │   ├── test_last_or_default.py                                |           8 |
| │   ├── test_left_join.py                                      |          10 |
| │   ├── test_max.py                                            |          11 |
| │   ├── test_max_by.py                                         |          12 |
| │   ├── test_min.py                                            |          11 |
| │   ├── test_min_by.py                                         |          12 |
| │   ├── test_of_type.py                                        |           5 |
| │   ├── test_order_by.py                                       |          18 |
| │   ├── test_prepend.py                                        |          19 |
| │   ├── test_range.py                                          |           3 |
| │   ├── test_repeat.py                                         |           3 |
| │   ├── test_reverse.py                                        |           8 |
| │   ├── test_select.py                                         |           9 |
| │   ├── test_select_await.py                                   |          10 |
| │   ├── test_select_many.py                                    |           5 |
| │   ├── test_single.py                                         |           9 |
| │   ├── test_single_or_default.py                              |           9 |
| │   ├── test_skip.py                                           |           9 |
| │   ├── test_skip_last.py                                      |           9 |
| │   ├── test_sum.py                                            |          10 |
| │   ├── test_take.py                                           |           9 |
| │   ├── test_take_last.py                                      |           9 |
| │   ├── test_to_async_enumerable.py                            |          10 |
| │   ├── test_to_dictionary.py                                  |           5 |
| │   ├── test_to_list.py                                        |           9 |
| │   ├── test_to_lookup.py                                      |           4 |
| │   ├── test_union.py                                          |          12 |
| │   ├── test_where.py                                          |           9 |
| │   ├── test_where_await.py                                    |           6 |
| │   └── test_zip.py                                            |          12 |
| ├── channels/                                                  |             |
| │   ├── test_bounded_channel.py                                |         139 |
| │   ├── test_channel.py                                        |          16 |
| │   ├── test_channel_closed_exception.py                       |           2 |
| │   ├── test_debug_attribute.py                                |           0 |
| │   ├── test_priority_unbounded_channel.py                     |          85 |
| │   ├── test_rendezvous_channel.py                             |         104 |
| │   └── test_unbounded_channel.py                              |         338 |
| ├── concurrent/                                                |             |
| │   ├── test_concurrent_bag.py                                 |         131 |
| │   ├── test_concurrent_dictionary.py                          |          56 |
| │   ├── test_concurrent_dictionary_generic.py                  |        1236 |
| │   ├── test_concurrent_queue.py                               |         130 |
| │   ├── test_concurrent_stack.py                               |         124 |
| │   └── test_etw.py                                            |           0 |
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
| │   ├── test_count.py                                          |          64 |
| │   ├── test_default_if_empty.py                               |          37 |
| │   ├── test_distinct.py                                       |          87 |
| │   ├── test_element_at.py                                     |          43 |
| │   ├── test_except.py                                         |          68 |
| │   ├── test_first.py                                          |          29 |
| │   ├── test_first_or_default.py                               |          50 |
| │   ├── test_full_join.py                                      |          37 |
| │   ├── test_generic_list.py                                   |          87 |
| │   ├── test_group_by.py                                       |          23 |
| │   ├── test_group_join.py                                     |          53 |
| │   ├── test_index.py                                          |           6 |
| │   ├── test_intersect.py                                      |          42 |
| │   ├── test_join.py                                           |          47 |
| │   ├── test_last.py                                           |          29 |
| │   ├── test_last_or_default.py                                |          45 |
| │   ├── test_left_join.py                                      |          47 |
| │   ├── test_max.py                                            |        1098 |
| │   ├── test_min.py                                            |         966 |
| │   ├── test_of_type.py                                        |          38 |
| │   ├── test_order_by.py                                       |         104 |
| │   ├── test_order_descending_by.py                            |          46 |
| │   ├── test_reverse.py                                        |          35 |
| │   ├── test_select.py                                         |         143 |
| │   ├── test_select_many.py                                    |          85 |
| │   ├── test_single.py                                         |          34 |
| │   ├── test_single_or_default.py                              |          48 |
| │   ├── test_skip.py                                           |          77 |
| │   ├── test_skip_last.py                                      |        1221 |
| │   ├── test_sum.py                                            |         154 |
| │   ├── test_take.py                                           |          73 |
| │   ├── test_take_last.py                                      |        1221 |
| │   ├── test_then_by.py                                        |          38 |
| │   ├── test_then_descending_by.py                             |          32 |
| │   ├── test_to_dictionary.py                                  |          32 |
| │   ├── test_to_list.py                                        |          40 |
| │   ├── test_to_lookup.py                                      |          26 |
| │   ├── test_union.py                                          |          62 |
| │   ├── test_where.py                                          |          76 |
| │   └── test_zip.py                                            |         101 |
| ├── task/                                                      |             |
| │   ├── test_aggregate_exception.py                            |           1 |
| │   ├── test_cancellation.py                                   |          69 |
| │   ├── test_method_coverage.py                                |          30 |
| │   ├── test_method_coverage_when_all.py                       |          13 |
| │   ├── test_operation_canceled_exception.py                   |           0 |
| │   ├── test_task_canceled_exception.py                        |           1 |
| │   ├── test_task_completion_source.py                         |          25 |
| │   ├── test_task_completion_source_tresult.py                 |           5 |
| │   ├── test_task_continue_with.py                             |          15 |
| │   ├── test_task_continue_with_func_and_action.py             |          16 |
| │   ├── test_task_continue_with_func_and_action_args.py        |          20 |
| │   ├── test_task_factory.py                                   |           3 |
| │   ├── test_task_rt.py                                        |           7 |
| │   ├── test_task_rt_core.py                                   |          32 |
| │   └── test_task_wait_all_any.py                              |          62 |
| └── threading/                                                 |             |
|     ├── test_semaphore_slim.py                                 |          39 |
|     ├── test_semaphore_slim_cancellation.py                    |           4 |
|     └── test_thread_local.py                                   |          15 |
--------------------------------------------------------------------------------
| GRAND TOTALS                                                   |       10848 |
================================================================================
```