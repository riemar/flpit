---
id: M22
title: take_until / skip_until
status: todo
priority: 082
effort: S
depends_on: [F05, F06, F07, F08, F09, L02, L03]
upstream:
  dotnet: n/a (contrast: TakeWhileTests.cs / SkipWhileTests.cs are ported by L02/L03)
  morelinq: TakeUntil.cs, SkipUntil.cs @ morelinq master d217ab1 (reference only, D7; TakeUntilTest.cs 6 + SkipUntilTest.cs 7 [Test]/[TestCase] read for behaviour)
pr:
---

# M22: `take_until` / `skip_until`

## 1. Goal
"Read lines up to and including the terminator", "skip the header up to and including the separator line" are common stream-parsing tasks. `take_while`/`skip_while` (L02/L03) get the boundary element wrong for these: `take_while(not p)` drops the terminator, `skip_while(not p)` keeps the separator. MoreLINQ's `TakeUntil`/`SkipUntil` put the **matching element in the first part**: `take_until` yields it, `skip_until` skips it. Both are tiny streaming generators; they depend on L02/L03 only for shared docs and the contrast table.

## 2. Scope
**In:** `take_until(predicate)` and `skip_until(predicate)` on `_LinqOps` (FlpIt, FlpList, OrderedIt, Grouping).
**Out:** indexed variants (`take_until_indexed`): MoreLINQ has none, D4 lists only the .NET indexed overloads; add later only on demand.

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `TakeUntil(Func<T, bool>)` | `take_until(predicate)` |
| `SkipUntil(Func<T, bool>)` | `skip_until(predicate)` |

**Boundary contrast** (source `[1, 2, 3, 4, 5]`, `p = x == 3`; goes into both docstrings and the README):
| Call | Result | Matching element |
|---|---|---|
| `take_while(lambda x: not p(x))` | `[1, 2]` | consumed and dropped |
| `take_until(p)` | `[1, 2, 3]` | yielded, then stop |
| `skip_while(lambda x: not p(x))` | `[3, 4, 5]` | yielded |
| `skip_until(p)` | `[4, 5]` | skipped |

## 3. Detailed design
### 3.1 Signatures
```python
def take_until(self, predicate: Callable[[TItem], bool]) -> FlpIt[TItem]: ...
def skip_until(self, predicate: Callable[[TItem], bool]) -> FlpIt[TItem]: ...
```
### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit (registry): n/a for intermediates, but `take_until` never pulls past the match.
- `take_until`: each element is yielded **before** the predicate sees it; the predicate is evaluated only when the consumer asks for the next element. So `take_until(p).first()` never calls `p`, and `take_until(p).take(k)` calls it `k - 1` times (MoreLINQ "as lazy as possible", observable in the trace). After a true predicate the source is not pulled again. Never true → the whole source.
- `skip_until`: pulls and tests elements until the predicate is true; that element is skipped; the rest is yielded **without** further predicate calls (an element that would make the predicate raise is fine after the match). Never true → empty, predicate called n times.
- Identity for docs and tests: `skip_until(p)` equals `skip_while(lambda x: not p(x)).skip(1)` element-wise and in predicate calls.
- Validation (eager): `predicate is None` → `ArgumentNoneError("predicate")`.
- Empty source → empty for both, predicate never called. None elements are ordinary values passed to the predicate.
- Exceptions from source or predicate propagate at enumeration, at the same position as MoreLINQ (`take_until`: after yielding the element the predicate raised on).
- Re-enumeration re-runs from the start; one-shot stays one-shot (a partially consumed one-shot source continues where `take_until` stopped, as in .NET with a shared enumerator; documented, tested).

### 3.3 Implementation sketch
```python
def take_until(self, predicate):
    _require_callable(predicate, "predicate")
    src = self._source()
    def _generator():
        for item in src:
            yield item
            if predicate(item):
                return
    return FlpIt(_FactoryIterable(_generator))

def skip_until(self, predicate):
    _require_callable(predicate, "predicate")
    src = self._source()
    def _generator():
        it = iter(src)
        for item in it:
            if predicate(item):
                yield from it                 # C-level tail, no predicate calls
                return
    return FlpIt(_FactoryIterable(_generator))
```
- O(n) time, O(1) memory. `itertools.dropwhile` would need a negating lambda plus a `next()` to drop the match; the loop is simpler and as fast.
- **FlpList fast path:** none (no index-based shortcut; the predicate must run element by element).

### 3.4 Registry entries
```toml
[operators.take_until]
category = "partitioning"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
origin = "morelinq"
dotnet = ""
morelinq = "MoreEnumerable.TakeUntil"
python_equivalent = "for x in xs: yield x; if p(x): break"
contract_args = "(lambda x: x > 1,)"
since = "0.4.0"   # adjust to the release that ships it
card = "M22"

[operators.skip_until]   # same fields; morelinq = "MoreEnumerable.SkipUntil",
                         # python_equivalent = "it = iter(xs); next((x for x in it if p(x)), None); yield from it"
```

## 4. Tests
- **Ported:** none (D7, 0 % by design); MoreLINQ's 13 cases are a checklist (never true, always true, match half-way, lazy source, lazy predicate) and each gets an own test. Skip categories: n/a.
- **Own unit tests** (`tests/unit/morelinq/test_take_until_skip_until.py`, both `flp_type`s):
  - The boundary table above, asserted literally, including the `take_while`/`skip_while` rows (guards against confusing the operators).
  - Match at first, middle, last position; never; always; empty source.
  - Predicate-call log: `take_until(p).first()` → 0 calls; `take_until(p).to_list()` with a match at index i → i + 1 calls; `skip_until` → calls stop at the match.
  - Pull count: `take_until` over `itertools.count()` with a match at 5 pulls exactly 6 and terminates.
  - Predicate raising on an element after the match: `skip_until` still yields it; `take_until` never sees it.
  - `None` → `ArgumentNoneError` at call time; None elements are passed to the predicate.
  - Shared one-shot source: `it = iter(range(6)); flp.it(it).take_until(p).to_list()` then `list(it)` continues after the match.
- **Contracts** (auto): deferral, lazy predicate, one-shot, FlpList not mutated.
- **Typing** (`tests/typing/test_types_take_until.py`): both return `FlpIt[int]` on `FlpList[int]`/`OrderedIt[int]`.

## 5. Differential harness
`difftest/specs/take_until.toml`, `difftest/specs/skip_until.toml`; oracle files `TakeUntil.cs`, `SkipUntil.cs` calling `MoreEnumerable.TakeUntil/SkipUntil` statically.
- Predicates (F09 catalogue): `eq(k)`, `gt(k)`, `is_even`, `always_true`, `always_false`, `throws_on(k)`; items: empty, singleton, `range(0, 20)`, duplicates, ints with nulls; sources: `list`, `one_shot`, `counting`, `throwing_at(i)`.
- Terminals: `to_list`, `first`, `take(k)` then `to_list`, `count`.
- Probes: values and `trace` (the yield-before-predicate order of `take_until` is the key assertion).
- Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_take_until.py` (both ops), predicate never true (worst case, full scan), `p = lambda x: x < 0`:
- `native` take_until: `out = []` + `for x in data: out.append(x); if p(x): break`; skip_until: `it = iter(data)` + `for x in it: if p(x): break` + `list(it)` (with a match at n/2 for skip_until so the tail is non-empty).
- `flpit-FlpIt` / `flpit-FlpList`: `.take_until(p).to_list()`, `.skip_until(p).to_list()`.
- Target ratio ≤ 1.5× (streaming); the prototype measured ~1.05× for `take_until`.

## 7. Docs
- Docstrings: summary; `MoreLINQ: MoreEnumerable.TakeUntil(predicate)` / `SkipUntil`; the boundary table (short form); `Execution: Deferred, streaming; predicate evaluated lazily`; doctests:
  ```python
  >>> flp.it([1, 2, 3, 4, 5]).take_until(lambda x: x == 3).to_list()
  [1, 2, 3]
  >>> flp.it([1, 2, 3, 4, 5]).skip_until(lambda x: x == 3).to_list()
  [4, 5]
  ```
- Translation map: MoreLINQ `.TakeUntil(p)` / Python loop with `yield` + `break` → `.take_until(p)`; `.SkipUntil(p)` / `dropwhile(not p)` + `next()` → `.skip_until(p)`.
- No semantic deviation.

## 8. Expected outcomes
- Both operators on all four types with the boundary semantics documented next to `take_while`/`skip_while`.
- difftest specs 0 MISMATCH including predicate-call timing.

## 9. Verification
VERIFY-std with `<op>=take_until` and `<op>=skip_until`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_take_until_skip_until.py
uv run python -c "from flpit import flp; print(flp.it([1,2,3,4,5]).take_until(lambda x: x == 3).to_list())"   # [1, 2, 3]
uv run python -c "from flpit import flp; print(flp.it([1,2,3,4,5]).skip_until(lambda x: x == 3).to_list())"   # [4, 5]
```

## 10. Definition of Done
DoD-std, plus: boundary contrast table present in both docstrings (short form) and in the README near `take_while`/`skip_while`.

## 11. Risks / open questions
- If L02/L03 land later than this card, drop them from `depends_on` and add the contrast rows when they land (they are only needed for docs and the contrast test).
