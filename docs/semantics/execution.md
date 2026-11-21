---
description: Which FlpIt operators stream and which buffer their input. Deferred execution, sorting, grouping, joins and last-N operators compared, as in .NET LINQ.
---
# Execution characteristics

Lazy does not mean streaming. Every FlpIt query is deferred, which means nothing runs until it is enumerated,
but some operators must read and buffer their input before they can produce a result. Sorting is the obvious
case: no exact sort can start without seeing every element. That is true of Python's `sorted` and of .NET's
`OrderBy` as well.

| Operator               | Deferred | Processes incrementally | Buffers input                          |
| ---------------------- | -------- | ----------------------- | -------------------------------------- |
| `where()` / `select()` | Yes      | Yes                     | No                                     |
| `index()`              | Yes      | Yes                     | No                                     |
| `default_if_empty()`   | Yes      | Yes                     | No                                     |
| `skip_last()`          | Yes      | Yes                     | `count` elements (none on `FlpList`)   |
| `take_last()`          | Yes      | No (`FlpList`: Yes)     | `count` elements (none on `FlpList`)   |
| `order_by()`           | Yes      | No                      | Yes                                    |
| `group_by()`           | Yes      | No                      | Yes                                    |
| `join()`               | Yes      | Yes (outer)             | Yes (inner)                            |
| `left_join()`          | Yes      | Yes (outer)             | Yes (inner)                            |
| `full_join()`          | Yes      | Yes (outer)             | Yes (inner)                            |
| `group_join()`         | Yes      | Yes (outer)             | Yes (inner)                            |
| `cross_join()`         | Yes      | Yes (outer)             | Yes (inner)                            |

`order_by()` and `group_by()` stay deferred when the query is built. Enumerating either one buffers its input.
The [chaining page](chaining.md#operators-that-must-see-everything) shows that as running code.

## A pipeline, conceptually

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
order_by    ← deferred, buffers its input when enumerated
  │
  ▼
take        ← streaming
  │
  ▼
to_list     ← terminal: runs the query and returns a FlpList
```

Terminal operators (`any`, `first`, `single`, `count`, `aggregate`, `to_list`, ...) run the query and return a
result instead of another query. `aggregate` processes its source incrementally but must consume all of it to
produce the final value.

## Details

**Last elements.** On `FlpIt`, `skip_last()` streams with a look-ahead of `count` elements: it holds back at
most `count` elements and releases each as soon as `count` newer ones were read. `take_last()` cannot know which
elements are last until the source is exhausted, so its first element appears only after the whole source was
read, once; it keeps at most `count` elements in memory. `FlpList` knows its length and indexes directly,
without buffering. With `count <= 0`, `skip_last()` returns every element and `take_last()` is empty without
reading the source.

**Joins.** `join`, `left_join`, `full_join` and `group_join` build a hash lookup of the inner sequence when
enumeration starts (`group_join`: when the outer sequence yields its first element) and stream the outer
sequence, so the cost is O(N + M). `cross_join` buffers the inner sequence into a list once, because it is
traversed again for every outer element, and the output size is N × M.

**Lookups.** `to_lookup(key_selector[, element_selector])` is the terminal counterpart (.NET `ToLookup`). It
reads the source once, immediately, and returns a read-only, re-enumerable `Lookup`: a `FlpIt` of groupings in
order of first key appearance. See [Joins and lookups](../guide/joins.md#lookups).

**Empty sources.** `default_if_empty(default)` streams the source unchanged and yields `default` only if the
source produced nothing. Falsy elements such as `0` or `None` do not count as empty.
