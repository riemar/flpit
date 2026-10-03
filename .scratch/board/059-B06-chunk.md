---
id: B06
title: chunk
status: todo
priority: 059
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: ChunkTests.cs @ dotnet/runtime main 6f1d9331 (12 [Fact]/[Theory])
  morelinq: n/a (MoreLINQ Batch is the same operator; skipped by D16)
pr:
---

# B06: `chunk` (backfill)

## 1. Goal
`chunk` already validates `size` eagerly, but reading `linq.py` against `ChunkTests.cs` shows: (1) `size` is compared with `<= 0` only, so `chunk(2.5)` is accepted and silently yields one chunk with everything (`len(chunk) == 2.5` is never true); (2) the error is a plain `ValueError` instead of `ArgumentOutOfRangeError("size")`; (3) it is a per-element Python loop, ~24× slower than `itertools.batched` (0.33 s vs 0.014 s for 20 × 1e5 elements, size 10). `batched` itself has a trap: it preallocates a `size`-slot tuple per batch, so `batched(range(10), 2**31 - 1)` raises `MemoryError` on 3.12 and 3.13, exactly the case of the .NET test `DoesNotPrematurelyAllocateHugeArray`. This card fixes all of it and ports the tests.

## 2. Scope
**In:** `chunk(size)` on `_LinqOps`; `operator.index` validation; `ArgumentOutOfRangeError`; `batched`-based implementation with a large-size fallback; port of `ChunkTests.cs`.
**Out:** returning tuples or arrays (chunks stay `FlpList`, existing contract); `strict=` mode of 3.13 `batched` (no .NET equivalent).

## 3. Detailed design
### 3.1 Signatures
```python
def chunk(self, size: int) -> FlpIt[FlpList[TItem]]: ...
```
.NET `Chunk(source, size)` returns `IEnumerable<TSource[]>`; flpit yields `FlpList[TItem]` (mutable, independent per chunk, consistent with M02 windows).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (one chunk, ≤ `size` elements). Short-circuit: `chunk(k).first()` pulls exactly `min(k, len)` elements.
- Validation (eager): `size = operator.index(size)` (`None` → `ArgumentNoneError("size")`, `2.5` → `TypeError`); `size <= 0` → `ArgumentOutOfRangeError("size", size)`, message format owned by F05, parameter name `size` as .NET. `ArgumentOutOfRangeError` subclasses `ValueError`, so the existing `pytest.raises(ValueError)` tests stay green.
- Last chunk may be shorter; empty source → no chunks. Each chunk is a new `FlpList`; mutating one does not affect the source or other chunks.
- Live list source: mutations made before enumeration are visible (`RemovingFromSourceBeforeIterating`, `AddingToSourceBeforeIterating`).
- Huge `size` (`2**31 - 1`, `2**62`) on a small source returns one chunk without large allocation.
- `bool` sizes: `chunk(True)` is `chunk(1)` (Python `int` subtype; documented, not special-cased).

### 3.3 Implementation sketch
```python
_BATCHED_MAX = 4096          # tuned by the benchmark; above it batched would preallocate too much

def chunk(self, size):
    size = _require_index(size, "size")
    if size <= 0:
        raise ArgumentOutOfRangeError("size", size)
    if size <= _BATCHED_MAX:
        def _generator():
            return map(_flplist_from_tuple, batched(self, size))     # C-level batching
    else:
        def _generator():
            it = iter(self)
            while batch := list(islice(it, size)):                   # grows dynamically, no preallocation
                yield FlpList._adopt(batch)
    return FlpIt(_FactoryIterable(_generator))
```
- O(n) time, O(size) memory per chunk. `_flplist_from_tuple` = `FlpList._adopt(list(t))`; `FlpList._adopt` is the no-copy private constructor from B09. Without it each `FlpList(...)` costs ~1.4 µs (it goes through `UserList[TItem](...)`), which dominates for small chunks.
- **FlpList fast path** (slicing `data[i:i + size]`): rejected unless measured ≥ 20 % faster than `batched`; it also changes behaviour when the list is mutated *during* enumeration (slices see later mutations at different offsets than an iterator).

### 3.4 Registry entry
```toml
[operators.chunk]
category = "partitioning"
kind = "intermediate"
buffering = "partial"
short_circuit = false
dotnet = "Enumerable.Chunk"
python_equivalent = "itertools.batched(xs, n)"
since = "0.2.0"          # pre-registry operator
```

## 4. Tests
- **Ported** `tests/nettests/test_chunk.py` from `ChunkTests.cs` (12):
  - Ported (11): `Empty`, `ThrowsWhenSizeIsNonPositive` (0, -1 → `ArgumentOutOfRangeError`, param `size`), `ChunkSourceLazily` (`FastInfiniteEnumerator` → `itertools.repeat(0)`), `ChunkSourceRepeatCalls`, `ChunkSourceEvenly`, `ChunkSourceUnevenly`, `ChunkSourceSmallerThanMaxSize`, `EmptySourceYieldsNoChunks` (`CreateSources` → list, tuple, `NonCollectionIterable`, generator factory), `RemovingFromSourceBeforeIterating`, `AddingToSourceBeforeIterating` (for `FlpIt` mutate the wrapped `list`; for `FlpList` mutate the `FlpList` via slice assignment / `add`, because `flp.lst` copies its input), `DoesNotPrematurelyAllocateHugeArray` (size `2**31 - 1`).
  - Skips: `OTHER` 1 (`ThrowsOnNullSource`).
  - Target: 11/12 ≈ 92 % ported.
- **Own unit tests** (`tests/unit/test_chunk.py`):
  - `chunk(2.5)`, `chunk("3")`, `chunk(None)` raise at call time; `chunk(0)` error is both `ArgumentOutOfRangeError` and `ValueError`.
  - Sizes `_BATCHED_MAX` and `_BATCHED_MAX + 1` give identical results (both code paths).
  - `chunk(2**62)` on 10 elements returns one chunk (no `MemoryError`).
  - Mutating a yielded chunk does not change the next chunk or a re-enumeration.
  - `chunk(3).first()` pulls exactly 3 elements from an infinite counting source.
- **Contracts** (auto) + the pull-count invariant above.
- **Typing**: `assert_type(flp.it([1]).chunk(2), FlpIt[FlpList[int]])`.

## 5. Differential harness
`difftest/specs/chunk.toml`: `size ∈ {1, 2, 3, len-1, len, len+1, 2**31-1}`; sources {empty, singleton, 9 ints, strings}; invalid sizes {0, -1} → exception family `ArgumentOutOfRange`; probe `elements_pulled` for `.chunk(k).first()`. Chunks compared as lists (`int[]` ↔ `FlpList`). Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_chunk.py`, sizes 1e3 and 1e5, chunk sizes 10 and 1000:
- `native`: `[list(b) for b in itertools.batched(data, k)]`.
- `flpit-FlpIt`, `flpit-FlpList`: `.chunk(k).to_list()`.
- Target ≤ 1.5× (needs `FlpList._adopt`; without B09 expect ≈ 3× at size 10, record it). Today ≈ 24×.

## 7. Docs
- Docstring: `.NET: Enumerable.Chunk(size)`; chunks are independent `FlpList`s; last chunk may be shorter; `Raises: ArgumentOutOfRangeError`. Doctest: `flp.it([1, 2, 3, 4, 5]).chunk(2).to_list()` → `[[1, 2], [3, 4], [5]]`.
- Translation map: `.Chunk(n)` / MoreLINQ `.Batch(n)` / `itertools.batched(xs, n)` → `.chunk(n)`.

## 8. Expected outcomes
- `chunk` rejects non-integer sizes; error type and message match .NET.
- ≥ 10× faster on small chunk sizes; no `MemoryError` for huge sizes.
- 11 ported .NET tests green.

## 9. Verification
VERIFY-std with `<op>=chunk`, plus:
```bash
uv run pytest -q tests/nettests/test_chunk.py -rs
uv run python -c "from flpit import flp; print(flp.it(range(10)).chunk(2**31 - 1).to_list())"   # [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]]
uv run python -c "from flpit import flp; flp.it([1]).chunk(2.5)"                                 # TypeError at call time
```

## 10. Definition of Done
DoD-std, plus: both code paths covered by tests; `_BATCHED_MAX` value justified in the PR with the benchmark.

## 11. Risks / open questions
- Soft dependency on B09 (`FlpList._adopt`) for the benchmark target; functionally independent. If B06 lands first, it uses `FlpList(list(t))` and B09 switches it.
- CPython may stop preallocating in `batched` in a future version; the threshold stays harmless.
