---
id: M16
title: cartesian
status: todo
priority: 077
effort: S
depends_on: [F05, F06, F07, F08, F09, M14]
upstream:
  dotnet: n/a (closest: query syntax `from a in xs from b in ys`, i.e. SelectMany)
  morelinq: Cartesian.g.cs @ morelinq/MoreLINQ master d217ab1 (reference only, D7; CartesianTest.cs has 7 [Test]/[TestCase])
pr:
---

# M16: `cartesian`

## 1. Goal
`cartesian` produces every combination of one element from each sequence (grids, test matrices, configuration sweeps), in nested-loop order. Python has `itertools.product`; flpit gets the fluent form with a `result_selector`, without the nested `select_many` lambdas that LINQ users otherwise write.

## 2. Scope
**In:** `cartesian(*others, result_selector=...)` on `_LinqOps` (`FlpIt`, `FlpList`, `OrderedIt`, `Grouping`); typed overloads for 1 to 3 others, variadic `Any` fallback (MoreLINQ goes up to 8 sequences).
**Out:** `product(repeat=n)` (use `cartesian(xs, xs)`); lazily memoised inner sequences (see §3.2 deviation).

**MoreLINQ overload mapping** (7 generated overloads)
| MoreLINQ | flpit |
|---|---|
| `Cartesian(second, Func<T1, T2, TResult>)` | `cartesian(second, result_selector=f)` |
| `Cartesian(second, third, Func<...>)` | `cartesian(second, third, result_selector=f)` |
| `Cartesian(second, third, fourth, Func<...>)` | `cartesian(second, third, fourth, result_selector=f)` |
| 5- to 8-sequence overloads | `cartesian(*others, result_selector=f)` (typed `Callable[..., TResult]`) |
| (none) | no selector → tuples |

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def cartesian(self, second: Iterable[T2], /) -> FlpIt[tuple[TItem, T2]]: ...
@overload
def cartesian(self, second: Iterable[T2], /, *, result_selector: Callable[[TItem, T2], TResult]) -> FlpIt[TResult]: ...
@overload
def cartesian(self, second: Iterable[T2], third: Iterable[T3], /) -> FlpIt[tuple[TItem, T2, T3]]: ...
@overload
def cartesian(self, second: Iterable[T2], third: Iterable[T3], /, *,
              result_selector: Callable[[TItem, T2, T3], TResult]) -> FlpIt[TResult]: ...
# (second, third, fourth): same two shapes
@overload
def cartesian(self, *others: Iterable[Any], result_selector: Callable[..., TResult]) -> FlpIt[TResult]: ...
@overload
def cartesian(self, *others: Iterable[Any]) -> FlpIt[tuple[Any, ...]]: ...
```
TypeVars `T2..T4` and the `_require_others` helper come from M14.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: partial (all `others` are cached per enumeration; `self` is streamed). Short-circuit: n/a.
- Order: nested loops, `self` outermost, last argument innermost (`(a1,b1), (a1,b2), (a2,b1), ...`), identical to MoreLINQ and `itertools.product`.
- **`self` is streamed**: an infinite `self` with finite others yields forever; `take(k)` works.
- **Inner sequences**: each of `others` is enumerated **once per enumeration** of the query and cached, so one-shot iterators work as inner sequences. MoreLINQ memoises them lazily (pulled on the first outer element); flpit materialises them with `tuple()` when the first outer element arrives. Values and order are identical; the difference is visible only through pull timing or infinite inner sequences (MoreLINQ streams `(a1, b1), (a1, b2), ...`; flpit would not return). Documented deviation.
- Empty `self` → empty, and **others are never enumerated** (same as MoreLINQ). Any empty other → empty, but `self` is still fully enumerated (MoreLINQ does the same; kept for observable parity).
- Validation (eager): at least one other (`TypeError`); `None` in `others` → `ArgumentNoneError("others")`; `result_selector=None` → `ArgumentNoneError("result_selector")`.
- Re-enumeration: re-runs `self` and re-caches every other (one-shot inner iterators are empty the second time, as with any one-shot source).
- Exceptions from sources or the selector propagate at enumeration.

### 3.3 Implementation sketch
```python
def _generator():
    outer = iter(src)
    for first in outer:                                   # nothing cached if src is empty
        pools = [tuple(o) for o in others]                # one pass per enumeration, in argument order
        rows = chain(product((first,), *pools),
                     chain.from_iterable(product((a,), *pools) for a in outer))
        if result_selector is not _SENTINEL:
            rows = starmap(result_selector, rows)
        yield from rows
        return
```
- `product((a,), *pools)` keeps the outer streaming while the inner combinations are produced in C. O(|self| × Π|others|) time, O(Σ|others|) memory.
- Plain `itertools.product(src, *others)` was rejected: it materialises `self` too (breaks infinite/streaming `self` and the "empty self never touches others" rule).
- **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.cartesian]
category = "combinatorics"
kind = "intermediate"
buffering = "partial"
short_circuit = false
morelinq = "MoreEnumerable.Cartesian"
python_equivalent = "itertools.product(a, b)"
since = "0.4.0"   # Phase 3 target; adjust when the release is cut
```

## 4. Tests
- **Ported:** none (D7). `CartesianTest.cs` (7 cases) as checklist, all applicable and covered: laziness, empty × empty, empty × non-empty (both orders), product count (2-D and multi-dimensional), combinations content and order, empty evaluation. Target: 100 %.
- **Own unit tests** (`tests/unit/morelinq/test_cartesian.py`, both `flp_type`s):
  - `[1, 2].cartesian("ab")` → `[(1, 'a'), (1, 'b'), (2, 'a'), (2, 'b')]`; 3- and 4-way; 5-way via fallback with selector.
  - Count equals the product of lengths for random small lengths (equals `len(list(itertools.product(...)))`).
  - Empty `self`: others are never iterated (instrumented iterable); empty other: `self` fully pulled, nothing yielded.
  - Infinite `self` + `take(5)` terminates; one-shot generator as inner sequence works once per enumeration.
  - Selector called once per combination with positional args.
  - Validation errors at call time.
- **Contracts:** auto via registry.
- **Typing:** `assert_type(flp.it([1]).cartesian(["a"]), FlpIt[tuple[int, str]])`, 3/4-arity, selector, fallback `FlpIt[tuple[Any, ...]]`.

## 5. Differential harness
`difftest/specs/cartesian.toml`, oracle calls the 2/3/4-sequence `MoreEnumerable.Cartesian` overloads with a tuple selector (pinned `morelinq` NuGet). Domains: lengths {0, 1, 2, 3} per sequence (capped at 4 sequences), ints/strings. Probes: values, outer `move_next` trace. Expected: MATCH for values and outer-sequence trace; `EXPECTED_DIFFERENCE` for inner-sequence `move_next` timing (eager `tuple()` vs lazy memo), declared in the spec with that reason.

## 6. Benchmarks
`tests/benchmarks/test_bench_cartesian.py`, sizes 1e3 / 1e5 output rows (e.g. `a = range(n // 100)`, `b = range(100)`):
- `native`: `list(itertools.product(a, b))`.
- `flpit-FlpIt` / `flpit-FlpList`: `flp.it(a).cartesian(b).to_list()`.
- Target ratio ≤ 1.3× (one `product` call per outer element adds overhead when `b` is short; the 100-wide inner keeps it small).

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.Cartesian(...)`; Args; Raises; `Execution:` deferred, streams `self`, caches each other sequence once per enumeration.
- Doctest:
  ```python
  >>> flp.it([1, 2]).cartesian("ab").to_list()
  [(1, 'a'), (1, 'b'), (2, 'a'), (2, 'b')]
  >>> flp.it([1, 2]).cartesian([10, 20], result_selector=lambda a, b: a * b).to_list()
  [10, 20, 20, 40]
  ```
- Translation map: `.Cartesian(b, f)` / `from a in xs from b in ys select f(a, b)` / `itertools.product(a, b)` → `.cartesian(b, result_selector=f)`.
- Deviations (README): inner sequences materialised on the first outer element (infinite inner sequences unsupported).

## 8. Expected outcomes
- `cartesian` on all four types; ~12 own tests; difftest 0 MISMATCH (with the declared timing difference); benchmark recorded.

## 9. Verification
VERIFY-std with `<op>=cartesian`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_cartesian.py
uv run python -c "from flpit import flp; print(flp.it([1,2]).cartesian('ab').to_list())"   # [(1, 'a'), (1, 'b'), (2, 'a'), (2, 'b')]
```

## 10. Definition of Done
DoD-std, plus the README deviation entry for inner-sequence materialisation.

## 11. Risks / open questions
- If lazy memoisation is ever required (infinite inner sequences), a small `_Memo` iterable can replace `tuple()` at a measured speed cost; out of scope unless requested.
- `depends_on: M14` only for the shared helper/TypeVars; if M16 lands first it introduces them instead.
