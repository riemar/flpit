---
id: L02
title: take_while (+ indexed)
status: todo
priority: 020
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: TakeWhileTests.cs @ dotnet/runtime main 6f1d9331 (20 [Fact]/[Theory], plus 1 stress-only [ConditionalFact])
  morelinq: n/a
pr:
---

# L02: `take_while` (+ `take_while_indexed`)

## 1. Goal
`TakeWhile` is the prefix counterpart of `where`: "take rows until the header ends", "read until the sentinel". It is a daily-use partitioning operator, maps one-to-one to `itertools.takewhile`, and is the first operator to ship a D4 indexed variant (`take_while_indexed`). Whichever of L02/L03/L15/L16 lands first establishes the indexed-variant pattern (registry `variant_of`, contract tests for `(item, index)` callbacks); by priority order that is this card.

## 2. Scope
**In:** `take_while(predicate)` and `take_while_indexed(predicate)` on `_LinqOps` (so `FlpIt`, `FlpList`, `OrderedIt`, `Grouping`). Registry support for `variant_of` and the indexed-callback contract test (if not already provided by F08).
**Out:** `skip_while` (L03); MoreLINQ `TakeUntil` (M22); a FlpList fast path (none possible: the predicate must run per element anyway).

## 3. Detailed design
### 3.1 Signatures
```python
def take_while(self, predicate: Callable[[TItem], object]) -> FlpIt[TItem]: ...
def take_while_indexed(self, predicate: Callable[[TItem, int], object]) -> FlpIt[TItem]: ...
```
.NET overload mapping (`ref/System.Linq.cs`):
| .NET | Python |
|---|---|
| `TakeWhile(Func<TSource,bool>)` | `take_while(predicate)` |
| `TakeWhile(Func<TSource,int,bool>)` | `take_while_indexed(predicate)` (D4; callback order `(item, index)` as in .NET) |

The predicate return type is `object` (truthiness), consistent with `where`; the docs show `bool`.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: yes, enumeration stops at the first element for which the predicate is falsy. That element is pulled from the source (it must be, to test it) and discarded, exactly as in .NET.
- Predicate truthiness: any truthy/falsy result is accepted (Python `if` semantics). A falsy *callable object* (`__bool__` returns `False`) is still a predicate: the code never tests the callable's truthiness, only `is None` (see `tests/luna_test_suite/test_falsey_callbacks.py`).
- Validation (eager): `predicate is None` raises `ArgumentNoneError("predicate")`. No `callable()` check (a non-callable fails at enumeration with Python's own `TypeError`, as for `where`).
- The predicate is called lazily, once per pulled element, never after the first falsy result. No call at all for an empty source.
- Index for the indexed variant starts at 0 and is a Python `int`. .NET throws `OverflowException` past `int.MaxValue` elements; Python ints do not overflow, so the index keeps growing. This is an intentional deviation (README § "Intentional Semantic Deviations", the existing "Python int can't overflow" entry is extended).
- `None` elements are ordinary values passed to the predicate.
- Re-enumeration: each enumeration re-iterates the source and restarts the index at 0. One-shot sources stay one-shot.
- On `OrderedIt` the result is `FlpIt` (no `then_by` afterwards), as in .NET.
- Exceptions from the source or the predicate propagate at enumeration time, from the `next()` call that triggered them.

### 3.3 Implementation sketch
```python
def take_while(self, predicate):
    _require_not_none(predicate, "predicate")           # F05 helper
    return FlpIt(_FactoryIterable(lambda: takewhile(predicate, self)))

def take_while_indexed(self, predicate):
    _require_not_none(predicate, "predicate")
    def _generator():
        for index, item in enumerate(self):
            if not predicate(item, index):
                return
            yield item
    return FlpIt(_FactoryIterable(_generator))
```
- `itertools.takewhile` is C-level: O(k) time for a k-element prefix, O(1) memory.
- The indexed variant uses a plain generator: a `takewhile` over `enumerate` needs a Python lambda plus `map(itemgetter(1), ...)`, which the benchmark should compare; keep whichever is faster (expected: the generator).
- **FlpList fast path:** none. No precomputation can avoid one predicate call per element. Decision recorded, no override.

### 3.4 Registry entry
```toml
[operators.take_while]
category = "partitioning"
kind = "intermediate"
buffering = "streaming"
short_circuit = true
dotnet = "Enumerable.TakeWhile"
python_equivalent = "itertools.takewhile(pred, xs)"
since = "0.3.0"

[operators.take_while_indexed]
category = "partitioning"
kind = "intermediate"
buffering = "streaming"
short_circuit = true
variant_of = "take_while"
dotnet = "Enumerable.TakeWhile (Func<TSource,int,bool>)"
python_equivalent = "(x for i, x in takewhile(lambda p: pred(p[1], p[0]), enumerate(xs)))"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_take_while.py` from `TakeWhileTests.cs` (20 counted cases + 1 stress case). Expected skips:
  - `INTERNAL_OPTIMIZATION`: `ForcedToEnumeratorDoesntEnumerate`, `ForcedToEnumeratorDoesntEnumerateIndexed` (cast of the iterable to `IEnumerator<T>`).
  - `OTHER` (Python ints do not overflow; also stress-only): `IndexTakeWhileOverflowBeyondIntMaxValueElements`.
  - `ThrowsOnNullSource*` are ported as `flp_type(None)` raising `SourceNoneError` (same pattern as `test_last.py`).
  - Target: 18 of 20 counted cases ported (90 %).
- **Own unit tests** (`tests/unit/test_take_while.py`):
  - Predicate call count: for `[1, 2, 5, 1]` and `x < 3` the predicate is called exactly 3 times, and the source is pulled 3 times.
  - Infinite source (`itertools.count()`) terminates.
  - Falsy callable object is used as a predicate; truthy non-bool results (`1`, `"x"`) keep taking.
  - `None` elements reach the predicate.
  - `take_while(None)` / `take_while_indexed(None)` raise `ArgumentNoneError` at call time, even on an empty source.
  - Indexed: indices seen are `0..k`; second enumeration restarts at 0.
  - `order_by(...).take_while(...)` applies ordering first.
- **Contracts** (auto via registry): no iteration at construction, callbacks lazy, one-shot stays one-shot, short-circuit (stops pulling after the first falsy result), FlpList not mutated. The indexed-callback contract (index starts at 0, increments by 1, resets per enumeration) is added to `tests/contracts/` here if F08 did not already.
- **Typing**: `assert_type(flp.lst([1]).take_while(lambda x: x > 0), FlpIt[int])`; `take_while_indexed(lambda x, i: i < 2)` returns `FlpIt[int]`; a 1-arg lambda passed to `take_while_indexed` is a pyrefly error (checked with `# pyrefly: expect-error` or the F08 equivalent).

## 5. Differential harness
`difftest/specs/take_while.toml` and `take_while_indexed.toml`: sources empty, singleton, ints with duplicates, strings, `None`-containing ints; predicates from the shared predicate catalogue (`always_true`, `always_false`, `lt_k`, `is_even`, `index_lt_k` for the indexed form); probes `result`, `predicate_calls`, `elements_pulled`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_take_while.py`, sizes 1e3 and 1e5, predicate `x < size // 2` over `range(size)` materialised as a list:
- `native`: `list(itertools.takewhile(lambda x: x < half, data))`
- `flpit-FlpIt`: `flp.it(data).take_while(lambda x: x < half).to_list()`; `flpit-FlpList`: `flp.lst(data).take_while(...).to_list()`
- indexed group (`take_while_indexed-<size>`): native `list(map(itemgetter(1), takewhile(lambda p: p[0] < half, enumerate(data))))` vs `flp.it(data).take_while_indexed(lambda x, i: i < half).to_list()`.
- Target ratio ≤ 1.5× (streaming).

## 7. Docs
- Docstrings: `.NET: Enumerable.TakeWhile(predicate)` / `TakeWhile((item, index) => ...)`; truthiness rule; "the first failing element is consumed from the source"; Execution: Deferred, Streaming, short-circuits.
- Doctests: `flp.it([1, 2, 5, 1]).take_while(lambda x: x < 3).to_list()` gives `[1, 2]`; `flp.it([5, 5, 5, 5]).take_while_indexed(lambda x, i: i < 2).to_list()` gives `[5, 5]`.
- Translation map: `itertools.takewhile(p, xs)` / `.TakeWhile(p)` → `.take_while(p)`; `.TakeWhile((x, i) => ...)` → `.take_while_indexed(lambda x, i: ...)`.
- README deviations: extend the "Python int can't overflow" note to indexed callbacks.

## 8. Expected outcomes
- `take_while` and `take_while_indexed` on all four types with typing.
- 18 ported .NET tests green, 3 categorised skips; own tests and contracts green.
- Indexed-variant pattern (`variant_of`, indexed contract test) available for L03, L15, L16, L17.

## 9. Verification
VERIFY-std with `<op>=take_while` (and again with `take_while_indexed` for the difftest), plus:
```bash
uv run pytest -q tests/nettests/test_take_while.py -rs     # 3 skips with categories
uv run python -c "from flpit import flp; print(flp.it([1, 2, 5, 1]).take_while(lambda x: x < 3).to_list())"   # [1, 2]
uv run python -c "import itertools; from flpit import flp; print(flp.it(itertools.count()).take_while(lambda x: x < 3).to_list())"   # [0, 1, 2]
```

## 10. Definition of Done
DoD-std, plus: registry supports `variant_of` and the README matrix renders the indexed variant on the same row as its base operator.

## 11. Risks / open questions
- If L15 (`where_indexed`) is pulled ahead of this card, it owns the indexed pattern and this card only reuses it.
- Typing an indexed predicate as `Callable[[TItem, int], object]` lets pyrefly reject single-argument lambdas; confirm the error message is readable in the typing test.
