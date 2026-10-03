---
id: N07
title: order / order_descending
status: todo
priority: 046
effort: S
depends_on: [F05, F06, F07, F08, F09, L07, L08, L10]
upstream:
  dotnet: OrderTests.cs (36 [Fact]/[Theory]) + OrderDescendingTests.cs (21 [Fact]/[Theory]) @ dotnet/runtime main 6f1d9331
  morelinq: n/a
pr:
---

# N07: `order` / `order_descending`

## 1. Goal
`Order()` / `OrderDescending()` (.NET 7) sort by the elements themselves, so the most common sort no longer needs `order_by(lambda x: x)`. They return `OrderedIt`, so `then_by` chains keep working. The card also adds an identity fast path that lets `order()` run at native `sorted()` speed instead of paying a Python key call per element.

## 2. Scope
**In:** `order()` and `order_descending()` on `_LinqOps` (FlpIt, FlpList, OrderedIt, Grouping), returning `OrderedIt`; identity fast path inside `OrderedIt.__iter__`.
**Out:** `Order(IComparer<T>)` / `OrderDescending(IComparer<T>)` (D3: `order_by(key)` covers custom orderings, e.g. `order_by(str.casefold)`). Culture-aware string ordering (Python compares code points). The .NET `OrderBy(...).First()` O(n) shortcut (separate optimisation for all `OrderedIt` terminals, not this card).

## 3. Detailed design
### 3.1 Signatures
```python
def order(self) -> OrderedIt[TItem]: ...
def order_descending(self) -> OrderedIt[TItem]: ...
```
| .NET overload | flpit |
|---|---|
| `Order<T>(source)` | `order()` |
| `Order<T>(source, IComparer<T>? comparer)` | omitted (D3); `comparer: null` cases equal `order()` |
| `OrderDescending<T>(source)` | `order_descending()` |
| `OrderDescending<T>(source, IComparer<T>? comparer)` | omitted (D3) |

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: full (sorts on enumeration). Short-circuit: none.
- No arguments, nothing to validate.
- Equivalent to `order_by(identity)` / `order_by_descending(identity)` in every observable respect: stable (equal elements keep source order, also for descending, as .NET), `None` sorts first ascending and last descending (existing `_NONE_ORDER_KEY` rule), re-sorted on every enumeration, one-shot sources stay one-shot.
- `then_by` / `then_by_descending` after `order()` work (`OrderedIt` criteria chain).
- Elements that are not mutually comparable (`1` and `"a"`) raise `TypeError` at enumeration (.NET: `ArgumentException` / `InvalidOperationException` from the default comparer). Same category as today's `order_by`.
- On an existing `OrderedIt`, `order()` starts a **new** primary ordering (like .NET `Order` on an `IOrderedEnumerable`), it does not append a criterion.
- Deviation (shared with `order_by`, README entry already implied): string order is ordinal (code point), not culture-sensitive.

### 3.3 Implementation sketch
```python
def _identity(x):            # module-level, compared by identity in OrderedIt
    return x

def order(self):
    return OrderedIt(self._source(), _identity, descending=False)

# OrderedIt.__iter__
def __iter__(self):
    items = list(self._iterable)
    if len(self._criteria) == 1 and self._criteria[0][0] is _identity \
            and not builtins.any(map(operator.is_, items, repeat(None))):
        items.sort(reverse=self._criteria[0][1])           # C-level, no key function
    else:
        for selector, descending in reversed(self._criteria):
            items.sort(key=partial(_none_aware_key, selector), reverse=descending)
    yield from items
```
- The `None` scan is a C-level `map(operator.is_, ...)` pass, O(n) and negligible next to the sort; `x is None` (not `==`) so objects with odd `__eq__` (e.g. arrays) are never compared to `None`.
- Fast path is observationally identical: same stability (`list.sort` is stable with or without key, `reverse=True` keeps equal elements in source order), same exceptions for incomparable elements (raised by the same `<` calls).
- Time O(n log n), memory O(n).
- `then_by` after `order()` takes the general keyed path (criteria length 2), unchanged behaviour.
- **FlpList fast path**: none beyond the shared one (`list(self._iterable)` copies the backing list, never mutates it).

### 3.4 Registry entry
```toml
[operators.order]
category = "ordering"
kind = "intermediate"
buffering = "full"
short_circuit = false
origin = "dotnet"
dotnet = "Enumerable.Order"
python_equivalent = "sorted(xs)"
variations = ["order_descending"]
since = "0.4.0"
card = "N07"
notes = "Returns OrderedIt; None first ascending; ordinal strings."
```

## 4. Tests
- **Ported** `tests/nettests/test_order.py` (from `OrderTests.cs`, 36) and `tests/nettests/test_order_descending.py` (from `OrderDescendingTests.cs`, 21):
  - `COMPARER_NOT_SUPPORTED`: Order: `SurviveBadComparerAlwaysReturnsNegative`, `SurviveBadComparerAlwaysReturnsPositive`, `FirstAndLastAreDuplicatesCustomComparer`, `OrderExtremeComparer`, `StableSort_CustomComparerAlwaysReturns0`; OrderDescending: `FirstAndLastAreDuplicatesCustomComparer`, `OrderByExtremeComparer`.
  - `OTHER` (culture collation): `CultureOrder`, `CultureOrderElementAt`.
  - Rewritten, not skipped: `RunOnce` (uses `OrdinalIgnoreCase` only incidentally; ported with default ordering and ordinal expectation, the one-shot intent is kept); `*NullPassedAsComparer` and `KeySelectorCalled` (null comparer) port as plain `order()`.
  - `Enumerable.Range(...).Shuffle()` in setup is replaced by a list shuffled with `random.Random(<seed>)`, so this card does not depend on N11.
  - `Order_FirstLast_MatchesArray` (`Assert.Same` on boxed ints): ported with a `Box` class ordered by value, asserting `is` identity of `order().first()` vs `order().to_list()[0]` (stability).
  - `SortsRandomizedEnumerableCorrectly[1_000_000]`: kept, no wall-clock assert (F01 rule).
  - Target: ≥ 80 % (48/57 ported).
- **Own unit tests** (`tests/unit/test_order.py`): fast path vs keyed path give identical output on ints, floats incl. `-0.0`/`0.0`, strings, tuples, and lists containing `None`; stability with equal-but-distinct objects (`1`, `1.0`, `True`); `order().then_by(...)` and `order_descending().then_by_descending(...)`; `OrderedIt.order()` restarts ordering; `TypeError` for mixed types raised at enumeration, not at call; FlpList not mutated.
- **Contracts**: auto via registry.
- **Typing**: `assert_type(flp.lst([3, 1]).order(), OrderedIt[int])`; `then_by` available on the result.

## 5. Differential harness
`difftest/specs/order.toml` (covers both methods): ints with duplicates, `int?` with nulls, doubles incl. `-0.0`, ASCII strings with mixed case. Probes: values, `enumeration_count`. Expected: MATCH for numeric domains; string domains MATCH only if the oracle runs with `InvariantGlobalization=true` (ordinal collation, F09 setting), otherwise `EXPECTED_DIFFERENCE` with reason "culture collation" (same applies to the existing `order_by` spec).

## 6. Benchmarks
`tests/benchmarks/test_bench_order.py`, sizes 1e3 and 1e5, random ints (seeded):
- `native`: `sorted(data)` and `sorted(data, reverse=True)`.
- `flpit-FlpIt`: `flp.it(data).order().to_list()`; `flpit-FlpList`: same on `flp.lst(data)`; plus `order_descending`.
- Target ratio ≤ 1.3× (fast path). Also record the keyed-path ratio (`[None] + data`) for information.

## 7. Docs
- Docstring (`order`): "Sorts the elements in ascending order by their own value."; `.NET: Enumerable.Order()`; Returns `OrderedIt`; Execution (deferred, full buffering, stable); `None` first; use `order_by(key)` for custom orderings (no comparer objects, D3). Example:
  ```python
  >>> flp.it([3, None, 1, 2]).order().to_list()
  [None, 1, 2, 3]
  >>> flp.it(["b", "a", "c"]).order_descending().to_list()
  ['c', 'b', 'a']
  ```
- README matrix row; Execution Characteristics table gains `order()`.
- Translation map: `sorted(xs)` / `.Order()` → `.order()`; `sorted(xs, reverse=True)` / `.OrderDescending()` → `.order_descending()`.

## 8. Expected outcomes
- `order` / `order_descending` on all four types, chaining into `then_by`.
- ~48 ported .NET tests green, 9 categorised skips; benchmark at native speed; difftest 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=order`, plus:
```bash
uv run pytest -q tests/nettests/test_order.py tests/nettests/test_order_descending.py -rs
uv run python -c "from flpit import flp; print(flp.it([3, None, 1]).order_descending().to_list())"   # [3, 1, None]
```

## 10. Definition of Done
DoD-std, plus the fast-path/keyed-path equivalence test and the benchmark showing the fast path is taken.

## 11. Risks / open questions
- Typing: `order()` cannot statically require `TItem` to be orderable without a self-type bound (`def order[T: SupportsRichComparison](self: _LinqOps[T]) -> OrderedIt[T]`). Try it in pyrefly strict; if it fights the mixin's un-annotated `self` (F05), keep it unconstrained.
- The identity fast path relies on `_identity` being the exact function object; `order_by(lambda x: x)` does not get it (intended: no lambda introspection).
