---
id: M13
title: interleave
status: todo
priority: 074
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: Interleave.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7; InterleaveTest.cs has 16 [Test]/[TestCase])
pr:
---

# M13: `interleave`

## 1. Goal
`interleave` merges several sequences round-robin (`a1, b1, c1, a2, b2, ...`), skipping sequences as they run out: fair scheduling of work queues, merging feeds, alternating layouts. Python's answer is the `roundrobin` recipe from the `itertools` docs, which most users do not know or copy wrongly; this makes it one fluent call.

## 2. Scope
**In:** `interleave(*others)` on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`).
**Out:** other imbalance strategies (MoreLINQ removed `ImbalancedInterleaveStrategy`; "stop at shortest" is `zip` + `select_many`, "pad" is `zip_longest`, M14).

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `Interleave(this IEnumerable<T> sequence, params IEnumerable<T>[] otherSequences)` | `interleave(*others)` |

## 3. Detailed design
### 3.1 Signatures
```python
def interleave(self, *others: Iterable[TItem]) -> FlpIt[TItem]: ...
```
Same element type for all sequences, as in MoreLINQ; mixing types is done with `as_type`/a union-typed source (pyrefly infers the join where it can).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming (one iterator per sequence, no element buffer). Short-circuit: n/a.
- Order: first element of `self`, of `others[0]`, ..., then second elements, and so on. When a sequence is exhausted it is dropped and the rotation continues with the **next** sequence after it (no restart from the first).
- **Laziness of each sequence:** `iter(seq_k)` is called only when sequence k is first needed, i.e. after the first element of sequence k-1 has been yielded (MoreLINQ "do not call GetEnumerator eagerly"); `next` is called only when the consumer asks for the next element.
- `interleave()` with no others yields `self` unchanged. All empty → empty.
- Validation (eager): any `None` in `others` → `ArgumentNoneError("others")` (MoreLINQ throws for a `null` array; a `None` element would fail later with an NRE, flpit reports it eagerly). Non-iterables fail at enumeration with Python's `TypeError` (when `iter()` is reached).
- Exceptions raised by `iter()` or `next()` of any sequence propagate at that point; earlier elements were already yielded.
- Re-enumeration: re-iterates `self` and every other (one-shot iterators stay one-shot).

### 3.3 Implementation sketch
The `itertools` `roundrobin` recipe, which is both the fastest stdlib formulation and exactly the MoreLINQ order:
```python
def interleave(self, *others):
    for o in others:
        _require_not_none(o, "others")
    src = self._source()
    def _generator():
        sequences = (src, *others)
        iterators = map(iter, sequences)                    # lazy iter() per sequence
        for active in range(len(sequences), 0, -1):
            iterators = cycle(islice(iterators, active))
            yield from map(next, iterators)                 # StopIteration of one iterator ends this round
    return FlpIt(_FactoryIterable(_generator))
```
- When `next` on iterator k raises `StopIteration`, `map` ends; the outer loop rebuilds the cycle from the remaining `active - 1` iterators, starting at k+1: identical to MoreLINQ's linked-list walk (`node = nextNode ?? first`).
- All per-element work is C-level (`cycle`, `islice`, `map(next, ...)`). O(total) time, O(k) memory for k sequences.
- **Disposal:** Python iterators have no `Dispose`; generators abandoned mid-way are closed by GC. MoreLINQ's disposal tests do not apply (§4).
- **FlpList fast path**: none (the recipe is already C-level).

### 3.4 Registry entry
```toml
[operators.interleave]
category = "concatenation"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
morelinq = "MoreEnumerable.Interleave"
python_equivalent = "roundrobin(*iterables) (itertools recipe)"
since = "0.4.0"   # Phase 3 target; adjust when the release is cut
```

## 4. Tests
- **Ported:** none (D7). `InterleaveTest.cs` (16 cases) as checklist:
  - covered by own tests: laziness, GetEnumerator not called eagerly, MoveNext not called eagerly, two balanced, two empty, two imbalanced (skip), many empty, many imbalanced.
  - `OTHER` (no `IDisposable` in Python iterators): "disposes on error at GetEnumerator / at MoveNext / on error / on partial enumeration (4 cases) / all iterators" (8 cases). The own tests instead assert that generator sources get `close()`d after full enumeration and that an exception from one source propagates unchanged.
  - Target: 100 % of applicable behaviours (8 of 16 cases are disposal-only).
- **Own unit tests** (`tests/unit/morelinq/test_interleave.py`, both `flp_type`s):
  - `[1, 2, 3].interleave("ab", [], [10, 20, 30, 40])` → `[1, 'a', 10, 2, 'b', 20, 3, 30, 40]`.
  - Rotation continues after the exhausted sequence (not from the first): three sequences where the middle one ends first.
  - No others → `self`; all empty → empty; only `self` empty.
  - Trace test with instrumented iterables: `iter()` of sequence k happens after the first yield of k-1; no `next` beyond what was consumed (`take(3)`).
  - `None` in `others` raises at call time; non-iterable raises `TypeError` at enumeration.
  - Infinite source interleaved with finite ones + `take(n)`.
  - One-shot vs list re-enumeration.
- **Contracts:** auto via registry.
- **Typing:** `assert_type(flp.it([1]).interleave([2], [3]), FlpIt[int])`.

## 5. Differential harness
`difftest/specs/interleave.toml`, oracle calls `MoreEnumerable.Interleave(source, others)` (pinned `morelinq` NuGet). Domains: 0 to 4 others, lengths from {0, 1, 3, 7}, ints/strings; a source that throws at position k. Probes: values, trace (`get_enumerator`/`move_next` order per sequence), exception position. Expected: MATCH; `dispose` trace events are filtered out (`UNCOMPARABLE: no IDisposable`).

## 6. Benchmarks
`tests/benchmarks/test_bench_interleave.py`, sizes 1e3 / 1e5 total elements split over 3 sequences of unequal length:
- `native`: `list(roundrobin(a, b, c))` with the `itertools` recipe copied verbatim into the benchmark module.
- `flpit-FlpIt` / `flpit-FlpList`: `flp.it(a).interleave(b, c).to_list()`.
- Target ratio ≤ 1.5× (expected ~1.0× plus `FlpList` construction).

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.Interleave(otherSequences)`; Args; Raises; `Execution:` deferred, streaming, lazy `iter()` per sequence, skips exhausted sequences.
- Doctest:
  ```python
  >>> flp.it([1, 2, 3]).interleave("ab", [], [10, 20, 30, 40]).to_list()
  [1, 'a', 10, 2, 'b', 20, 3, 30, 40]
  ```
- Translation map: `.Interleave(b, c)` / `roundrobin(a, b, c)` (itertools recipe) / `more_itertools.interleave_longest` → `.interleave(b, c)`.
- Deviations: none in values; disposal semantics n/a (documented once in README for all MoreLINQ ops).

## 8. Expected outcomes
- `interleave` on all four types; ~10 own tests; difftest 0 MISMATCH; benchmark ≈ native.

## 9. Verification
VERIFY-std with `<op>=interleave`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_interleave.py
uv run python -c "from flpit import flp; print(flp.it([1,2,3]).interleave('ab').to_list())"   # [1, 'a', 2, 'b', 3]
```

## 10. Definition of Done
DoD-std, plus a README sentence (shared by all M-cards) that MoreLINQ disposal guarantees map to Python generator `close()`/GC and are not tested as such.

## 11. Risks / open questions
- `map(next, ...)` relies on a `StopIteration` from a source iterator ending `map`; a source that leaks `StopIteration` from a nested call would be read as exhaustion. Same behaviour as the stdlib recipe; documented, no workaround.
