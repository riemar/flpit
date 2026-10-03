---
id: L03
title: skip_while (+ indexed)
status: todo
priority: 021
effort: S
depends_on: [F05, F06, F07, F08, F09, L02]
upstream:
  dotnet: SkipWhileTests.cs @ dotnet/runtime main 6f1d9331 (18 [Fact]/[Theory], plus 1 stress-only [ConditionalFact])
  morelinq: n/a
pr:
---

# L03: `skip_while` (+ `skip_while_indexed`)

## 1. Goal
`SkipWhile` drops a leading run (headers, leading blanks, warm-up samples) and then streams the rest. It completes the partitioning family with `skip`/`take`/`take_while`, maps to `itertools.dropwhile`, and reuses the indexed-variant pattern landed in L02.

## 2. Scope
**In:** `skip_while(predicate)` and `skip_while_indexed(predicate)` on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`).
**Out:** MoreLINQ `SkipUntil` (M22); any FlpList fast path (the predicate must run on the leading run, and the tail must be streamed anyway).

## 3. Detailed design
### 3.1 Signatures
```python
def skip_while(self, predicate: Callable[[TItem], object]) -> FlpIt[TItem]: ...
def skip_while_indexed(self, predicate: Callable[[TItem, int], object]) -> FlpIt[TItem]: ...
```
| .NET | Python |
|---|---|
| `SkipWhile(Func<TSource,bool>)` | `skip_while(predicate)` |
| `SkipWhile(Func<TSource,int,bool>)` | `skip_while_indexed(predicate)` (D4, callback `(item, index)`) |

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: n/a (yields the whole tail). The predicate is called for each leading element until the first falsy result, and **never again** afterwards (the tail is yielded without calling it). This matches .NET and `dropwhile`.
- The first element with a falsy predicate is yielded (it is not lost, unlike `take_while`).
- Validation (eager): `predicate is None` raises `ArgumentNoneError("predicate")`.
- Truthiness and falsy-callable rules as in L02.
- Indexed: index starts at 0 and counts only the elements tested (the predicate is not called on the tail, so no index is observed there). No overflow (Python int); deviation shared with L02.
- Re-enumeration re-iterates the source and restarts the skip phase. One-shot stays one-shot.
- Source/predicate exceptions propagate at enumeration time. `SkipWhilePassesPredicateExceptionWhenEnumerated` (`1 / i` with `i = 0`) maps to `ZeroDivisionError` on the first `next()`.

### 3.3 Implementation sketch
```python
def skip_while(self, predicate):
    _require_not_none(predicate, "predicate")
    return FlpIt(_FactoryIterable(lambda: dropwhile(predicate, self)))

def skip_while_indexed(self, predicate):
    _require_not_none(predicate, "predicate")
    def _generator():
        it = iter(self)
        for index, item in enumerate(it):
            if not predicate(item, index):
                yield item
                break
        yield from it          # tail: no predicate calls, no index bookkeeping
    return FlpIt(_FactoryIterable(_generator))
```
- O(n) time, O(1) memory. `dropwhile` is C-level; after the leading run it degenerates to a plain pass-through.
- The indexed form breaks out of `enumerate` and continues on the raw iterator so the tail has no per-element overhead.
- **FlpList fast path:** rejected (same reason as L02). Decision recorded.

### 3.4 Registry entry
```toml
[operators.skip_while]
category = "partitioning"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.SkipWhile"
python_equivalent = "itertools.dropwhile(pred, xs)"
since = "0.3.0"

[operators.skip_while_indexed]
category = "partitioning"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
variant_of = "skip_while"
dotnet = "Enumerable.SkipWhile (Func<TSource,int,bool>)"
python_equivalent = "(x for i, x in dropwhile(lambda p: pred(p[1], p[0]), enumerate(xs)))"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_skip_while.py` from `SkipWhileTests.cs` (18 counted + 1 stress). Expected skips:
  - `INTERNAL_OPTIMIZATION`: `ForcedToEnumeratorDoesntEnumerate`, `ForcedToEnumeratorDoesntEnumerateIndexed`.
  - `OTHER` (no int overflow, stress-only): `IndexSkipWhileOverflowBeyondIntMaxValueElements`.
  - `SkipErrorWhenSourceErrors` actually exercises `Skip` (upstream oddity); port it as written with `skip(4)` (requires L01) and keep the upstream name.
  - `SkipWhileThrowsOnNull`: source half via `flp_type(None)` → `SourceNoneError`; predicate half → `ArgumentNoneError`.
  - Target: 16 of 18 counted cases ported (≈ 89 %).
- **Own unit tests** (`tests/unit/test_skip_while.py`):
  - Predicate call count equals length of the leading run + 1, and is unchanged after the tail is fully consumed (e.g. `[2, 4, 5, 6, 8]`, `is_even` → 3 calls, result `[5, 6, 8]`).
  - The tail is yielded lazily: `skip_while(...).first()` on an infinite source after a finite run terminates.
  - All-true predicate → empty, all-false → whole source; empty source → no predicate calls.
  - `None` elements; falsy callable; eager `ArgumentNoneError` on both variants.
  - Indexed: indices observed are `0..k` only; restart per enumeration.
- **Contracts** (auto): deferral, one-shot, FlpList not mutated, indexed-callback contract.
- **Typing**: `assert_type(flp.it(["a"]).skip_while(str.isspace), FlpIt[str])`; indexed variant `FlpIt[T]`.

## 5. Differential harness
`difftest/specs/skip_while.toml`, `skip_while_indexed.toml`: same domains/predicate catalogue as L02; probes `result`, `predicate_calls` (must equal leading-run length + 1, or n when the predicate is always true), `elements_pulled`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_skip_while.py`, sizes 1e3 and 1e5, data `list(range(size))`, predicate `x < size // 2`:
- `native`: `list(itertools.dropwhile(lambda x: x < half, data))`
- `flpit-FlpIt` / `flpit-FlpList`: `flp.it(data).skip_while(lambda x: x < half).to_list()` / `flp.lst(data)...`
- indexed group: native `list(map(itemgetter(1), dropwhile(lambda p: p[0] < half, enumerate(data))))`.
- Target ratio ≤ 1.5× (expected better for the indexed form thanks to the raw-tail pass-through).

## 7. Docs
- Docstring: `.NET: Enumerable.SkipWhile(predicate)`; "predicate is not called after the first falsy result"; Execution: Deferred, Streaming.
- Doctests: `flp.it([1, 2, 5, 1]).skip_while(lambda x: x < 3).to_list()` gives `[5, 1]`; `flp.it("abcd").skip_while_indexed(lambda c, i: i < 2).to_list()` gives `['c', 'd']`.
- Translation map: `itertools.dropwhile(p, xs)` / `.SkipWhile(p)` → `.skip_while(p)`; indexed → `.skip_while_indexed(lambda x, i: ...)`.

## 8. Expected outcomes
- `skip_while` and `skip_while_indexed` on all four types; 16 ported tests green, 3 categorised skips.
- Predicate-call-count behaviour pinned by contract and difftest.

## 9. Verification
VERIFY-std with `<op>=skip_while` (and `skip_while_indexed`), plus:
```bash
uv run pytest -q tests/nettests/test_skip_while.py -rs
uv run python -c "from flpit import flp; print(flp.it([1, 2, 5, 1]).skip_while(lambda x: x < 3).to_list())"   # [5, 1]
```

## 10. Definition of Done
DoD-std, plus the own test pinning "no predicate call on the tail".

## 11. Risks / open questions
- `SkipErrorWhenSourceErrors` depends on L01 (`skip`); if L01 slips, mark it `pytest.skip("OTHER: needs skip (L01)")` temporarily and remove the skip when L01 merges.
