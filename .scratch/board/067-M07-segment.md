---
id: M07
title: segment
status: todo
priority: 067
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: Segment.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7; SegmentTest.cs has 8 [Test]/[TestCase])
pr:
---

# M07: `segment` (+ `segment_indexed`, `segment_with_previous`)

## 1. Goal
`segment` cuts a sequence into consecutive runs wherever a predicate says "a new segment starts here": sessions split by time gaps, log blocks starting at header lines, runs of consecutive integers. `chunk` only cuts by size and `group_by` loses adjacency, so this is a frequent hand-written loop that has no stdlib one-liner.

## 2. Scope
**In:** three methods on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`), one per MoreLINQ predicate shape. Following D4, the predicate arity is expressed by the method name, not by runtime introspection.
**Out:** a result-selector overload (compose with `.select`); inclusive/exclusive separators (that is `split`, M08).

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `Segment(Func<T, bool>)` | `segment(predicate)`: `predicate(current)` |
| `Segment(Func<T, int, bool>)` | `segment_indexed(predicate)`: `predicate(current, index)` (D4 suffix) |
| `Segment(Func<T, T, int, bool>)` | `segment_with_previous(predicate)`: `predicate(current, previous, index)` |

## 3. Detailed design
### 3.1 Signatures
```python
def segment(self, predicate: Callable[[TItem], bool]) -> FlpIt[FlpList[TItem]]: ...
def segment_indexed(self, predicate: Callable[[TItem, int], bool]) -> FlpIt[FlpList[TItem]]: ...
def segment_with_previous(self, predicate: Callable[[TItem, TItem, int], bool]) -> FlpIt[FlpList[TItem]]: ...
```
Segments are `FlpList` (same choice as `chunk`), so they are re-iterable, indexable and support LINQ operators.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (the current segment only). Short-circuit: n/a; a segment is yielded as soon as the element that starts the next one is seen.
- **The first element always belongs to the first segment and is never passed to the predicate.** The predicate is evaluated for elements at index 1..n-1; `index` is the element's position in the source (so the first call gets `index == 1`), `previous` is the element at `index - 1`.
- A truthy predicate result starts a new segment with the current element; segments are therefore never empty.
- Empty source → no segments (not one empty segment). Single element → one segment, predicate never called.
- Validation (eager): `predicate is None` → `ArgumentNoneError("predicate")`.
- `None` elements are ordinary values (`previous` can be `None`).
- Each yielded `FlpList` is a fresh object; mutating it does not affect later segments or the source.
- Re-enumeration re-runs the source and the predicate. Exceptions from source or predicate propagate at enumeration time; the partially built segment is discarded.

### 3.3 Implementation sketch
```python
def segment_with_previous(self, predicate):
    _require_callable(predicate, "predicate")
    src = self._source()
    def _generator():
        it = iter(src)
        for previous in it:              # at most one iteration: the first element
            current_segment = [previous]
            for index, current in enumerate(it, 1):
                if predicate(current, previous, index):
                    yield FlpList(current_segment)
                    current_segment = [current]
                else:
                    current_segment.append(current)
                previous = current
            yield FlpList(current_segment)
    return FlpIt(_FactoryIterable(_generator))
```
- `segment` and `segment_indexed` get their own tight loops (no wrapper lambda per element): the 1-arg form drops `enumerate` and `previous`. O(n) time, O(longest segment) memory.
- `FlpList(list)` wraps without a second copy once F05's `FlpList._wrap` (no-copy constructor) exists; otherwise one copy per segment (still O(n) overall).
- **FlpList fast path**: none; the loop is already linear and cannot skip predicate calls.
- itertools: `groupby` with a stateful key could express it but is slower and less clear; not used.

### 3.4 Registry entries
```toml
[operators.segment]
category = "grouping"
kind = "intermediate"
buffering = "partial"
short_circuit = false
morelinq = "MoreEnumerable.Segment"
python_equivalent = "manual loop accumulating runs"
since = "0.4.0"   # Phase 3 target; adjust when the release is cut
```
`[operators.segment_indexed]` and `[operators.segment_with_previous]` repeat these fields plus `variant_of = "segment"` (same pattern as L02), so contract tests cover all three.

## 4. Tests
- **Ported:** none (D7). `SegmentTest.cs` (8 cases) as checklist, all applicable and covered by own tests: laziness, identity segment (predicate always false → one segment), empty sequence, every element a segment, first segment never empty for all three shapes, segmentation starts with the second item, segment by index, segment by previous. Target: 100 %.
- **Own unit tests** (`tests/unit/morelinq/test_segment.py`, both `flp_type`s):
  - Consecutive runs: `[1, 2, 3, 5, 6, 9].segment_with_previous(lambda c, p, i: c != p + 1)` → `[[1, 2, 3], [5, 6], [9]]`.
  - Always-true predicate → n singleton segments; always-false → one segment equal to the source.
  - Predicate call log: called n-1 times, first call `(xs[1], xs[0], 1)`; `segment_indexed` sees indexes `1..n-1`.
  - Empty and single-element sources; `None` elements and `None` as `previous`.
  - Each segment is a distinct `FlpList`; mutating one leaves the next untouched.
  - `segment(None)` raises eagerly; predicate exception mid-segment propagates and nothing partial is yielded.
  - Streaming: the first segment is yielded after pulling exactly the element that starts the second one (counting source).
- **Contracts:** auto for all three names (deferral, one-shot, no FlpList mutation, callbacks lazy).
- **Typing** (`tests/typing/test_types_segment.py`): `assert_type(flp.it([1]).segment(lambda x: x > 0), FlpIt[FlpList[int]])` for each method; a 2-arg lambda passed to `segment` is a pyrefly error (negative check via `# pyrefly: expect-error`).

## 5. Differential harness
`difftest/specs/segment.toml` (three ops), oracle calls the three `MoreEnumerable.Segment` overloads (pinned `morelinq` NuGet). Domains: empty, singleton, ascending ints with gaps, repeated values, strings with nulls; predicates from a fixed catalogue (`x % 3 == 0`, `i % 2 == 0`, `c != p + 1`, always true/false, throws at index k). Probes: segment values, predicate call log `(args...)`, `elements_pulled` after `first()`, exception position. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_segment.py`, sizes 1e3 / 1e5, data = ints with a gap every ~10 elements:
- `native`: the idiomatic loop (`out, cur = [], [xs[0]]`; for each pair append or start a new list), materialised to a list of lists.
- `flpit-FlpIt` / `flpit-FlpList`: `segment_with_previous(lambda c, p, i: c != p + 1).to_list()`, plus a `segment(lambda x: x % 10 == 0)` group.
- Target ratio ≤ 1.3× (partial buffering; cost dominated by the predicate call and `FlpList` construction).

## 7. Docs
- Docstrings (one per method): summary; `MoreLINQ: MoreEnumerable.Segment(...)` with the matching overload; Args (callback shape, index base); Returns `FlpIt[FlpList[T]]`; Raises `ArgumentNoneError`; `Execution:` deferred, buffers one segment; note that the first element is never tested.
- Doctest:
  ```python
  >>> flp.it([1, 2, 3, 5, 6, 9]).segment_with_previous(lambda cur, prev, i: cur != prev + 1).to_list()
  [[1, 2, 3], [5, 6], [9]]
  >>> flp.it(range(1, 6)).segment_indexed(lambda x, i: i % 2 == 0).to_list()
  [[1, 2], [3, 4], [5]]
  ```
- Translation map: `.Segment((c, p, i) => ...)` → `.segment_with_previous(...)`; `.Segment(x => ...)` → `.segment(...)`; Python idiom: manual run-accumulation loop.
- Deviations: none in values; method-per-arity naming is the documented D4 rule.

## 8. Expected outcomes
- Three methods on all four types, typed; ~15 own tests; difftest 0 MISMATCH; benchmark recorded.
- The `*_with_previous` naming becomes the precedent for any later "(current, previous)" callbacks.

## 9. Verification
VERIFY-std with `<op>=segment`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_segment.py
uv run python -m difftest run --op segment_indexed && uv run python -m difftest run --op segment_with_previous
uv run python -c "from flpit import flp; print(flp.it([1,2,3,5,6,9]).segment_with_previous(lambda c,p,i: c != p+1).to_list())"   # [[1, 2, 3], [5, 6], [9]]
```

## 10. Definition of Done
DoD-std for all three method names (registry, docstrings, typing, difftest spec entries).

## 11. Risks / open questions
- Naming: `segment_with_previous` versus a single `segment(predicate, *, with_previous=True)`. A flag changes the callback arity, which typing cannot express cleanly; separate names are proposed (consistent with D4).
- Should `segment_with_previous` drop the `index` argument (`(current, previous)` only)? Proposal: keep `(current, previous, index)` to stay 1:1 with MoreLINQ; callers ignore `index` with `_`.
