---
id: M30
title: subsets
status: todo
priority: 091
effort: S
depends_on: [F05, F06, F07, F08, F09, B09, M29]
upstream:
  dotnet: n/a
  morelinq: Subsets.cs @ morelinq master d217ab1 (reference only, D7; SubsetTest.cs 13 [Test]/[TestCase] read for behaviour)
pr:
---

# M30: `subsets`

## 1. Goal
The power set and k-combinations (`itertools` "powerset" recipe and `itertools.combinations`) as a fluent operator, with MoreLINQ's validation rules and **the same order as itertools**, so translations in either direction are exact. Shares the result-type decision and `_adopt` usage with M29.

## 2. Scope
**In:** `subsets()` (all 2^n subsets) and `subsets(subset_size)` (k-subsets) on `_LinqOps`.
**Out:** `RandomSubset` (D16 excludes `Random*`); combinations with replacement (not in MoreLINQ).

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `Subsets<T>()` | `subsets()` |
| `Subsets<T>(int subsetSize)` | `subsets(subset_size)` |

## 3. Detailed design
### 3.1 Signatures
```python
@overload
def subsets(self) -> FlpIt[FlpList[TItem]]: ...
@overload
def subsets(self, subset_size: int) -> FlpIt[FlpList[TItem]]: ...
def subsets(self, subset_size: int | _Sentinel = _SENTINEL) -> FlpIt[FlpList[TItem]]: ...
```
### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: full (source materialised at the first `next()`); subsets produced lazily. Short-circuit: n/a.
- **Order:** `subsets(k)` yields k-subsets in lexicographic order of positions, which is exactly `itertools.combinations(xs, k)` order and MoreLINQ's order (its swap algorithm was re-implemented in Python while writing this card and matched `combinations` for every n ≤ 7, k ≤ n). `subsets()` yields the empty subset, then sizes 1, 2, ..., n in that order (MoreLINQ: empty, k = 1..n-1, then the whole list), i.e. the itertools powerset recipe order. The difftest compares exact sequences.
- Elements keep source order inside each subset; equal elements are distinct positions (duplicates produce repeated subsets).
- Counts: `2**n` for `subsets()`, `comb(n, k)` for `subsets(k)`. Empty source: `subsets()` → `[[]]`; `subsets(0)` → `[[]]` for any source.
- Validation:
  - Eager: `subset_size` must be an int (`_require_index`; `None` → `ArgumentNoneError`); `subset_size < 0` → `ArgumentOutOfRangeError("subset_size")`, message `Subset size must be >= 0 (Parameter 'subset_size')`.
  - **Deferred** (cannot be known before reading the source; MoreLINQ does the same and documents the trade-off): `subset_size > len(source)` → `ArgumentOutOfRangeError("subset_size")` at the first `next()`, message `Subset size must be <= sequence.Count() (Parameter 'subset_size')` (MoreLINQ wording kept for message parity). This differs from `itertools.combinations`, which silently yields nothing; flpit follows MoreLINQ. Registry flag `deferred_validation = true`.
- Each yielded `FlpList` is new and independent (mutation-safe), as in M29.
- None elements are ordinary elements. Re-enumeration re-materialises the source.

### 3.3 Implementation sketch
```python
def subsets(self, subset_size=_SENTINEL):
    if subset_size is not _SENTINEL:
        subset_size = _require_index(subset_size, "subset_size")
        if subset_size < 0:
            raise ArgumentOutOfRangeError("subset_size", "Subset size must be >= 0")
    src = self._source()
    def _generator():
        pool = tuple(src)
        adopt = FlpList._adopt                                    # B09
        if subset_size is _SENTINEL:
            sizes = range(len(pool) + 1)
        elif subset_size > len(pool):
            raise ArgumentOutOfRangeError("subset_size", "Subset size must be <= sequence.Count()")
        else:
            sizes = (subset_size,)
        for k in sizes:
            for c in itertools.combinations(pool, k):
                yield adopt(list(c))
    return FlpIt(_FactoryIterable(_generator))
```
- C-level `combinations`; O(n) memory for the pool plus one list per result; O(n * 2^n) for the power set.
- **FlpList fast path:** none (the source is read once into `pool`).

### 3.4 Registry entry
```toml
[operators.subsets]
category = "combinatorics"
kind = "intermediate"
buffering = "full"
short_circuit = false
deferred_validation = true        # subset_size > len is only known after reading the source
origin = "morelinq"
dotnet = ""
morelinq = "MoreEnumerable.Subsets"
python_equivalent = "chain.from_iterable(combinations(xs, k) for k in range(len(xs) + 1))  # combinations(xs, k)"
contract_args = "()"
since = "0.4.0"   # adjust to the release that ships it
card = "M30"
```

## 4. Tests
- **Ported:** none (D7, 0 % by design). MoreLINQ's 13 cases (negative size, empty sequence, single element, order of all subsets, k-subsets for several n/k, size larger than the sequence, laziness) are a checklist with own equivalents. Skip categories: n/a.
- **Own unit tests** (`tests/unit/morelinq/test_subsets.py`, both `flp_type`s):
  - **Order oracle:** for n = 0..8 and every k in 0..n, `subsets(k)` equals `[list(c) for c in combinations(xs, k)]`; `subsets()` equals the powerset recipe.
  - Counts `2**n` and `comb(n, k)`; empty source; `subsets(0)` on empty and non-empty sources.
  - `subset_size = -1` → error at call time (`NoIterList` untouched); `subset_size = n + 1` → no error at call time, `ArgumentOutOfRangeError` at the first `next()` with the documented message.
  - `None` / `1.5` → `ArgumentNoneError` / `TypeError` eagerly.
  - Duplicated elements produce repeated subsets; None elements kept.
  - Independence: mutating a yielded `FlpList` does not affect later results or a re-enumeration.
- **Contracts** (auto): deferral, one-shot, FlpList not mutated; the contract runner honours `deferred_validation = true` (the oversize case is excluded from the "validated eagerly" invariant by that flag).
- **Typing** (`tests/typing/test_types_subsets.py`): both overloads → `FlpIt[FlpList[int]]` on `FlpList[int]`.

## 5. Differential harness
`difftest/specs/subsets.toml`; oracle `Operators/Subsets.cs` calling `MoreEnumerable.Subsets(source)` / `Subsets(source, size)` statically.
- Items: lengths 0..8 (≤ 256 subsets), distinct ints, duplicates, strings, ints with nulls; `subset_size ∈ {omitted, -1, 0, 1, len-1, len, len+1}`.
- Terminals: `to_list`, `first`, `count`.
- Probes: values (exact order), exception type/message/timing (`at: "call"` for -1, `at: "enumeration"` for `len + 1`), `trace`.
- Param-name mapping in messages: `subset_size ↔ subsetSize`.
- Expected: all MATCH.

## 6. Benchmarks
`tests/benchmarks/test_bench_subsets.py` (sizes are element counts: n = 12 and n = 16 for the power set; `subsets(3)` of n = 50):
- `native`: `[list(c) for k in range(len(data) + 1) for c in combinations(data, k)]` and `[list(c) for c in combinations(data, 3)]`.
- `flpit-FlpIt` / `flpit-FlpList`: `.subsets().to_list()`, `.subsets(3).to_list()`.
- Target ratio ≤ 1.5× with `_adopt` (prototype without it: 108 ms vs 7.7 ms at n = 16, which is why B09 matters).

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.Subsets([subsetSize])`; order statement (itertools order); deferred oversize error; `Execution: Deferred; buffers the source, yields one new FlpList per subset`; doctests:
  ```python
  >>> flp.it("abc").subsets().to_list()
  [[], ['a'], ['b'], ['c'], ['a', 'b'], ['a', 'c'], ['b', 'c'], ['a', 'b', 'c']]
  >>> flp.it("abcd").subsets(2).to_list()
  [['a', 'b'], ['a', 'c'], ['a', 'd'], ['b', 'c'], ['b', 'd'], ['c', 'd']]
  ```
- README: note that `subsets(k)` with `k > len` raises (MoreLINQ) where `itertools.combinations` yields nothing.
- Translation map: MoreLINQ `.Subsets()` / itertools powerset recipe → `.subsets()`; `.Subsets(k)` / `itertools.combinations(xs, k)` → `.subsets(k)`.

## 8. Expected outcomes
- Power set and k-subsets on all four types, order-identical to MoreLINQ and itertools.
- First operator using `deferred_validation = true`, exercising that registry flag in the contract suite.
- difftest spec 0 MISMATCH including the deferred exception timing.

## 9. Verification
VERIFY-std with `<op>=subsets`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_subsets.py
uv run python -c "from flpit import flp; print(flp.it('abc').subsets().count())"                  # 8
uv run python -c "from flpit import flp; q = flp.it('ab').subsets(3); print('built'); q.to_list()"  # built, then ArgumentOutOfRangeError
```

## 10. Definition of Done
DoD-std, plus: order oracle tests against `itertools.combinations`; `deferred_validation` honoured by the contract suite (extend F08's runner here if it does not read the flag yet).

## 11. Risks / open questions
- The result type follows M29; change both together if tuples are preferred.
- Message text `sequence.Count()` is .NET-flavoured; kept for exact message parity in the harness (testplan §27: message equivalence is important). Revisit if the maintainer prefers Python-flavoured messages library-wide.
