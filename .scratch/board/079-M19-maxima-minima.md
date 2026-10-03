---
id: M19
title: maxima / minima
status: todo
priority: 079
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a (closest .NET op is Enumerable.MaxBy/MinBy, which return a single element; see L27)
  morelinq: Maxima.cs, Minima.cs @ morelinq master d217ab1 (reference only, D7; MaximaTest.cs 47 + MinimaTest.cs 45 [Test]/[TestCase] read for behaviour)
pr:
---

# M19: `maxima` / `minima`

## 1. Goal
`max_by`/`min_by` return exactly one element, so "all employees with the top salary" needs two passes (`m = max(map(key, xs)); [x for x in xs if key(x) == m]`) or a hand-written loop. MoreLINQ `Maxima`/`Minima` return **every** element whose key is extreme, in source order, in one pass. It is the most requested MoreLINQ aggregate-style operator and reuses the None-aware key ordering that `order_by` already has.

## 2. Scope
**In:** `maxima(key_selector)` and `minima(key_selector)` on `_LinqOps` (FlpIt, FlpList, OrderedIt, Grouping). No FlpList override.
**Out:**
- The `IComparer<TKey>` overloads (D3: the key selector carries the use-case; a reversing comparer is `minima`).
- The `IExtremaEnumerable<T>` return type and its members `Take(n)`, `TakeLast(n)` and the `First/FirstOrDefault/Last/LastOrDefault/Single/SingleOrDefault` extension overloads. They only bound memory (keep the first/last `n` extremes instead of all); the **values** they return are identical to `maxima(k).take(n)`, `.take_last(n)` (L04), `.first()` and so on over the plain `FlpIt`. Dropped extras are listed in README deviations; a bounded-memory `_ExtremaIt` subclass can be a follow-up if a benchmark ever needs it.
- A keyless `maxima()`: not in MoreLINQ; `maxima(lambda x: x)` covers it.

## 3. Detailed design
### 3.1 Signatures
```python
def maxima(self, key_selector: Callable[[TItem], Any]) -> FlpIt[TItem]: ...
def minima(self, key_selector: Callable[[TItem], Any]) -> FlpIt[TItem]: ...
```
`Any` for the key mirrors `order_by`/`min_by` (no `SupportsRichComparison` bound until a typing refactor does it for all ordering ops).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: full (the whole source is consumed before the first element is yielded; memory O(m) where m is the number of extremes). Short-circuit: none.
- Result: all elements whose key equals the extreme key, **in source order**, duplicates kept (`[2, 2, 1].maxima(id)` gives `[2, 2]`).
- `key_selector` is called exactly once per element, in source order (MoreLINQ does the same); it is never called on an empty source.
- Comparison: maxima restarts the bucket when `key > best`, appends when `key == best`; minima uses `<`. This is the same operator set `builtins.max/min` use, so any type that works with `max_by` works here.
- **None keys** compare lower than every other key (MoreLINQ uses `Comparer<TKey>.Default`, where `null` is smallest). Implemented by reusing the existing `_none_aware_key` / `_NONE_ORDER_KEY` from `order_by`, so `minima` returns the elements with a `None` key if any exist. Documented deviation from Python's `max(key=...)`, which would raise `TypeError`.
- None **elements** are ordinary elements (only keys matter).
- Empty source: empty result, no error (unlike `max_by`).
- Validation (eager): `key_selector is None` raises `ArgumentNoneError("key_selector")`.
- Errors during enumeration: exceptions from `key_selector` or from comparing incomparable keys (`TypeError`, e.g. `1` vs `"a"`) propagate when the query is enumerated; nothing is yielded before (full buffering).
- Re-enumeration: each enumeration re-runs the scan (re-iterable source gives identical results; one-shot stays one-shot).
- On `OrderedIt` the ordering is applied first, so ties come out in sorted order; result is a plain `FlpIt`.

### 3.3 Implementation sketch
```python
def maxima(self, key_selector):
    _require_callable(key_selector, "key_selector")             # F05 helper
    return FlpIt(_FactoryIterable(lambda: _extrema(self, key_selector, operator.gt)))

def _extrema(source, key_selector, better):                     # module-level, shared by minima (operator.lt)
    it = iter(source)
    for first in it:
        break
    else:
        return
    best = _none_aware_key(key_selector, first)
    found = [first]
    for item in it:
        key = _none_aware_key(key_selector, item)
        if better(key, best):
            best, found = key, [item]
        elif key == best:
            found.append(item)
    yield from found
```
- O(n) time (1 to 2 comparisons per element), O(m) memory. A single Python-level pass; the native two-pass idiom calls the key twice per element, so flpit is expected to be faster (prototype: 5.7 ms vs 9.0 ms at n = 1e5).
- **FlpList fast path:** none (no O(1) shortcut exists; the generic loop already runs over the list iterator).

### 3.4 Registry entry
```toml
[operators.maxima]
category = "aggregation"
kind = "intermediate"
buffering = "full"
short_circuit = false
morelinq = "MoreEnumerable.Maxima"
python_equivalent = "m = max(map(key, xs)); [x for x in xs if key(x) == m]"
since = "0.4.0"   # adjust to the release that ships it

[operators.minima]
category = "aggregation"
kind = "intermediate"
buffering = "full"
short_circuit = false
morelinq = "MoreEnumerable.Minima"
python_equivalent = "m = min(map(key, xs)); [x for x in xs if key(x) == m]"
since = "0.4.0"
```

## 4. Tests
- **Ported:** none by decision D7 (0 % by design). MoreLINQ tests were read only to list behaviours; skip categories are n/a.
- **Own unit tests** (`tests/unit/morelinq/test_maxima_minima.py`, parametrized over `flp_type`):
  - Single extreme, several tied extremes (source order kept), all elements tied, duplicates of the same value kept.
  - Empty source gives empty; singleton gives the singleton.
  - `key_selector` call log equals the source order, exactly n calls; zero calls on empty.
  - None keys: `minima` returns the None-keyed elements, `maxima` ignores them unless all keys are None.
  - None elements with a non-None key are returned normally.
  - Incomparable keys raise `TypeError` at enumeration, not at call time.
  - `maxima(None)` raises `ArgumentNoneError` eagerly.
  - Composition: `.maxima(k).first()`, `.maxima(k).take(1)`, `.maxima(k).last()` equal the corresponding `IExtremaEnumerable` member results (written as own expectations).
  - On `order_by(...)` input, ties appear in sorted order.
  - One-shot generator: second enumeration is empty; list source: identical results.
- **Contracts** (auto): deferral (`NoIterList`), lazy callbacks, FlpList not mutated, buffering = full (first yield only after the source is exhausted).
- **Typing** (`tests/typing/test_types_maxima.py`): `assert_type(flp.it(["a"]).maxima(len), FlpIt[str])`, same for `minima` and on `FlpList`/`OrderedIt` receivers.

## 5. Differential harness
`difftest/specs/maxima.toml`, `difftest/specs/minima.toml`; oracle `difftest/oracle/Operators/Maxima.cs` calls `MoreEnumerable.Maxima(source, selector)` statically (avoids extension-method ambiguity with .NET 10).
- Sources: empty, singleton, all equal, ints with ties at start/middle/end, strings, records `{id, score}` with duplicate scores, nullable ints (None keys).
- Selectors from the harness catalogue: `identity`, `mod(k)`, `field(score)`, `len`, `throws_on(v)`.
- Probes: result sequence, `selector_calls` (= n), `source_enumerations` (= 1 per enumeration), re-enumeration twice.
- Expected: all MATCH. Mixed-type keys are UNCOMPARABLE (.NET throws `ArgumentException`, Python `TypeError`; excluded from the domain with that reason).

## 6. Benchmarks
`tests/benchmarks/test_bench_maxima.py`, `key = lambda x: x % 97`, data = random ints:
- `native`: `m = max(map(key, data)); [x for x in data if key(x) == m]`
- `flpit-FlpIt`: `flp.it(data).maxima(key).to_list()`; `flpit-FlpList`: `flp.lst(data).maxima(key).to_list()`
- Target ratio ≤ 1.3× (buffering default); the prototype is below 1.0×.

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.Maxima(selector)`; Args/Returns/Raises; `Execution: Deferred, buffers the whole source, key_selector called once per element`; None-key rule; doctests:
  ```python
  >>> flp.it(["fig", "kiwi", "pear", "plum"]).maxima(len).to_list()
  ['kiwi', 'pear', 'plum']
  >>> flp.it(["fig", "kiwi", "pear", "plum"]).minima(len).to_list()
  ['fig']
  ```
- README deviations: None keys sort lowest; `IExtremaEnumerable` bounded-memory members dropped (values identical through `take`/`take_last`/`first`/`last`).
- Translation map: MoreLINQ `.Maxima(x => x.Score)` / Python `m = max(map(key, xs)); [x for x in xs if key(x) == m]` → `.maxima(lambda x: x.score)`; same for `Minima`.

## 8. Expected outcomes
- `maxima`/`minima` available on all four types, fully typed, one-pass and faster than the native two-pass idiom.
- Own test module green on FlpIt and FlpList; difftest specs with 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=maxima` and again with `<op>=minima`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_maxima_minima.py
uv run python -c "from flpit import flp; print(flp.it(['fig','kiwi','pear','plum']).maxima(len).to_list())"   # ['kiwi', 'pear', 'plum']
uv run python -c "from flpit import flp; print(flp.it([3, None, 1]).minima(lambda x: x).to_list())"           # [None]
```

## 10. Definition of Done
DoD-std, plus: README deviation entry (None keys, dropped `IExtremaEnumerable` members); `_extrema` helper shared by both methods (no duplicated loop).

## 11. Risks / open questions
- L27 (`max_by`/`min_by` backfill) may change how None keys are treated for those ops (.NET `MaxBy` skips null keys). That is a different .NET rule; `maxima` follows MoreLINQ (`Comparer<T>.Default`), so the two may legitimately differ. Cross-check wording with L27 so the README explains both.
- If users ask for `maxima(k).take(1)` on huge inputs with many ties, add the bounded-memory subclass as a follow-up.
