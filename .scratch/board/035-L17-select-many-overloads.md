---
id: L17
title: select_many overloads (result selector, indexed)
status: todo
priority: 035
effort: M
depends_on: [F05, F06, F07, F08, F09, L15]
upstream:
  dotnet: SelectManyTests.cs @ dotnet/runtime main 6f1d9331 (38 [Fact]/[Theory], +1 [ConditionalTheory])
  morelinq: n/a
pr:
---

# L17: `select_many` overloads (result selector, indexed)

## 1. Goal
`select_many` exists only in its simplest form. The result-selector overload is what C# query syntax `from a in xs from b in f(a) select g(a, b)` compiles to, and it is the natural way to keep the parent element while flattening (`orders.select_many(lambda o: o.lines, lambda o, l: (o.id, l.sku))`). This card adds the result selector, the indexed variant (D4), eager validation, and ports `SelectManyTests.cs` (no tests today).

## 2. Scope
**In:** `select_many(selector, result_selector=...)` and `select_many_indexed(selector, result_selector=...)` on `_LinqOps`; eager validation; full port of `SelectManyTests.cs`.
**Out:** MoreLINQ `Flatten` (recursive, M17).

## 3. Detailed design
### 3.1 Signatures
```python
TCollection = TypeVar("TCollection")

@overload
def select_many(self, selector: Callable[[TItem], Iterable[TResult]]) -> FlpIt[TResult]: ...
@overload
def select_many(self, selector: Callable[[TItem], Iterable[TCollection]],
                result_selector: Callable[[TItem, TCollection], TResult]) -> FlpIt[TResult]: ...

@overload
def select_many_indexed(self, selector: Callable[[TItem, int], Iterable[TResult]]) -> FlpIt[TResult]: ...
@overload
def select_many_indexed(self, selector: Callable[[TItem, int], Iterable[TCollection]],
                        result_selector: Callable[[TItem, TCollection], TResult]) -> FlpIt[TResult]: ...
```
`.NET` overload map: `SelectMany(Func<T,IEnumerable<R>>)` → `select_many(selector)`; `SelectMany(Func<T,int,IEnumerable<R>>)` → `select_many_indexed(selector)`; `SelectMany(collectionSelector, resultSelector)` → `select_many(selector, result_selector)`; `SelectMany(Func<T,int,IEnumerable<C>>, resultSelector)` → `select_many_indexed(selector, result_selector)`. As in .NET, the result selector receives the **outer item**, not the index.

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming (one inner iterator alive at a time). Short-circuit: stops pulling outer and inner as soon as the consumer stops.
- Validation (eager): `selector is None` → `ArgumentNoneError("selector")` (the .NET name is `collectionSelector` for the result-selector overloads; we keep `selector` as the Python keyword and use it in messages); explicit `result_selector=None` → `ArgumentNoneError("result_selector")`. **Bug fix**: today `select_many(None)` fails lazily.
- The selector is called exactly once per outer element, lazily, right before its inner sequence is consumed (`EvaluateSelectorOncePerItem`).
- The inner value must be iterable; a `str` is flattened into characters (same as .NET `string : IEnumerable<char>`). Returning `None` raises `TypeError: 'NoneType' object is not iterable` at enumeration (.NET throws `NullReferenceException`); documented.
- Index (indexed variant): 0-based over outer elements, restarts per enumeration, never overflows.
- Inner iterators that are generators are exhausted before the next outer element is pulled, so their `finally` blocks run in order (maps .NET's dispose order, `DisposeAfterEnumeration`).

### 3.3 Implementation sketch
```python
def select_many(self, selector, result_selector=_SENTINEL):
    _require_callable(selector, "selector")
    if result_selector is _SENTINEL:
        return FlpIt(_FactoryIterable(lambda: chain.from_iterable(map(selector, self))))
    _require_callable(result_selector, "result_selector")
    def _generator():
        for item in self:
            for sub in selector(item):
                yield result_selector(item, sub)
    return FlpIt(_FactoryIterable(_generator))

# indexed: same, with starmap(selector, _indexed(self)) / `for item, i in _indexed(self)`
```
- Base and indexed-without-result-selector paths are C-level (`chain.from_iterable` + `map`/`starmap`). Time O(n + Σ|inner|), memory O(1).
- **FlpList fast path**: none.

### 3.4 Registry entry
```toml
[operators.select_many]            # existing, gains overload note
python_equivalent = "itertools.chain.from_iterable(map(f, xs))"

[operators.select_many_indexed]
category = "projection"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.SelectMany(Func<TSource,int,IEnumerable<TResult>>)"
python_equivalent = "itertools.chain.from_iterable(itertools.starmap(f, zip(xs, itertools.count())))"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_select_many.py` from `SelectManyTests.cs` (38). Expected skips:
  - `OTHER` (no int overflow): `IndexOverflow`; `ThrowOverflowExceptionOnConstituentLargeCounts` ([ConditionalTheory], not counted).
  - Adapted: `DisposeAfterEnumeration` uses generator sources with `try/finally` flags instead of `DelegateIterator.dispose`; the trailing `Current` asserts are dropped. `ForcedToEnumerator*` become `not isinstance(q, Iterator)`. `ParameterizedTests` uses the F08 source fixtures instead of `CreateSources`.
  - Target: ≥ 95 % ported (only `IndexOverflow` skipped).
- **Own unit tests** (`tests/unit/test_select_many.py`): selector/result-selector `None` raise at call time; selector called once per outer element and only when reached (`select_many(f).first()` calls `f` once); `str` results flatten to characters; `None` inner raises `TypeError` lazily; result selector receives the outer item (not the index) in the indexed overload; re-enumeration re-invokes the selector.
- **Contracts**: auto via registry.
- **Typing**: `assert_type(flp.it([[1]]).select_many(lambda xs: xs), FlpIt[int])`; `assert_type(flp.it(["ab"]).select_many(lambda s: s, lambda s, c: (s, c)), FlpIt[tuple[str, str]])`; indexed variants analogous.

## 5. Differential harness
`difftest/specs/select_many.toml` and `select_many_indexed.toml`: outer sources empty, singleton, `range(1..20)`; selectors `n -> range(i, n)`, `n -> []`, `(n, i) -> repeat(n, i)`; result selectors `(a, b) -> (a, b)`; probes `selector_calls`, `elements_pulled` for `.first()`. Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_select_many.py`, sizes 1e3 / 1e5 outer elements, each inner of length 3:
- `native`: `list(chain.from_iterable(map(f, data)))` and `[g(x, y) for x in data for y in f(x)]`
- `flpit-FlpIt` / `flpit-FlpList`: `.select_many(f).to_list()` and `.select_many(f, g).to_list()`.
- Target ratio ≤ 1.5×.

## 7. Docs
- Docstring: `.NET: Enumerable.SelectMany` (all four overloads listed with their Python form); laziness of the selector; string flattening note; `Execution: Deferred, streaming`.
- Doctests:
  ```python
  >>> flp.it([[1, 2], [3]]).select_many(lambda xs: xs, lambda xs, x: (len(xs), x)).to_list()
  [(2, 1), (2, 2), (1, 3)]
  >>> flp.it(["ab", "c"]).select_many_indexed(lambda s, i: s * (i + 1)).to_list()
  ['a', 'b', 'c', 'c']
  ```
- Translation map: `[g(x, y) for x in xs for y in f(x)]` / `from x in xs from y in f(x) select g(x, y)` → `.select_many(f, g)`.

## 8. Expected outcomes
- Four `SelectMany` overloads covered by two Python methods with precise typing.
- ~37 ported tests green.

## 9. Verification
VERIFY-std with `<op>=select_many` and `<op>=select_many_indexed`, plus:
```bash
uv run pytest -q tests/nettests/test_select_many.py -rs | tail -3
uv run python -c "from flpit import flp; print(flp.it([1, 2]).select_many(lambda n: range(n), lambda n, k: n * 10 + k).to_list())"   # [10, 20, 21]
```

## 10. Definition of Done
DoD-std, plus the pyrefly overload resolution for the two-argument form is checked in `tests/typing/test_types_select_many.py`.

## 11. Risks / open questions
- pyrefly must infer `TCollection` from the selector's return type when `result_selector` is a lambda; if inference fails, the typing test documents the needed annotation and the README shows a typed example.
