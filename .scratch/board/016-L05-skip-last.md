---
id: L05
title: skip_last
status: todo
priority: 016
effort: S
depends_on: [F05, F06, F07, F08, F09, L04]
upstream:
  dotnet: SkipLastTests.cs @ dotnet/runtime main 6f1d9331 (6 [Fact]/[Theory]; theories expand to ~615 rows via SkipTakeData)
  morelinq: n/a (MoreLINQ's own SkipLast is superseded by the .NET operator, D16)
pr:
---

# L05: `skip_last`

## 1. Goal
"Everything except the trailer / the last n samples" without materialising the source. `SkipLast(n)` streams with a lag of exactly n elements, which Python only offers via the `xs[:-n]` slice (lists only, and `xs[:-0]` is empty, a classic bug). Completes the `skip`/`take`/`take_last` family; reuses L04's `_indexable()`.

## 2. Scope
**In:** `skip_last(count)` on `_LinqOps`; `Sequence` fast path via `_indexable()` (L04).
**Out:** `Take(Range)` (N09).

## 3. Detailed design
### 3.1 Signatures
```python
def skip_last(self, count: int) -> FlpIt[TItem]: ...
```
.NET mapping: `SkipLast(int count)` → `skip_last(count)` (single overload).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial, a FIFO of exactly `count` elements. Streaming with lag: when the i-th result is yielded, exactly `count + i` source elements have been pulled (upstream `EvaluationBehavior`). Short-circuit: none beyond what the consumer stops.
- `count <= 0` → the source unchanged (still deferred, streaming, re-iterable as the source is). Unlike `take_last`, the source **is** enumerated.
- `count >= len(source)` → empty, but the source is still fully enumerated (it cannot know the length in advance on the generic path).
- Validation (eager): `operator.index(count)`; `None` → `ArgumentNoneError("count")`.
- Mutation before enumeration is observed (`List_ChangesAfterSkipLast_ChangesReflectedInResults`).
- Re-enumeration restarts with an empty buffer. One-shot stays one-shot.
- Source exceptions propagate at the `next()` that pulls the failing element, which can be up to `count` results earlier than the element's own position (lag), as in .NET.

### 3.3 Implementation sketch
```python
def skip_last(self, count):
    count = _require_index(count, "count")
    if count <= 0:
        return FlpIt(self._source())                    # same as skip(0): deferred pass-through
    seq = self._indexable()                              # L04 helper
    if seq is not None:
        def _generator():
            n = len(seq)
            return iter(seq[:n - count]) if count < n else iter(())
    else:
        def _generator():
            it = iter(self)
            buffer = deque(islice(it, count))            # prefetch `count` elements
            if len(buffer) < count:
                return
            for item in it:
                buffer.append(item)
                yield buffer.popleft()
    return FlpIt(_FactoryIterable(_generator))
```
- Generic: O(n) time, O(count) memory; `islice(it, count)` grows the deque only up to the real source length, so `count = 2**31 - 1` on a short source is cheap. For `count > sys.maxsize` (`islice` limit) the generator drains the source and yields nothing (equivalent).
- Sequence path: the slice `seq[:n - count]` is a copy of n − count elements. Alternative `islice(seq, n - count)` is O(1) memory; the benchmark picks. Either way it is taken at enumeration start; list/tuple/range/str iteration has no side effects, so the lag is unobservable and results/exceptions are identical. Guarded against the `xs[:-0]` trap.

### 3.4 Registry entry
```toml
[operators.skip_last]
category = "partitioning"
kind = "intermediate"
buffering = "partial"
short_circuit = false
dotnet = "Enumerable.SkipLast"
python_equivalent = "xs[:-n]  # n > 0 only; lag-n deque for iterators"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_skip_last.py` from `SkipLastTests.cs`:
  - `SkipLast` theory (300 rows) over `flp_type` and `non_collection`; `*OrDefault`/`ElementAt` sub-asserts handled exactly as in L04 (`ElementAtOrDefault(-1)` dropped with `NO_INDEX_RANGE_TYPE`; `ElementAtOrDefault(Count())` added by L10).
  - `EvaluationBehavior` (15 rows): fully portable for the lag asserts (`index == count + i` when yielding i, via a counting iterator); the final `Dispose` bit check is skipped as `OTHER`.
  - `RunOnce` (300 rows), `SkipLastThrowsOnNull` (`SourceNoneError`), `List_ChangesAfterSkipLast...` (list and FlpList), `List_Skip_ChangesAfterSkipLast...` (uses L01).
  - Target: 100 % of methods ported; only dispose sub-asserts skipped.
- **Own unit tests** (`tests/unit/test_skip_last.py`):
  - Lag contract on the generic path: after the first yielded element, exactly `count + 1` source elements were pulled.
  - Infinite source with `skip_last(3).take(5)` terminates and yields `0..4`.
  - `count <= 0` returns all elements; `count >= len` returns empty but still drains the source (pull counter).
  - Slicing trap: `flp.lst([1, 2, 3]).skip_last(0).to_list() == [1, 2, 3]`.
  - Exception position: a source raising at element 5 with `skip_last(2)` raises on the 3rd `next()`.
- **Contracts** (auto): deferral, one-shot, FlpList not mutated, buffering `partial`.
- **Typing**: `assert_type(flp.lst(["a"]).skip_last(1), FlpIt[str])`.

## 5. Differential harness
`difftest/specs/skip_last.toml`: same count/source domains as L04; probes `result` and `pulled_at_each_yield` (sequence of pull counts per yielded element; must equal `count + i` on the generic path in both runtimes). Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_skip_last.py`, sizes 1e3 / 1e5, `k = 10` and `k = size // 2`:
- `native` (list): `data[:-k]`; `native` (iterator): a hand-written generator with the same lag-deque algorithm (there is no stdlib one-liner).
- `flpit-FlpIt` (list source and `iter()` source), `flpit-FlpList`.
- Target ratio ≤ 1.3× vs the matching native variant.

## 7. Docs
- Docstring: `.NET: Enumerable.SkipLast(count)`; lag of `count` elements; `count <= 0` → all; Execution: Deferred, Partial buffering, streams with lag.
- Doctest: `flp.it(range(6)).skip_last(2).to_list()` gives `[0, 1, 2, 3]`; `flp.lst([1, 2, 3]).skip_last(0).to_list()` gives `[1, 2, 3]`.
- Translation map: `xs[:-n]` (n > 0) / `.SkipLast(n)` → `.skip_last(n)`.

## 8. Expected outcomes
- `skip_last` on all four types; ~615 ported rows green on both types; the lag contract is pinned by tests and the difftest.

## 9. Verification
VERIFY-std with `<op>=skip_last`, plus:
```bash
uv run pytest -q tests/nettests/test_skip_last.py -rs
uv run python -c "import itertools; from flpit import flp; print(flp.it(itertools.count()).skip_last(3).take(5).to_list())"   # [0, 1, 2, 3, 4]
```

## 10. Definition of Done
DoD-std, plus the PR records the slice-vs-`islice` measurement for the Sequence path.

## 11. Risks / open questions
- The native iterator baseline has no idiomatic one-liner; the benchmark documents the hand-written generator it compares against.
