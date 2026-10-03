---
id: L18
title: to_dictionary
status: todo
priority: 036
effort: M
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: ToDictionaryTests.cs @ dotnet/runtime main 6f1d9331 (28 [Fact]/[Theory])
  morelinq: n/a
pr:
---

# L18: `to_dictionary`

## 1. Goal
Materialising a keyed index (`users.to_dictionary(lambda u: u.id)`) is one of the most common endpoints of a LINQ pipeline. Python's `{k(x): x for x in xs}` silently overwrites duplicates, which hides data bugs; `ToDictionary` fails loudly. Per D17 the result is a plain `dict` and duplicates raise `DuplicateKeyError(ValueError)`.

## 2. Scope
**In:** `to_dictionary()` (source of pairs), `to_dictionary(key_selector)`, `to_dictionary(key_selector, element_selector)` on `_LinqOps`; `DuplicateKeyError` (if F05 did not add it); a FlpList fast path for the pairs overload.
**Out:** comparer overloads (D3: put the normalisation into `key_selector`); a frozen/read-only dict (D17 says plain `dict`).

## 3. Detailed design
### 3.1 Signatures
```python
TValue = TypeVar("TValue"); TElement = TypeVar("TElement")

@overload
def to_dictionary(self: _LinqOps[tuple[TKey, TValue]]) -> dict[TKey, TValue]: ...
@overload
def to_dictionary(self, key_selector: Callable[[TItem], TKey]) -> dict[TKey, TItem]: ...
@overload
def to_dictionary(self, key_selector: Callable[[TItem], TKey],
                  element_selector: Callable[[TItem], TElement]) -> dict[TKey, TElement]: ...
```
`.NET` overload map (8 overloads): `ToDictionary(IEnumerable<KeyValuePair<K,V>>)` and `ToDictionary(IEnumerable<(K,V)>)` → `to_dictionary()` over 2-tuples (pass `mapping.items()` for a dict); `ToDictionary(keySelector)` → `to_dictionary(key_selector)`; `ToDictionary(keySelector, elementSelector)` → `to_dictionary(key_selector, element_selector)`; the four `IEqualityComparer` overloads are omitted (D3).

### 3.2 Semantics
- Kind: terminal. Buffering: full. Short-circuit: stops at the first duplicate key (the rest of the source is not pulled, as in .NET where `Dictionary.Add` throws immediately).
- Validation (eager, before touching the source): explicit `key_selector=None` → `ArgumentNoneError("key_selector")`; `element_selector=None` → `ArgumentNoneError("element_selector")`. Passing `element_selector` without `key_selector` is a `TypeError` (no such .NET overload).
- Per element, call order is `key_selector(item)`, then `element_selector(item)`, then insertion; a duplicate is therefore detected after the element selector ran for that item (same as `d.Add(key(x), elem(x))`).
- Duplicate key → `DuplicateKeyError(key)` with message `An item with the same key has already been added. Key: {key!r}` and attribute `.key`. Equality is Python `__eq__`/`__hash__` (`1`, `1.0`, `True` collide: documented with the shared equality deviation of L06).
- Pairs overload: each element is unpacked as `key, value = element`, so any 2-item iterable works (`tuple`, `list`, `NamedTuple`); a wrong arity raises Python's `ValueError` from unpacking. Iterating a `dict` yields keys, so `flp.it(d).to_dictionary()` fails; the docstring points to `flp.it(d.items())`.
- **`None` keys (deviation, proposed)**: .NET throws `ArgumentNullException("key")` because `Dictionary<TKey,_>` forbids null keys; that is a container restriction, not a LINQ rule. A Python `dict` accepts `None`, so flpit **allows `None` keys**. README § Intentional Semantic Deviations gets the entry; the difftest classifies it `EXPECTED_DIFFERENCE`. Alternative (rejected): mirror .NET with `ArgumentNoneError("key")`, which would make `to_dictionary` stricter than `dict(...)` for no Python benefit.
- Unhashable key → `TypeError` from `dict` at that element.
- The result is a new `dict` in source insertion order; the source is never aliased (`ToDictionary_AlwaysCreateACopy`).

### 3.3 Implementation sketch
```python
def to_dictionary(self, key_selector=_SENTINEL, element_selector=_SENTINEL):
    ...validation...
    d = {}; n = 0
    if key_selector is _SENTINEL:
        for k, v in self:
            d[k] = v
            if len(d) == n: raise DuplicateKeyError(k)
            n += 1
    else:
        for item in self:
            k = key_selector(item)
            v = item if element_selector is _SENTINEL else element_selector(item)
            d[k] = v
            if len(d) == n: raise DuplicateKeyError(k)
            n += 1
    return d
```
- One hash operation per element (the `len` check replaces a separate `k in d` probe). O(n) time, O(n) memory.
- **FlpList fast path (pairs overload)**: `d = dict(data)`; if `len(d) != len(data)`, fall back to the loop above to find and raise on the first duplicate. Iterating a list has no side effects and no callbacks run, so results and exceptions are identical; the gain (C-level `dict()`) is recorded in the PR. Not applied to arbitrary iterables, because pre-materialising would pull elements past a duplicate (observable on generators, fatal on infinite ones).

### 3.4 Registry entry
```toml
[operators.to_dictionary]
category = "conversion"
kind = "terminal"
buffering = "full"
short_circuit = true          # stops at the first duplicate
dotnet = "Enumerable.ToDictionary"
python_equivalent = "{k(x): x for x in xs}  (but raises on duplicate keys)"
since = "0.3.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_to_dictionary.py` from `ToDictionaryTests.cs` (28). `KeyValuePair` and value-tuple sources both become lists of 2-tuples; `RunToDictionaryOnAllCollectionTypes` maps to the F08 source fixtures. Expected skips:
  - `COMPARER_NOT_SUPPORTED`: `ToDictionary_PassCustomComparer`, `_UseDefaultComparerOnNull`, `_UseDefaultComparer` (assert `.Comparer` identity), `SeveralElementsCustomComparerer`, `ThrowsOnNullKeyCustomComparer`, `ThrowsOnNullKeyCustomComparerValueSelector`.
  - `OTHER` (`None` keys allowed, deviation): `ToDictionary_ThrowWhenKeySelectorReturnNull`, `ThrowsOnNullKey`, `ThrowsOnNullKeyValueSelector`; own tests assert acceptance instead.
  - Rewritten without comparer (intent kept): `ThrowsOnDuplicateKeys`, `EmptySource`, `OneElementNullComparer`, `NullCoalescedKeySelector`.
  - Target: ≥ 65 % ported (19/28).
- **Own unit tests** (`tests/unit/test_to_dictionary.py`): duplicate stops enumeration (a generator source records that later elements were not pulled); `DuplicateKeyError` is a `ValueError` with `.key`; call order key → element → insert; `None` keys accepted; unhashable key `TypeError`; `flp.it(d.items()).to_dictionary() == d` and `is not d`; FlpList fast path and generic path raise the same error for the same input.
- **Contracts**: auto (terminal; FlpList not mutated).
- **Typing**: `assert_type(flp.it([("a", 1)]).to_dictionary(), dict[str, int])`; `assert_type(flp.lst(["x"]).to_dictionary(len), dict[int, str])`; `assert_type(flp.it(["x"]).to_dictionary(len, str.upper), dict[int, str])`.

## 5. Differential harness
`difftest/specs/to_dictionary.toml`: sources unique ints, ints with a duplicate at position 0 / middle / last, pairs, strings; selectors identity, `x % 3`, `str`; probes `result` (compared as ordered key/value list), `exception_type`, `elements_pulled` on duplicate. `None` key cases are `EXPECTED_DIFFERENCE: None keys allowed (README deviation)`.

## 6. Benchmarks
`tests/benchmarks/test_bench_to_dictionary.py`, sizes 1e3 / 1e5, unique int keys:
- `native`: `{k(x): x for x in data}` and `dict(pairs)`
- `flpit-FlpIt` / `flpit-FlpList`: `.to_dictionary(k)` and `.to_dictionary()`.
- Target ratio ≤ 1.5× (the duplicate check is the extra cost); FlpList pairs fast path target ≤ 1.1×.

## 7. Docs
- Docstring: `.NET: Enumerable.ToDictionary`; overload table; duplicate rule and message; `None`-key deviation; `Execution: Immediate, full buffering, stops at first duplicate`.
- Doctests:
  ```python
  >>> flp.it(["apple", "banana"]).to_dictionary(len)
  {5: 'apple', 6: 'banana'}
  >>> flp.it([("a", 1), ("b", 2)]).to_dictionary()
  {'a': 1, 'b': 2}
  >>> flp.it(["a", "b", "a"]).to_dictionary(lambda s: s)  # doctest: +IGNORE_EXCEPTION_DETAIL
  Traceback (most recent call last):
  DuplicateKeyError: An item with the same key has already been added. Key: 'a'
  ```
- Translation map: `{k(x): x for x in xs}` / `dict(pairs)` / `.ToDictionary(k)` → `.to_dictionary(k)`.

## 8. Expected outcomes
- `to_dictionary` with three Python forms covering the four non-comparer .NET overloads; `DuplicateKeyError` exported from `flpit`.
- ~19 ported tests plus own tests green; README deviation for `None` keys.

## 9. Verification
VERIFY-std with `<op>=to_dictionary`, plus:
```bash
uv run pytest -q tests/nettests/test_to_dictionary.py -rs | tail -3
uv run python -c "from flpit import flp; print(flp.it([None, 1]).to_dictionary(lambda x: x))"   # {None: None, 1: 1}
```

## 10. Definition of Done
DoD-std, plus the `None`-key deviation entry in README and the difftest spec reason.

## 11. Risks / open questions
- **Decision needed from the maintainer**: `None` keys allowed (proposed) vs mirroring .NET.
- The self-typed overload (`self: _LinqOps[tuple[K, V]]`) must resolve in pyrefly strict; fallback is a separate method name `to_dictionary_from_pairs` (not preferred, recorded in the PR if needed).
