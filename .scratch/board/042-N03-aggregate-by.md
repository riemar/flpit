---
id: N03
title: aggregate_by
status: todo
priority: 042
effort: S
depends_on: [F05, F06, F07, F08, F09, N02]
upstream:
  dotnet: AggregateByTests.cs @ dotnet/runtime main 6f1d9331 (12 [Fact]/[Theory])
  morelinq: AggregateBy.cs (reference only, D7; superseded by the .NET 9 operator)
pr:
---

# N03: `aggregate_by`

## 1. Goal
`AggregateBy` (.NET 9) folds elements per key in one pass without materialising groups: sums per category, running maxima per id, "group into custom containers". It is the general form of `count_by` (N02) and reuses its `KeyValue` result type and buffering pattern. Today users write `group_by(k).select(lambda g: (g.key, g.aggregate(f, seed)))`, which keeps every element in memory.

## 2. Scope
**In:** `aggregate_by` on `_LinqOps` with both .NET seeding forms (constant `seed`, per-key `seed_selector`).
**Out:** the `keyComparer` parameter (D3, normalise in `key_selector`). A result-selector variant (not in .NET; `.select(...)` afterwards).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def aggregate_by(
    self,
    key_selector: Callable[[TItem], TKey],
    func: Callable[[TAccumulate, TItem], TAccumulate],
    seed: TAccumulate,
) -> FlpIt[KeyValue[TKey, TAccumulate]]: ...
@overload
def aggregate_by(
    self,
    key_selector: Callable[[TItem], TKey],
    func: Callable[[TAccumulate, TItem], TAccumulate],
    *,
    seed_selector: Callable[[TKey], TAccumulate],
) -> FlpIt[KeyValue[TKey, TAccumulate]]: ...
```
| .NET overload | flpit |
|---|---|
| `AggregateBy(keySelector, TAccumulate seed, func, keyComparer = null)` | `aggregate_by(key_selector, func, seed)` |
| `AggregateBy(keySelector, Func<TKey,TAccumulate> seedSelector, func, keyComparer = null)` | `aggregate_by(key_selector, func, seed_selector=...)` |

- **Argument order** follows flpit's existing `aggregate(func, seed)` (func before seed), not .NET's `(seed, func)`, so the two methods read alike. Keep consistent with L28.
- `seed_selector` is **keyword-only**: in Python a callable can itself be a legitimate seed, so the two forms cannot be told apart by type as C# does.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: full (whole source consumed on the first `next()`, memory O(distinct keys)). Short-circuit: none.
- Validation (eager, .NET order): `key_selector` `None` → `ArgumentNoneError("key_selector")`; `seed_selector` explicitly `None` → `ArgumentNoneError("seed_selector")`; `func` `None` → `ArgumentNoneError("func")`. Passing both `seed` and `seed_selector`, or neither → `TypeError("aggregate_by() requires exactly one of 'seed' or 'seed_selector'")`. `seed=None` is a valid seed (`_SENTINEL` distinguishes "not passed").
- Per element, in source order: `key_selector(item)`; for a key seen for the first time `seed_selector(key)` (once per key); then `func(acc, item)`. All callbacks run before the first pair is yielded.
- Output: `KeyValue(key, acc)` in first-occurrence key order (same as .NET `Dictionary` insertion order).
- **Shared seed object**: with `seed=`, every key starts from the *same* object, as in .NET with a reference-type seed. A mutable seed mutated in place (`seed=[]` with `acc.append`) is shared between keys; docs point to `seed_selector=lambda _: []`.
- Empty source → empty, no callback called. Unhashable key → `TypeError` at enumeration. Exceptions from callbacks propagate on the first `next()`; nothing is yielded.
- Re-enumeration recomputes (seed_selector called again per key).
- **Deviations**: `None` keys allowed (.NET throws `ArgumentNullException`); `KeyValue` NamedTuple instead of `KeyValuePair`; func-before-seed argument order. All in README § Intentional Semantic Deviations (shared entries with N02).

### 3.3 Implementation sketch
```python
def aggregate_by(self, key_selector, func, seed=_SENTINEL, *, seed_selector=_SENTINEL):
    _require_callable(key_selector, "key_selector")
    if seed_selector is not _SENTINEL:
        _require_callable(seed_selector, "seed_selector")
    _require_callable(func, "func")
    if (seed is _SENTINEL) == (seed_selector is _SENTINEL):
        raise TypeError("aggregate_by() requires exactly one of 'seed' or 'seed_selector'")
    src = self._source()
    def _generator():
        acc: dict = {}
        get = acc.get
        for item in src:
            key = key_selector(item)
            cur = get(key, _MISSING)
            if cur is _MISSING:
                cur = seed if seed_selector is _SENTINEL else seed_selector(key)
            acc[key] = func(cur, item)
        yield from map(_make_kv, acc.items())
    return FlpIt(_FactoryIterable(_generator))
```
- One dict probe (`get`) plus one store per element; O(n) time, O(k) memory.
- The `seed_selector is _SENTINEL` test sits in the per-new-key branch only, so the hot path has no extra check. Two specialised loops are not worth it (measure; keep one loop unless > 5 % difference).
- **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.aggregate_by]
category = "aggregation"
kind = "intermediate"
buffering = "full"
short_circuit = false
origin = "dotnet"
dotnet = "Enumerable.AggregateBy"
morelinq = "MoreEnumerable.AggregateBy"
python_equivalent = "acc = {}; for x in xs: acc[k(x)] = f(acc.get(k(x), seed), x)"
since = "0.4.0"
card = "N03"
notes = "func before seed (like aggregate); seed_selector keyword-only; None keys allowed."
```

## 4. Tests
- **Ported** `tests/nettests/test_aggregate_by.py` from `AggregateByTests.cs` (12 cases):
  - `Empty` over the F08 source variants (list, tuple, FlpList, `non_collection`), both seeding forms.
  - Null-argument tests (`SourceNull`, `KeySelectorNull`, `SeedSelectorNull`, `FuncNull`): ported for the no-comparer calls; the comparer calls are dropped with a `COMPARER_NOT_SUPPORTED` comment.
  - `SourceThrowsOnGetEnumerator / OnMoveNext / OnCurrent`: ported with `tests.helpers` throwing iterables.
  - `HasExpectedOutput`: all `Validate` calls except the two `OrdinalIgnoreCase` ones (rewriting with `str.lower` changes the yielded key); each runs on a list and a `RunOnce` source.
  - `GroupBy` (seed_selector returning a fresh list), `LongCountBy` (`seed=0`, `lambda c, _: c + 1`), `Score`: ported as is.
  - Target: 12/12 test functions ported (100 %); 2 of 11 `Validate` calls dropped.
- **Own unit tests** (`tests/unit/test_aggregate_by.py`):
  - Exactly-one rule: neither / both seeding forms raise `TypeError` at call; `seed=None` accepted.
  - Shared mutable seed documented behaviour (`seed=[]` + in-place append shares the list) vs `seed_selector` (separate lists).
  - Call counts and order: `seed_selector` once per distinct key, `func` once per element, recorded call log for `[a1, b1, a2]` is `k(a1), s(a), f, k(b1), s(b), f, k(a2), f`.
  - `None` keys; first-occurrence order; deferral (`NoIterList`); re-enumeration calls `seed_selector` again.
- **Contracts**: auto (registry).
- **Typing**: both overloads, e.g. `assert_type(flp.it([("a", 1)]).aggregate_by(lambda t: t[0], lambda a, t: a + t[1], 0), FlpIt[KeyValue[str, int]])`; the `seed_selector` form infers `TAccumulate` from the selector.

## 5. Differential harness
`difftest/specs/aggregate_by.toml`: sources: empty, singleton, ints with duplicates, `(name, age)` records; keys: identity, `x % 5`, constant; seeding: `seed ∈ {0, ""}` and `seed_selector = key -> f"seed{key}"`; func: sum, string concat. Probes: values, callback call log (seed_selector count), exception type for null arguments. Null-key domain `EXPECTED_DIFFERENCE` (as N02). Expected: all other cases MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_aggregate_by.py`, sizes 1e3 and 1e5, `key = x % 100`, `func = operator.add`, `seed = 0`:
- `native`: `acc = {}` then `for x in data: k = key(x); acc[k] = func(acc.get(k, 0), x)`; `list(acc.items())` (same callbacks, so the ratio isolates operator overhead).
- `flpit-FlpIt`: `flp.it(data).aggregate_by(key, func, 0).to_list()`; `flpit-FlpList`: same on `flp.lst(data)`.
- Target ratio ≤ 1.3×.

## 7. Docs
- Docstring: "Applies an accumulator per key and yields one (key, accumulated value) pair per distinct key."; `.NET: Enumerable.AggregateBy(keySelector, seed | seedSelector, func)`; Args (note func/seed order and keyword-only `seed_selector`), Raises, Execution (deferred, full buffering O(keys)); warning about shared mutable seeds. Example:
  ```python
  >>> scores = [("0", 42), ("1", 5), ("2", 4), ("1", 10), ("0", 25)]
  >>> dict(flp.it(scores).aggregate_by(lambda e: e[0], lambda total, e: total + e[1], 0))
  {'0': 67, '1': 15, '2': 4}
  >>> flp.it([1, 2, 3, 4]).aggregate_by(lambda x: x % 2, lambda acc, x: acc + [x], seed_selector=lambda k: [k]).to_list()
  [KeyValue(key=1, value=[1, 1, 3]), KeyValue(key=0, value=[0, 2, 4])]
  ```
- README matrix row; deviation entries (argument order; shared with N02 for None keys).
- Translation map: `.AggregateBy(k, seed, f)` → `.aggregate_by(k, f, seed)`; `.AggregateBy(k, s => ..., f)` → `.aggregate_by(k, f, seed_selector=...)`; Python idiom `defaultdict` loop.

## 8. Expected outcomes
- `aggregate_by` on all four types with both seeding forms, fully typed.
- 12 ported .NET tests green, own tests, benchmark recorded, difftest 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=aggregate_by`, plus:
```bash
uv run pytest -q tests/nettests/test_aggregate_by.py -rs
uv run python -c "from flpit import flp; print(dict(flp.it([1,2,3,4]).aggregate_by(lambda x: x % 2, lambda a, x: a + x, 0)))"
# {1: 4, 0: 6}
```

## 10. Definition of Done
DoD-std, plus the argument-order deviation and the shared-seed warning documented (docstring and README).

## 11. Risks / open questions
- Argument order (func, seed) vs .NET (seed, func): chosen for consistency with flpit's `aggregate`. If L28 changes `aggregate` to .NET order, this card follows it before merge; the two must not diverge.
- `seed_selector` keyword-only makes the .NET positional form `AggregateBy(k, s => ..., f)` impossible to transcribe literally; the translation map shows the keyword form.
