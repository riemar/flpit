---
id: M10
title: run_length_encode
status: todo
priority: 070
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: RunLengthEncode.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7; RunLengthEncodeTest.cs has 6 [Test]/[TestCase])
pr:
---

# M10: `run_length_encode`

## 1. Goal
`run_length_encode` collapses runs of equal consecutive elements into `(item, count)` pairs: compression, histogram of streaks, "how long did each state last". It is the one-line answer to the common `[(k, len(list(g))) for k, g in groupby(xs)]` idiom and lands right after `group_adjacent` (M09), whose `groupby` core it shares.

## 2. Scope
**In:** `run_length_encode()` on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`), yielding plain `tuple[TItem, int]`.
**Out:** the comparer overload (D3). Its use-case ("runs ignoring case") is `group_adjacent(str.lower, result_selector=lambda k, xs: (xs[0], len(xs)))`, documented in the docstring. A `run_length_decode` (not in MoreLINQ; `select_many(lambda p: repeat(*p))` covers it).

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `RunLengthEncode()` → `IEnumerable<KeyValuePair<T, int>>` | `run_length_encode()` → `FlpIt[tuple[TItem, int]]` |
| `RunLengthEncode(IEqualityComparer<T>)` | omitted (D3), see above |

`KeyValuePair<T, int>` maps to a 2-tuple (`Key` → `[0]`, `Value` → `[1]`), which unpacks naturally (`for item, n in ...`) and matches what `dict(...)`/`Counter` style code expects.

## 3. Detailed design
### 3.1 Signatures
```python
def run_length_encode(self) -> FlpIt[tuple[TItem, int]]: ...
```

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming (O(1): only the current run's representative and its count). Short-circuit: n/a; a pair is yielded when the next different element (or end) is seen.
- Equality: `previous == current` (Python `==`, the `itertools.groupby` comparison; MoreLINQ calls `comparer.Equals(prev, current)` in the same order).
- The reported item is the **first** element of the run (relevant for equal-but-distinct objects, e.g. `1` and `1.0` and `True`: `[1, 1.0, True]` → `[(1, 3)]`).
- Counts are always ≥ 1. Empty source → empty. Non-adjacent repeats are separate runs.
- `None` elements form runs like any value.
- No arguments, so no validation beyond the source itself.
- Re-enumeration re-runs the source. Source exceptions propagate at enumeration; the open run is not yielded.

### 3.3 Implementation sketch
```python
def run_length_encode(self):
    src = self._source()
    def _generator():
        for item, run in groupby(src):
            yield item, _ilen(run)
    return FlpIt(_FactoryIterable(_generator))

def _ilen(it):                      # module helper, no list allocation per run
    counter = count()
    deque(zip(it, counter), maxlen=0)
    return next(counter)
```
- `groupby` keys by identity function (C path); `item` is the group's first element. `_ilen` counts without building a list (C-level `deque(maxlen=0)` consumer); the benchmark compares it with `len(list(run))` and keeps the faster (short runs may favour `len(list(...))`).
- O(n) time, O(1) memory. **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.run_length_encode]
category = "grouping"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
morelinq = "MoreEnumerable.RunLengthEncode"
python_equivalent = "[(k, len(list(g))) for k, g in itertools.groupby(xs)]"
since = "0.4.0"   # Phase 3 target; adjust when the release is cut
```

## 4. Tests
- **Ported:** none (D7). `RunLengthEncodeTest.cs` (6 cases) as checklist:
  - covered: laziness, empty sequence, results on mixed runs, no runs (all distinct), one run (all equal).
  - `COMPARER_NOT_SUPPORTED`: `TestRunLengthEncodeCustomComparer`; own equivalent via `group_adjacent(str.lower, ...)` documents the replacement.
  - Target: 100 % of applicable behaviours.
- **Own unit tests** (`tests/unit/morelinq/test_run_length_encode.py`, both `flp_type`s):
  - `"aaabccdd"` → `[('a', 3), ('b', 1), ('c', 2), ('d', 2)]`; all distinct → all counts 1; all equal → one pair with `len`.
  - Non-adjacent repeats; `None` runs; first-of-run representative with `[1, 1.0, True]`.
  - Streaming: first pair yielded right after pulling the first element of the second run (counting source); infinite source + `take(2)` terminates.
  - Large run (1e6 equal items) counted correctly without O(n) memory (tracemalloc bound).
  - Round trip: `select_many(lambda p: itertools.repeat(*p))` reproduces the source.
  - One-shot vs list re-enumeration.
- **Contracts:** auto via registry.
- **Typing** (`tests/typing/test_types_run_length_encode.py`): `assert_type(flp.it("ab").run_length_encode(), FlpIt[tuple[str, int]])`.

## 5. Differential harness
`difftest/specs/run_length_encode.toml`, oracle calls `MoreEnumerable.RunLengthEncode(source)` (pinned `morelinq` NuGet) and serialises each `KeyValuePair` as `[key, value]`. Domains: empty, singleton, all equal, all distinct, alternating, strings with nulls, long runs (1e4). Probes: pairs, `elements_pulled` after `first()`. Expected: MATCH; `EXPECTED_DIFFERENCE` for NaN runs (.NET `double.Equals` treats NaN as equal, Python `==` does not) and for mixed `int`/`float`/`bool` equal values (not representable as one .NET element type; marked `UNCOMPARABLE`).

## 6. Benchmarks
`tests/benchmarks/test_bench_run_length_encode.py`, sizes 1e3 / 1e5, data with runs of length 1..20:
- `native`: `[(k, len(list(g))) for k, g in itertools.groupby(data)]`.
- `flpit-FlpIt` / `flpit-FlpList`: `run_length_encode().to_list()`.
- Target ratio ≤ 1.5× (streaming).

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.RunLengthEncode()`; Returns `(item, count)` tuples; `Execution:` deferred, streaming, O(1) memory; note on first-of-run representative and on the comparer replacement recipe.
- Doctest:
  ```python
  >>> flp.it("aaabccdd").run_length_encode().to_list()
  [('a', 3), ('b', 1), ('c', 2), ('d', 2)]
  >>> flp.it([1, 1, 2, 2, 2, 1]).run_length_encode().to_list()
  [(1, 2), (2, 3), (1, 1)]
  ```
- Translation map: `.RunLengthEncode()` / `[(k, len(list(g))) for k, g in groupby(xs)]` → `.run_length_encode()`.
- Deviations (README): `KeyValuePair` → tuple; `==` equality (NaN runs are split).

## 8. Expected outcomes
- `run_length_encode` on all four types; ~10 own tests; difftest 0 MISMATCH; benchmark recorded.

## 9. Verification
VERIFY-std with `<op>=run_length_encode`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_run_length_encode.py
uv run python -c "from flpit import flp; print(flp.it('aaabccdd').run_length_encode().to_list())"
# [('a', 3), ('b', 1), ('c', 2), ('d', 2)]
```

## 10. Definition of Done
DoD-std, plus the `_ilen` vs `len(list(...))` measurement recorded in the PR.

## 11. Risks / open questions
- Tuple versus a named `RunLength(item, count)` NamedTuple: a NamedTuple is still a tuple (unpacking works) and adds `.item`/`.count` (but `.count` shadows `tuple.count`). Proposal: plain tuple, consistent with `zip` and `lag`/`lead`.
