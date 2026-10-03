---
id: B04
title: of_type
status: todo
priority: 015
effort: S
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: OfTypeTests.cs @ dotnet/runtime main 6f1d9331 (26 [Fact]/[Theory])
  morelinq: n/a
pr:
---

# B04: `of_type` (backfill)

## 1. Goal
`of_type` filters by `isinstance`, but `OfTypeTests.cs` shows a semantic gap: .NET `OfType<T>` **never yields `null`** (the `is T` test is false for `null`), even for `OfType<object>` or `OfType<int?>` (`AllElementsOfNullableTypeNullsSkipped`, `Count`: 3 of 6 for `OfType<object>` over 3 nulls). Today `flp.it([1, None]).of_type(object)` yields `[1, None]`. Target validation is also lazy (`of_type(list[int])` fails inside the loop). This card aligns the `None` rule with .NET, shares the eager validator with `cast` (B03), and ports the tests.

## 2. Scope
**In:** `of_type(target_type)` on `_LinqOps`; `None` filtering; eager validation via `_require_isinstance_target` (from B03, or introduced here if B04 lands first); port of `OfTypeTests.cs`.
**Out:** conversions; `try_get_non_enumerated_count` assertions inside the `Count` test (N10).

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def of_type(self, target_type: type[TResult]) -> FlpIt[TResult]: ...
@overload
def of_type(self, target_type: types.UnionType | tuple[type[Any] | types.UnionType, ...]) -> FlpIt[Any]: ...
```
.NET `OfType<TResult>(IEnumerable)` maps 1:1 (type argument → `target_type` argument; `T?` → `T | None`).

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: streaming. Short-circuit: no.
- Yields `item` iff `item is not None and isinstance(item, target_type)`. **`None` is never yielded**, matching .NET; so `of_type(object)` is the idiomatic "drop `None`" filter and `of_type(int | None)` equals `of_type(int)`. Degenerate `of_type(type(None))` yields nothing (documented).
- This is a behaviour change from today for `object`, `T | None` and `NoneType` targets: CHANGELOG "Changed".
- Validation (eager): `None` → `ArgumentNoneError("target_type")`; non-`isinstance`-able targets (`list[int]`, `typing.Any`, non-runtime protocols) → `TypeError` at call time (same message family as `cast`).
- Filtering is by type, never by equality (`OfType_Contains_FiltersByTypeEvenIfEqual`).
- `bool` is an `int`; `int` is not a `float` (`of_type(float)` over ints is empty, as .NET `OfType<double>` over `long`).
- Live source: re-enumeration sees mutations (`MultipleIterations`).

### 3.3 Implementation sketch
```python
def of_type(self, target_type):
    _require_isinstance_target(target_type, "target_type")
    if target_type is object:
        pred = _is_not_none                                     # cheaper than isinstance
    else:
        pred = lambda x: x is not None and isinstance(x, target_type)
    def _generator():
        return filter(pred, self)                              # C-level loop
    return FlpIt(_FactoryIterable(_generator))
```
- O(n) time, O(1) memory. `filter` keeps it streaming and lazy (the factory is only called on `__iter__`).
- **FlpList:** no override.

### 3.4 Registry entry
```toml
[operators.of_type]
category = "filtering"
kind = "intermediate"
buffering = "streaming"
short_circuit = false
dotnet = "Enumerable.OfType"
python_equivalent = "(x for x in xs if x is not None and isinstance(x, T))"
since = "0.2.0"          # pre-registry operator
```

## 4. Tests
- **Ported** `tests/nettests/test_of_type.py` from `OfTypeTests.cs` (26):
  - Ported (19): `SameResultsRepeatCallsIntQuery`, `SameResultsRepeatCallsStringQuery`, `EmptySource`, `HeterogenousSourceNoAppropriateElements`, `HeterogenousSourceOnlyFirstOfType`, `AllElementsOfNullableTypeNullsSkipped` (`of_type(int | None)`), `HeterogenousSourceSomeOfType` (`3.5m` → `Decimal("3.5")`), `RunOnce`, `IntFromNullableInt`, `IntFromNullableIntWithNulls`, `NullableDecimalFromString`, `LongFromDouble` (`of_type(float)` over ints), `ToArray`, `ToList`, `Count` (the three `TryGetNonEnumeratedCount` asserts go behind `requires_op("try_get_non_enumerated_count")`), `First_Last_ElementAt` (`*OrDefault` parts need L07/L08/L10, `requires_op`; .NET `default(long)` is `0`, so the port passes `default=0`), `OfTypeSelect`, `MultipleIterations`, `OfType_Contains_FiltersByTypeEvenIfEqual` (needs L06 `contains`).
  - Adapted (1): `ForcedToEnumeratorDoesntEnumerate` → query is not an `Iterator`.
  - Skips: `NO_VALUE_TYPES` 1 (`LongSequenceFromIntSource`: no `int`/`long` split); `INTERNAL_OPTIMIZATION` 3 (`ValueType_ReturnsOriginal`, `NullableValueType_ReturnsNewEnumerable`, `ReferenceType_ReturnsNewEnumerable`: object identity of the result); `NO_SPAN_OR_ARRAY` 1 (`MultiDimArray_OfType_Succeeds`); `OTHER` 1 (`NullSource`).
  - Target: 20/26 ≈ 77 % ported.
- **Own unit tests** (`tests/unit/test_of_type.py`):
  - `of_type(object)`, `of_type(int | None)`, `of_type(type(None))` never yield `None`.
  - `of_type((int, str))` keeps both; `of_type(int)` keeps `True` (existing `test_of_type_uses_python_isinstance_semantics` stays green).
  - Eager failures: `of_type(list[int])`, `of_type(None)` on a `NoIterList` source.
  - Subclass instances pass (`of_type(Animal)` keeps `Dog`).
- **Contracts** (auto).
- **Typing**: `assert_type(flp.it(objs).of_type(str), FlpIt[str])`; union target → `FlpIt[Any]`.

## 5. Differential harness
`difftest/specs/of_type.toml`: object-typed sources mixing `int`, `str`, `double`, `decimal`, `null`; targets `{int, int?, string, object, double}` mapped as in §3.1. Expected: all MATCH (the `None` rule now mirrors .NET). `bool` values are excluded from the domain (`bool` is an `int` in Python only; documented, not compared).

## 6. Benchmarks
`tests/benchmarks/test_bench_of_type.py`, sizes 1e3 and 1e5, 50 % ints / 50 % strings:
- `native`: `[x for x in data if isinstance(x, int)]`.
- `flpit-FlpIt`, `flpit-FlpList`: `.of_type(int).to_list()`; plus `of_type(object)` vs `[x for x in data if x is not None]`.
- Target ≤ 1.5× (today ≈ 1.1×; the extra `is not None` test must not regress it, which is why `filter` with a prebuilt predicate is used).

## 7. Docs
- Docstring: `.NET: Enumerable.OfType<TResult>()`; never yields `None`; eager target validation; "see also `cast` (raises instead of filtering)". Doctest: `flp.it([1, "a", None, 2.5, True]).of_type(int).to_list()` → `[1, True]`, and `flp.it([1, None, "a"]).of_type(object).to_list()` → `[1, 'a']`.
- README "Intentional Semantic Deviations": `bool` is an `int` for `of_type`/`cast`. (The `None` rule is no longer a deviation.)
- Translation map: `.OfType<T>()` → `.of_type(T)`; `[x for x in xs if isinstance(x, T)]` → `.of_type(T)`; `.Where(x => x != null)` → `.of_type(object)`.

## 8. Expected outcomes
- `of_type` matches .NET on `None`; invalid targets fail at the call site.
- 20 ported .NET tests green (some activate only when L06/L07/L08/L10 land).

## 9. Verification
VERIFY-std with `<op>=of_type`, plus:
```bash
uv run pytest -q tests/nettests/test_of_type.py -rs
uv run python -c "from flpit import flp; print(flp.it([1, None, 'a']).of_type(object).to_list())"   # [1, 'a']
```

## 10. Definition of Done
DoD-std, plus: CHANGELOG "Changed" entry for the `None` rule; `_require_isinstance_target` shared with B03 (single implementation).

## 11. Risks / open questions
- Behaviour change for code relying on `of_type(object)` keeping `None`. Judged unlikely and it aligns with .NET; called out in CHANGELOG.
- `of_type(type(None))` is now always empty; alternative (special-case it to yield `None`s) rejected as a .NET-less corner case. Open to revisit if a user asks.
