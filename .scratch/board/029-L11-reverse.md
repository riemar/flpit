---
id: L11
title: reverse
status: todo
priority: 029
effort: S
depends_on: [F05, F06, F07, F08, F09, L04]
upstream:
  dotnet: ReverseTests.cs @ dotnet/runtime main 6f1d9331 (5 [Fact]/[Theory]; ReverseData has 8 rows)
  morelinq: n/a
pr:
---

# L11: `reverse`

## 1. Goal
`Reverse()` keeps "newest first" and "walk back from the end" inside the pipeline. Python has `reversed()`, but it only works on sequences and breaks the fluent chain. The card also settles the naming clash with `list.reverse()` (in-place, returns `None`), which `FlpList` users may expect.

## 2. Scope
**In:** `reverse()` on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`); `reversed()` fast path for immutable sequences; README deviation entry for the name clash.
**Out:** an in-place `FlpList.reverse` (never: LINQ operators do not mutate FlpList, README 3.1). `.NET 10 Reverse(this T[])` overload: it exists only to win C# overload resolution over `MemoryExtensions.Reverse(Span)`; Python has no such ambiguity.

## 3. Detailed design
### 3.1 Signatures
```python
def reverse(self) -> FlpIt[TItem]: ...
```
| .NET | Python |
|---|---|
| `Reverse(IEnumerable<T>)` | `reverse()` |
| `Reverse(T[])` (.NET 10) | `reverse()` (same method; no array distinction, `NO_SPAN_OR_ARRAY` note) |

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: **full**. Nothing happens at construction; on the first `next()` the whole source is read into a buffer, then yielded back to front.
- Snapshot semantics: the buffer is taken at enumeration start (as .NET's `ReverseIterator` does with `ToArray()` on the first `MoveNext`). Mutating a source list *during* enumeration does not affect the running enumeration; mutating it *before* enumeration is observed.
- Re-enumeration re-reads the source (re-iterable source → same result; one-shot → empty the second time).
- Empty source → empty; `None` elements kept.
- On `OrderedIt`: returns `FlpIt`. Note for docs: `order_by(k).reverse()` is **not** `order_by_descending(k)`: with equal keys, `reverse` flips their original order, `order_by_descending` keeps it (stable).
- **Name clash (README § "Intentional Semantic Deviations", next to `count()`):** `FlpList.reverse()` follows LINQ: it returns a deferred `FlpIt` and **does not** reverse in place (Python `list.reverse()` mutates and returns `None`). `FlpList` is not a `list`. The builtin `reversed(flp_list)` keeps working through the sequence protocol (`__len__` + `__getitem__`).
- Exceptions from the source propagate on the first `next()`.

### 3.3 Implementation sketch
```python
def reverse(self):
    seq = self._indexable()                                # L04 helper
    if seq is not None and type(seq) in (tuple, range, str):
        return FlpIt(_FactoryIterable(lambda: reversed(seq)))   # immutable: O(1) memory, no copy
    def _generator():
        buffer = list(self)                                # snapshot at enumeration start
        buffer.reverse()
        return iter(buffer)
    return FlpIt(_FactoryIterable(_generator))
```
- Generic: O(n) time, O(n) memory, all C-level (`list()` + in-place `reverse`).
- Immutable sequences (`tuple`, `range`, `str`): `reversed()` is O(1) memory; no snapshot is needed because they cannot change.
- **`list` / `FlpList` sources take the generic path on purpose**: a live `reversed(list)` would observe mutation during enumeration, violating the snapshot rule; `list(data)` is a memcpy-speed copy, so a "fast path" would buy nothing. No FlpList override. The PR records the measurement (`data[::-1]` vs `list(data)` + `reverse()`).

### 3.4 Registry entry
```toml
[operators.reverse]
category = "ordering"
kind = "intermediate"
buffering = "full"
short_circuit = false
dotnet = "Enumerable.Reverse"
python_equivalent = "reversed(xs) / xs[::-1]"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_reverse.py` from `ReverseTests.cs` (5; `ReverseData`: 4 int arrays + their `ToString()` projections = 8 rows):
  - `Reverse`: over `flp_type` and `non_collection`. Sub-asserts use `count`, `to_list`, `first_or_default` (L07), `last_or_default` (L08), `element_at` (L10), `skip` (L01), `take`, `select`, `where`. `ElementAtOrDefault(-1)` is dropped (`NO_INDEX_RANGE_TYPE`: `-1` means last in flpit, L10); `ElementAtOrDefault(Length)` → `element_at_or_default(len) is None`; `default(T)` → `None`.
  - `ReverseArray`: ported with a `tuple` source (exercises the `reversed()` path) since Python has no array overload.
  - `RunOnce`: ported with the `run_once` fixture.
  - `InvalidArguments` → `flp_type(None)` raises `SourceNoneError`.
  - `INTERNAL_OPTIMIZATION`: `ForcedToEnumeratorDoesntEnumerate`.
  - Target: 4 of 5 (80 %).
- **Own unit tests** (`tests/unit/test_reverse.py`):
  - Snapshot: appending to the source list during enumeration does not change the running enumeration; mutation before enumeration is visible.
  - `FlpList.reverse()` leaves the FlpList unchanged and returns an `FlpIt`.
  - `order_by(k).reverse()` vs `order_by_descending(k)` with equal keys (documents the stability difference).
  - `tuple`, `range`, `str` sources give the same results as `non_collection`.
  - Source pulls: 0 before the first `next()`, all of them during it.
- **Contracts** (auto): deferral, one-shot, FlpList not mutated, buffering `full`.
- **Typing**: `assert_type(flp.lst([1]).reverse(), FlpIt[int])`; `OrderedIt` input returns `FlpIt`.

## 5. Differential harness
`difftest/specs/reverse.toml`: sources empty, singleton, distinct ints, ints with duplicates, strings, `None`-containing; compositions `reverse()`, `reverse().take(2)`, `order_by(k).reverse()` with duplicate keys; probes `result`, `elements_pulled_before_first_yield`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_reverse.py`, sizes 1e3 / 1e5:
- `native`: `data[::-1]` (list) and `list(reversed(tuple_data))`
- `flpit-FlpIt` (list and tuple sources) / `flpit-FlpList`: `.reverse().to_list()`
- Target ratio ≤ 1.3× (buffering op).

## 7. Docs
- Docstring: `.NET: Enumerable.Reverse()`; snapshot at enumeration start; "does not mutate; unlike `list.reverse()`"; stability note vs `order_by_descending`; Execution: Deferred, Full buffering.
- Doctest: `flp.it([1, 2, 3]).reverse().to_list()` gives `[3, 2, 1]`; `flp.lst([1, 2]).reverse().to_list()` gives `[2, 1]`.
- README deviation entry "`reverse()` does not reverse in place". Translation map: `reversed(xs)` / `xs[::-1]` / `.Reverse()` → `.reverse()`.

## 8. Expected outcomes
- `reverse` on all four types; 4 ported methods green (8 data rows × sources); deviation documented next to `count()`.

## 9. Verification
VERIFY-std with `<op>=reverse`, plus:
```bash
uv run pytest -q tests/nettests/test_reverse.py -rs
uv run python -c "from flpit import flp; xs = flp.lst([1, 2, 3]); print(xs.reverse().to_list(), xs)"   # [3, 2, 1] [1, 2, 3]
```

## 10. Definition of Done
DoD-std, plus the README deviation entry and the PR note on the list fast-path measurement.

## 11. Risks / open questions
- If L07, L08 or L10 slip behind this card, the corresponding sub-asserts in the ported `Reverse` theory are temporarily commented with `OTHER: needs <card>` and restored when the card lands.
