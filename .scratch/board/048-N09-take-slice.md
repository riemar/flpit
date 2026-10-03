---
id: N09
title: take(slice) (Take(Range))
status: todo
priority: 048
effort: M
depends_on: [F05, F06, F07, F08, F09, L01, L04, L05, L07, L08, L10]
upstream:
  dotnet: TakeTests.cs @ dotnet/runtime main 6f1d9331 (55 [Fact]/[Theory])
  morelinq: n/a
pr:
---

# N09: `take(slice)` (.NET `Take(Range)`)

## 1. Goal
.NET 6 `Take(Range)` takes any contiguous window, counted from the start or the end, from any sequence, in one streaming or bounded-buffer pass: `Take(2..^1)`, `Take(^3..)`. Python already has the perfect spelling, the `slice`: `take(slice(2, -1))`, `take(slice(-3, None))`. This card adds that overload with **exactly Python list-slicing results** (which coincide with .NET's clamping rules) but without materialising the source, and ports the whole of `TakeTests.cs`: today `tests/nettests/test_take.py` ports only a subset (its header says ranges are "not possible in python"; there are no `pytest.skip` markers, the Range cases were simply left out).

## 2. Scope
**In:** `take(slice)` overload on `_LinqOps`; eager validation of `take(int)` (bug fixes below); private helper `_count_if_cheap()` (published by N10); a shared from-end iterator used by `take_last` (L04) and `skip_last` (L05), as .NET does with `TakeRangeFromEndIterator`; full port of `TakeTests.cs`.
**Out:** `skip(slice)` (no .NET counterpart); slices with a step (`take_every`, M21); `element_at` with negative index (L10); `FlpList.__getitem__` slicing (already Python slicing, returns `FlpList`, eager).

### Current implementation issues (fixed in scope)
| Today | Fix |
|---|---|
| `take(None)` raises an incidental `TypeError` from `None <= 0` | `ArgumentNoneError("count")` |
| `take(1.5)` passes the check and fails lazily inside `islice` (`ValueError`) | `operator.index` at call: `TypeError` |
| `take(slice(...))` raises `TypeError` from `slice <= 0` | new overload |

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def take(self, count: int) -> FlpIt[TItem]: ...
@overload
def take(self, range_: slice, /) -> FlpIt[TItem]: ...
def take(self, count: int | slice) -> FlpIt[TItem]: ...   # implementation; keyword `count=` keeps working
```
| .NET | flpit |
|---|---|
| `Take(int count)` | `take(count)` |
| `Take(Range range)`: `a..b`, `a..`, `..b` | `take(slice(a, b))`, `take(slice(a, None))`, `take(slice(None, b))` |
| `^k` (from end, k > 0) | `-k` |
| `^0` as **end** | `None` |
| `^0` as **start** (`Take(^0..x)`, always empty) | no spelling (`-0 == 0`); documented |

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming for `int` and for non-negative bounds; partial otherwise (bounded buffer, below). Short-circuit: stops pulling once the window is complete when `stop >= 0`.
- **Specification**: `list(q.take(s)) == list(q)[s]` for every `slice` with `step in (None, 1)`, on any source. Python's clamping rules equal .NET's (`Take` never throws for out-of-range bounds): negative bounds below `-len` clamp to 0, bounds past the end clamp to `len`, `start >= stop` after normalisation is empty.
- Validation (eager): `slice.step` not `None`/`1` → `ArgumentOutOfRangeError("range")` (a `ValueError`) with message "step must be None or 1; use take_every for strides"; `start`/`stop` must be `None` or index-like (`operator.index`), else `TypeError`.
- **Known-empty windows return an empty query without touching the source** (as .NET): both bounds non-negative with `start >= stop`; both bounds negative with `stop >= start` (e.g. `slice(-2, -3)`).
- Pull behaviour by bound kind (mirrors `Take.cs`; `n` = source length):
  | start | stop | strategy | first element yielded after | memory |
  |---|---|---|---|---|
  | `>= 0`/`None` | `>= 0` | `islice(src, a, b)` | pulling `a+1` elements | O(1) |
  | `>= 0`/`None` | `None` | `islice(src, a, None)` | pulling `a+1` elements | O(1) |
  | `>= 0`/`None` | `-e` | skip `a`, then sliding queue of size `e` | pulling `a+e+1` elements | O(e) |
  | `-s` | any | `deque(maxlen=s)` over the whole source | the source is exhausted | O(s) |
- **Count fast path** (as .NET's `TryGetNonEnumeratedCount` check inside the iterator): at enumeration time, if `_count_if_cheap()` knows `n` (a `Sized` source: list, tuple, range, FlpList, dict, set, ...), negative bounds are converted with `slice(start, stop).indices(n)` and the window is read with `islice`, streaming, no buffer. Evaluated per enumeration, so mutations of a backing list between enumerations are seen (`MutableSource` tests).
- `None` elements and falsy elements are passed through untouched.
- Re-enumeration recomputes everything (re-iterable stays re-iterable).
- **Deviations** (README § Intentional Semantic Deviations, "take(slice) mirrors Take(Range)"): `^0` as start has no spelling; a step other than 1 is rejected rather than supported.

### 3.3 Implementation sketch
```python
def take(self, count):
    if isinstance(count, slice):
        return self._take_slice(count)
    count = _require_index(count, "count")       # ArgumentNoneError / TypeError
    if count <= 0:
        return FlpIt(())
    src = self._source()
    return FlpIt(_FactoryIterable(lambda: islice(src, count)))

def _take_slice(self, s):
    start, stop = _normalise_slice(s)            # validates step, operator.index on bounds
    a = 0 if start is None else start
    if (a >= 0 and stop is not None and stop >= 0 and a >= stop) or \
       (a < 0 and stop is not None and stop < 0 and stop >= a):
        return FlpIt(())
    if a >= 0 and (stop is None or stop >= 0):
        src = self._source()
        return FlpIt(_FactoryIterable(lambda: islice(src, a, stop)))
    return FlpIt(_FactoryIterable(lambda: _take_range_from_end(self, a, stop)))

def _take_range_from_end(q, a, stop):            # shared with take_last / skip_last
    n = q._count_if_cheap()
    if n is not None:
        lo, hi, _ = slice(a, stop).indices(n)
        yield from islice(q._source(), lo, hi); return
    it = iter(q._source())
    if a < 0:                                     # start from end: buffer last -a items
        counter = count()
        dq = deque(map(itemgetter(0), zip(it, counter)), maxlen=-a)   # C-level, counts n
        n = next(counter); m = len(dq)
        lo, hi, _ = slice(a, stop).indices(n)
        yield from islice(dq, lo - (n - m), hi - (n - m))
    else:                                         # start from start, stop = -e: sliding queue
        e = -stop
        it = islice(it, a, None)
        dq = deque(islice(it, e))
        if len(dq) < e: return
        for x in it:
            yield dq.popleft(); dq.append(x)
```
- `zip(it, counter)` pulls from `it` first, so `next(counter)` after exhaustion is exactly `n` (no Python-level loop for the buffering pass).
- Time O(n) worst case; memory O(|start|) or O(|stop|) for negative bounds, O(1) otherwise.
- `_count_if_cheap()` (private): `len(src)` if the underlying source is `Sized`, else `None`. Introduced here because N09 ships before N10; N10 extends it (count-preserving operators) and exposes it as `try_get_non_enumerated_count()`.
- L04 `take_last(n)` is `_take_range_from_end(q, -n, None)` and L05 `skip_last(n)` is `(0, -n)`; refactor them onto this helper if their benchmarks do not regress.
- **FlpList fast path**: none (the count path already streams the backing list with `islice`). Measure `iter(data[lo:hi])` against `islice` for a large `lo`; adopt only with a > 20 % gain and identical behaviour.

### 3.4 Registry entry (updates the existing `take` row)
```toml
[operators.take]
category = "partitioning"
kind = "intermediate"
buffering = "partial"
short_circuit = true
origin = "dotnet"
dotnet = "Enumerable.Take"
python_equivalent = "islice(xs, n) / list(xs)[a:b]"
since = "0.1.0"
card = "N09"
notes = "take(slice) = Take(Range); list-slice results; negative bounds buffer at most |bound| items unless the count is known."
```

## 4. Tests
- **Ported** `tests/nettests/test_take.py` rewritten as a full port of `TakeTests.cs` (55 cases), upstream names kept; the existing flpit-specific cases (`Bomb`/`Falsy`, `NoIterList`, pull counts, helper-exception checks) move to `tests/unit/test_take.py` unchanged. Range expressions translate mechanically (`^k` → `-k`, end `^0` → `None`). Expected skips:
  - `NO_INDEX_RANGE_TYPE` (single assertions, not whole tests): `^0` as start, e.g. `Take(^0..^6)` in the `OutOfBound*` and `*DoNotThrowException` tests; each dropped line gets a comment.
  - `INTERNAL_OPTIMIZATION`: `SkipTakeOnIListIsIList` (IList view type).
  - `OTHER` (no `Dispose` on Python iterators; `take` never closes upstream): `DisposeSource` theory. `DisposeSource_StartIndexFromEnd_*` and `DisposeSource_EndIndexFromEnd_*` are ported for their pull-count assertions (state after first `next()`), dispose assertions dropped.
  - `LONG_RUNNING`: `LazySkipAllTakenForLargeNumbers[int.MaxValue]` (.NET fuses skip/take partitions; Python would iterate 2³¹ elements); the 1000 and 1e6 cases run.
  - `ListPartition` / `EnumerablePartition` variants are behavioural and ported via `skip(0)` / `select` wrappers (L01).
  - Target: ≥ 90 % (≥ 50/55 test functions fully or partially ported).
- **Own unit tests** (`tests/unit/test_take.py`):
  - Property: `list(src.take(slice(a, b))) == list(data)[a:b]` for all `a, b in range(-7, 8) ∪ {None}`, `len(data) in 0..5`, on a `list` source and on the `non_collection` fixture (both paths).
  - Pull counts per strategy table row (counting generator), including "first element after `a+e+1` pulls".
  - Known-empty windows never iterate (`NoIterList`).
  - Validation: `slice(0, 3, 2)` → `ArgumentOutOfRangeError`; `slice(0.5, 2)` → `TypeError`; `take(None)` → `ArgumentNoneError`; `take(1.5)` → `TypeError`; all at call time.
  - Mutating a backing list between enumerations is visible (count path evaluated per enumeration).
- **Contracts**: auto via registry.
- **Typing**: `assert_type(flp.it([1]).take(slice(1, None)), FlpIt[int])`; `take(3)` unchanged.

## 5. Differential harness
`difftest/specs/take.toml` gains a `range` argument: `start, end ∈ {0, 1, 2, len-1, len, len+1, 2**31-1} ∪ {^1, ^2, ^len, ^(len+1), ^(2**31-1)}`, plus end `^0` (as `None`); start `^0` excluded (no Python spelling). Sources: empty, singleton, 10 ints, nulls; both array and non-collection (`ForceNotCollection`) on the C# side. Probes: values, `elements_pulled` before the first element. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_take.py` (extends the existing take benchmark), sizes 1e3 and 1e5, generator source unless noted:
- `slice(n//4, 3*n//4)`: native `list(islice(gen, a, b))`.
- `slice(-k, None)`, k = 100: native `list(deque(gen, maxlen=k))`.
- `slice(0, -k)`: native manual `deque` sliding loop.
- list source, `slice(-k, None)`: native `data[-k:]`.
- Target ratio ≤ 1.5× streaming cases, ≤ 1.3× buffering cases.

## 7. Docs
- Docstring (`take`): adds the slice form: "`take(slice(a, b))` returns the same elements as `list(source)[a:b]` without materialising the source"; table of bound kinds and memory; `.NET: Enumerable.Take(Range)`; `^k` ↔ `-k`. Example:
  ```python
  >>> flp.it(range(10)).take(slice(2, -3)).to_list()
  [2, 3, 4, 5, 6]
  >>> flp.it(x for x in range(10)).take(slice(-3, None)).to_list()
  [7, 8, 9]
  ```
- README: deviation entry; "Migrated .NET Unit Tests" table updated (55 upstream cases, skips by category).
- Translation map: `.Take(2..^1)` → `.take(slice(2, -1))`; `.Take(^3..)` → `.take(slice(-3, None))`; `list(xs)[a:b]` / `islice` → `.take(slice(a, b))`.

## 8. Expected outcomes
- `take(slice)` with list-slice results, bounded memory, and the count fast path.
- `take(int)` validates eagerly. `test_take.py` is a complete port.
- L04/L05 share the from-end helper. Benchmark and difftest 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=take`, plus:
```bash
uv run pytest -q tests/nettests/test_take.py -rs      # skips: 1 INTERNAL_OPTIMIZATION, 1 OTHER, 1 LONG_RUNNING param
uv run python -c "from flpit import flp; print(flp.it(x for x in range(10)).take(slice(-3, None)).to_list())"   # [7, 8, 9]
uv run python -c "from flpit import flp; flp.it([1]).take(slice(0, 3, 2))"   # ArgumentOutOfRangeError at call
```

## 10. Definition of Done
DoD-std, plus: property test against list slicing green on both source kinds; `_count_if_cheap` documented as the hook N10 builds on.

## 11. Risks / open questions
- Ordering with N10: this card introduces `_count_if_cheap` in its minimal form (`Sized` check). If N10 is implemented first, reuse its version instead.
- `Sized` sources whose `__len__` is expensive or lies are trusted (same assumption as .NET `ICollection<T>.Count`); documented.
- Mixed overload parameter naming (`count` vs positional-only `range_`) needs a pyrefly check; fall back to a single `count: int | slice` parameter if the overload/implementation consistency check complains.
