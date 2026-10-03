---
id: N01
title: index
status: todo
priority: 040
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: IndexTests.cs @ dotnet/runtime main 6f1d9331 (3 [Fact]/[Theory], plus 2 stress-only [ConditionalFact])
  morelinq: n/a
pr:
---

# N01: `index`

## 1. Goal
`Index()` (.NET 9) is LINQ's `enumerate`: it pairs each element with its position. It opens Phase 2 because it is tiny, has no dependencies, and is where the board **decides once how operators that return .NET named tuples look in Python**. Joins (N04 to N06), `count_by`/`aggregate_by` (N02/N03) and L25's tuple `join` overload reuse the decision recorded here.

## 2. Scope
**In:** `index()` on `_LinqOps` (FlpIt, FlpList, OrderedIt, Grouping). New module `src/flpit/core/tuples.py` with the `Indexed` NamedTuple, exported from `flpit` and `flpit.core.linq`. The named-tuple convention (below) written into `.agents/rules.md`.
**Out:** a `start=` offset (Python extension not in .NET; `select_indexed` (L16) or `zip(flp.infinite_sequence(start, 1))` covers it). `KeyValue` and `JoinPair` types: added by N02 and N04 respectively, following this card's convention.

### Decision: named-tuple results (applies to N01 to N06, L25)
.NET returns `ValueTuple`s with element names (`(int Index, TSource Item)`, `(TOuter Outer, TInner? Inner)`) or `KeyValuePair<TKey, TValue>`. flpit returns **generic `typing.NamedTuple` subclasses** with snake_case field names:

| .NET result | flpit type | fields | card |
|---|---|---|---|
| `(int Index, T Item)` | `Indexed[T]` | `index`, `item` | N01 |
| `KeyValuePair<TKey, TValue>` | `KeyValue[K, V]` | `key`, `value` | N02 |
| `(TOuter Outer, TInner Inner)` | `JoinPair[O, I]` | `outer`, `inner` | N04 (L25 adopts) |

Why: attribute access mirrors .NET (`x.Index` becomes `x.index`), while the value **is still a tuple**: unpacking (`for i, x in q.index()`), indexing, hashing, `dict(q)` for 2-tuples, and equality with plain tuples (`Indexed(0, "a") == (0, "a")` is `True`) all keep working. Cost: construction is ~2.4× a plain tuple (measured on 3.12: 100k items, `list(enumerate(xs))` 8.2 ms vs `map(partial(tuple.__new__, Indexed), enumerate(xs))` 19.4 ms; `Indexed._make` 27 ms, `starmap(Indexed, ...)` 32 ms), accepted for the readability.
**Exception: `zip` keeps plain tuples** (N08). Python's `zip` idiom dominates, `First`/`Second` names carry no information, and zip is a hot path.

## 3. Detailed design
### 3.1 Signatures
```python
# src/flpit/core/tuples.py
class Indexed[T](NamedTuple):
    index: int
    item: T

# _LinqOps
def index(self) -> FlpIt[Indexed[TItem]]: ...
```
### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: n/a.
- No arguments, so nothing to validate; the source-`None` case is already rejected by `FlpIt(None)` (`SourceNoneError`).
- Indices start at 0 and increase by 1 per element, per enumeration (re-enumerating restarts at 0). One-shot source stays one-shot.
- `None` elements are yielded as `Indexed(i, None)`; elements are never truth-tested.
- On `OrderedIt` the index is assigned after sorting (`order_by(k).index()` numbers the sorted output) and the result is `FlpIt`, so `then_by` is no longer available, as in .NET.
- Source exceptions propagate at enumeration time, after the elements already yielded.
- **Deviation**: .NET throws `OverflowException` after `int.MaxValue` elements; Python ints don't overflow, so no limit (README § Intentional Semantic Deviations, "no fixed-width integer overflow", shared entry with N02/N12).

### 3.3 Implementation sketch
```python
_make_indexed = partial(tuple.__new__, Indexed)        # C-level construction, no __new__ in Python

def index(self):
    src = self._source()
    return FlpIt(_FactoryIterable(lambda: map(_make_indexed, enumerate(src))))
```
- Fully C-level pipeline (`enumerate` + `map` + `tuple.__new__`): O(n) time, O(1) memory.
- `tuple.__new__(Indexed, pair)` bypasses NamedTuple's Python `__new__`; it is the documented `_make` path without the classmethod call. A unit test asserts `type(x) is Indexed`.
- **FlpList fast path**: none; the mixin already iterates the backing list directly.
- When N10 lands, `index()` registers a count provider (count-preserving).
- PEP 695 generic NamedTuple works on 3.12+ (D2); spike `pyrefly` strict on `Indexed[int]` field types first (see §11).

### 3.4 Registry entry
```toml
[operators.index]
category = "projection"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
origin = "dotnet"
dotnet = "Enumerable.Index"
python_equivalent = "enumerate(xs)"
since = "0.4.0"
card = "N01"
notes = "Yields Indexed(index, item) NamedTuples; no int overflow."
```

## 4. Tests
- **Ported** `tests/nettests/test_index.py` from `IndexTests.cs` (3 + 2 conditional):
  - `Empty`, `Index` ported; `Index_SourceIsNull` ported as `FlpIt(None)` raising `SourceNoneError`.
  - `LONG_RUNNING`: `LargeEnumerable_ThrowsOverflowException`, `LargeEnumerable` (stress-only upstream, 2³¹ elements; the overflow one is also a deviation).
  - Target: 3/3 non-stress cases ported (100 %).
- **Own unit tests** (`tests/unit/test_index.py`):
  - Values and type: `x.index`, `x.item`, `type(x) is Indexed`, `x == (0, "a")`, unpacking in a `for` loop, `dict(flp.it("ab").index())` gives `{0: "a", 1: "b"}`.
  - Re-enumeration restarts at 0 (list source); one-shot generator second pass empty.
  - `order_by(...).index()` numbers sorted output; `index().where(lambda p: p.index % 2 == 0)` composes.
  - `None` and falsy elements (`Bomb`, `Falsy` helpers) preserved, never truth-tested.
  - Pickle round-trip of `Indexed` (NamedTuple at module level).
- **Contracts**: auto via registry (deferral, one-shot, FlpList not mutated).
- **Typing** `tests/typing/test_types_index.py`: `assert_type(flp.lst(["a"]).index(), FlpIt[Indexed[str]])`; `assert_type(next(iter(flp.it([1]).index())).item, int)`; `.index` is `int`.

## 5. Differential harness
`difftest/specs/index.toml`: sources: empty, singleton, ints with duplicates, strings with nulls, 1000 ints. Probes: values (the runner converts `Indexed` to a 2-element JSON array, .NET `ValueTuple` likewise), `enumeration_count`, `elements_pulled` for `index().take(k)` (`k ∈ {0, 1, 3}`). Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_index.py`, sizes 1e3 and 1e5:
- `native`: `list(enumerate(data))`; second reference `native-named`: `[Indexed(i, x) for i, x in enumerate(data)]` (what a user writes to get names).
- `flpit-FlpIt`: `flp.it(data).index().to_list()`; `flpit-FlpList`: `flp.lst(data).index().to_list()`.
- Target ratio: ≤ 2.6× vs `native` (NamedTuple construction cost, see decision), ≤ 1.0× vs `native-named`. Both recorded in the PR.

## 7. Docs
- Docstring: "Pairs each element with its zero-based position."; `.NET: Enumerable.Index()`; Returns `FlpIt[Indexed[TItem]]`; Execution: deferred, streaming, restarts at 0 on re-enumeration. Example:
  ```python
  >>> flp.it("ab").index().to_list()
  [Indexed(index=0, item='a'), Indexed(index=1, item='b')]
  >>> [f"{i}:{c}" for i, c in flp.it("xy").index()]
  ['0:x', '1:y']
  ```
- `Indexed` class docstring (fields, tuple compatibility).
- README: matrix row (generated); new short section "Named tuple results" with the decision table above; deviation "no fixed-width integer overflow".
- Translation map: `enumerate(xs)` / `.Index()` → `.index()`.

## 8. Expected outcomes
- `index()` available on all four types; `Indexed` importable from `flpit`.
- Named-tuple convention documented in README and `.agents/rules.md`, referenced by N02 to N06 and L25.
- 3 ported .NET tests green (2 stress skips), own tests, typing, benchmark ratio and difftest spec with 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=index`, plus:
```bash
uv run pytest -q tests/nettests/test_index.py -rs
uv run python -c "from flpit import flp; print(flp.it('ab').index().to_list())"
# [Indexed(index=0, item='a'), Indexed(index=1, item='b')]
uv run python -c "from flpit import Indexed; print(Indexed(0, 'a') == (0, 'a'))"   # True
```
Manual: README "Named tuple results" section present; `inspect.getdoc(flp.lst([]).index)` non-empty.

## 10. Definition of Done
DoD-std, plus:
- [ ] `src/flpit/core/tuples.py` with `Indexed`, exported in `flpit.__all__`.
- [ ] Named-tuple convention recorded in README and `.agents/rules.md` (including the `zip` exception).
- [ ] Both benchmark ratios recorded.

## 11. Risks / open questions
- pyrefly support for PEP 695 generic `NamedTuple`: if strict mode rejects it, fall back to `class Indexed(NamedTuple, Generic[T])` (3.11+ syntax). Spike before implementing.
- L25 (`join`, priority 036) ships before this card. If it already returns plain tuples for its tuple overload, N04 switches it to `JoinPair` (compatible change: equality, unpacking and indexing are unchanged). Better: L25 creates `tuples.py` with `JoinPair` directly, following this convention.
- NamedTuple overhead may surprise users of very hot loops; documented, and `select_indexed(lambda x, i: (i, x))` (L16) stays as the plain-tuple alternative.
