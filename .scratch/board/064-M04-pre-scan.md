---
id: M04
title: pre_scan
status: todo
priority: 064
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: n/a
  morelinq: PreScan.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7)
pr:
---

# M04: `pre_scan`

## 1. Goal
`pre_scan` is the exclusive prefix scan: element *i* of the output is the fold of the first *i* inputs, starting from an identity. It yields "state before this element" (offsets from lengths, start times from durations, balance before each transaction) with the same length as the input, which `scan` (M03) cannot do without an extra `skip_last`. MoreLINQ ships it as `PreScan`; Python has no direct equivalent.

## 2. Scope
**In:** `pre_scan(func, identity)` on `_LinqOps`; own tests; MoreLINQ oracle op.
**Out:** an unseeded form (an exclusive scan needs an identity by definition); keyed variants.

## 3. Detailed design
### 3.1 Signatures
```python
def pre_scan(
    self,
    func: Callable[[TAccumulate, TItem], TAccumulate],
    identity: TAccumulate,
) -> FlpIt[TAccumulate]: ...
```
MoreLINQ `PreScan(transformation, identity)` is homogeneous (`TSource` everywhere). flpit types the accumulator separately (a strict superset; with `TAccumulate = TItem` it is the MoreLINQ signature), consistent with seeded `scan`. Argument order `(func, identity)` matches MoreLINQ and flpit's `scan(func, seed)`.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (one element of lookahead). Short-circuit: `pre_scan(f, id).first()` pulls 1 element (to know the source is non-empty) and calls `f` 0 times.
- Output for `[x0, x1, ..., x(n-1)]`: `id, f(id, x0), f(f(id, x0), x1), ...`, **length n** (the fold including the last element is never produced).
- Empty source → empty output (identity is **not** yielded; contrast seeded `scan`, which yields `[seed]`).
- `func` is called exactly `n - 1` times; the *i*-th output (*i* ≥ 1) is computed after pulling element *i* (MoreLINQ pull order).
- Relationship: for non-empty sources `pre_scan(f, id) == scan(f, id)` without its last element, and `pre_scan(f, id).zip(source, f)` equals `scan(f)` when `id` is a true identity of `f`.
- Validation (eager): `func is None` → `ArgumentNoneError("func")`. `identity` may be any value, including `None`; it is not checked to be an identity of `func` (documented: a non-identity seed gives a "seeded exclusive scan").
- Exceptions from `func` propagate after the earlier states were yielded; re-enumeration recomputes.

### 3.3 Implementation sketch
```python
def pre_scan(self, func, identity):
    _require_callable(func, "func")
    def _generator():
        it = iter(self)
        for first in it:                                            # non-empty check pulls x0
            heads = map(itemgetter(0), pairwise(chain((first,), it)))   # x0..x(n-2), each released after its successor is pulled
            yield from accumulate(chain((identity,), heads), func)
            return
    return FlpIt(_FactoryIterable(_generator))
```
- All C-level iterators (`pairwise`, `map`, `accumulate`); O(n) time, O(1) memory. Verified pull/call trace for `[1, 2, 3, 4]` with `+` and `0`: `pull1, yield0, pull2, f(0,1), yield1, pull3, f(1,2), yield3, pull4, f(3,3), yield6`, identical to MoreLINQ.
- The simpler `accumulate(chain((identity,), source), func)` minus its last item is rejected: it calls `func` `n` times (one wasted, observable call).
- **FlpList fast path** (`accumulate(data[:-1], func, initial=identity)`): rejected; `initial=None` means "no seed" in `accumulate`, and the slice copy buys nothing.

### 3.4 Registry entry
```toml
[operators.pre_scan]
category = "aggregation"
kind = "intermediate"
buffering = "partial"          # one-element lookahead
short_circuit = false
morelinq = "MoreEnumerable.PreScan"
python_equivalent = "accumulate(xs[:-1], f, initial=identity) if xs else []"
since = "0.3.0"                # next minor at merge time
```

## 4. Tests
- **Own tests** `tests/unit/morelinq/test_pre_scan.py` (from scratch, D7):
  - `[]`, `[5]`, `[1, 2, 3, 4]` with `+`, `0` → `[]`, `[0]`, `[0, 1, 3, 6]`.
  - Equivalence property against `scan(f, id)` minus last element (non-empty inputs, `random.Random(0)`, 200 cases) and output length == input length.
  - Pull/call trace exactly as in §3.3 (recording source and tracker); `func` count `n - 1`.
  - `identity=None` and non-identity seeds (`pre_scan(add, 100)` → `[100, 101, 103, 106]` for `[1, 2, 3, 4]`).
  - `func=None` raises at call time; infinite source + `take(3)` terminates; one-shot vs re-iterable source; `FlpList` not mutated.
  - Heterogeneous accumulator: `pre_scan(lambda acc, s: acc + len(s), 0)` over strings gives start offsets.
- **Contracts** (auto) + `elements_pulled(first) == 1`.
- **Typing**: `assert_type(flp.it([1]).pre_scan(operator.add, 0), FlpIt[int])`; `assert_type(flp.it(["ab"]).pre_scan(lambda acc, s: acc + len(s), 0), FlpIt[int])`.

## 5. Differential harness
`difftest/specs/pre_scan.toml`, oracle = MoreLINQ NuGet `PreScan` (homogeneous cases only): sources {empty, singleton, ints, strings with concatenation}; `(func, identity)` ∈ {(`+`, 0), (`*`, 1), (`max`, `int.MinValue` ↔ `-2**31`), (concat, "")}; probes `elements_pulled` and `func` call count. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_pre_scan.py`, sizes 1e3 and 1e5:
- `native`: `list(itertools.accumulate(data[:-1], operator.add, initial=0)) if data else []` (list-only idiom) and the streaming generator `def pre(xs): acc = 0; for x in xs: yield acc; acc += x` (one extra `+`, accepted for the baseline).
- `flpit-FlpIt`, `flpit-FlpList`: `.pre_scan(operator.add, 0).to_list()`.
- Target ≤ 1.5× vs the `accumulate` idiom.

## 7. Docs
- Docstring: `MoreLINQ: MoreEnumerable.PreScan(transformation, identity)`; exclusive vs inclusive (link to `scan`); empty → empty; `n - 1` calls; identity not validated. Doctest: `flp.it([1, 2, 3, 4]).pre_scan(lambda a, b: a + b, 0).to_list()` → `[0, 1, 3, 6]`.
- Translation map: MoreLINQ `.PreScan(f, id)` / `accumulate(xs[:-1], f, initial=id)` (non-empty lists) / numpy `np.cumsum` shifted by one → `.pre_scan(f, id)`.

## 8. Expected outcomes
- Exclusive scan available with MoreLINQ-identical pull order and callback count.
- MoreLINQ oracle 0 MISMATCH; benchmark recorded.

## 9. Verification
VERIFY-std with `<op>=pre_scan`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_pre_scan.py
uv run python -c "from flpit import flp; print(flp.it([1, 2, 3, 4]).pre_scan(lambda a, b: a + b, 0).to_list())"   # [0, 1, 3, 6]
uv run python -c "from flpit import flp; print(flp.it([]).pre_scan(lambda a, b: a + b, 0).to_list())"             # []
```

## 10. Definition of Done
DoD-std, plus: docstrings of `scan` and `pre_scan` cross-reference each other with the inclusive/exclusive example.

## 11. Risks / open questions
- Shares the `(func, seed)` ordering decision with M03; any change by L28 applies here too.
- Independent of M03 at code level; if both are in flight, land M03 first so the cross-reference docstrings resolve.
