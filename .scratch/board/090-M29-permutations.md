---
id: M29
title: permutations
status: todo
priority: 090
effort: S
depends_on: [F05, F06, F07, F08, F09, B09]
upstream:
  dotnet: n/a
  morelinq: Permutations.cs @ morelinq master d217ab1 (reference only, D7; PermutationsTest.cs 9 [Test] read for behaviour)
pr:
---

# M29: `permutations`

## 1. Goal
All orderings of a small sequence (test-case generation, brute-force search, puzzles) are one `itertools.permutations` call in Python, but that breaks the fluent chain and yields tuples rather than flpit collections. `permutations()` exposes MoreLINQ's operator with **the same order as both MoreLINQ and itertools**, so the translation is exact. Niche (Phase 4) and cheap.

## 2. Scope
**In:** `permutations()` on `_LinqOps`.
**Out:** an `r` parameter (`itertools.permutations(xs, r)`): MoreLINQ has none; add only on demand. Distinct-only permutations of multisets: neither MoreLINQ nor itertools offer it (compose `permutations().distinct_by(tuple)`).

**MoreLINQ overload mapping**
| MoreLINQ | flpit |
|---|---|
| `Permutations<T>()` → `IEnumerable<IList<T>>` | `permutations()` → `FlpIt[FlpList[T]]` (lists like `chunk`/`window`, board convention for MoreLINQ `IList<T>` results) |

## 3. Detailed design
### 3.1 Signatures
```python
def permutations(self) -> FlpIt[FlpList[TItem]]: ...
```
### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: full (the source is materialised at the first `next()`, O(n)); each permutation is produced lazily. Short-circuit: n/a, `permutations().first()` costs O(n).
- **Order (answers the difftest question):** permutations are produced in lexicographic order of element **positions**, starting with the source order itself. This is exactly `itertools.permutations` order and exactly MoreLINQ's order (its algorithm is a next-permutation over an index array starting at the identity). Verified while writing this card by re-implementing MoreLINQ's index algorithm in Python and comparing it with `itertools.permutations` for n = 0..6, including inputs with duplicates. Hence the difftest compares **exact sequences**; no set normalisation is needed (testplan §2.3 forbids sorting an ordered result anyway).
- Count: always `n!` results; equal elements are treated as distinct positions (duplicates produce repeated permutations, as in both references).
- Empty source → exactly one permutation, the empty `FlpList` (both references agree). Singleton → one.
- Each yielded `FlpList` is a **new, independent** object: mutating one never affects later ones or a re-enumeration.
- No size limit. MoreLINQ yields the first permutation and then throws `OverflowException("Too many permutations.")` for more than 20 elements (its counter is a `ulong` factorial). Python has no overflow; flpit keeps going (21! is not enumerable in practice). README deviation; difftest EXPECTED_DIFFERENCE.
- None elements are ordinary elements. No validation arguments (no parameters).
- Re-enumeration re-materialises the source.

### 3.3 Implementation sketch
```python
def permutations(self):
    src = self._source()
    def _generator():
        pool = tuple(src)
        adopt = FlpList._adopt                       # B09 no-copy private constructor
        for p in itertools.permutations(pool):
            yield adopt(list(p))
    return FlpIt(_FactoryIterable(_generator))
```
- `itertools.permutations` is C-level; O(n) memory plus one list per result; O(n * n!) total time.
- `FlpList(...)` costs ~1.5 µs per instance (prototype: 8! permutations as `FlpList` 65 ms vs 4.8 ms as plain lists), so `_adopt` (B09) is required; without B09 the card can land with `FlpList(p)` and a documented ratio miss.
- **FlpList fast path:** none (the receiver is only read once into `pool`).

### 3.4 Registry entry
```toml
[operators.permutations]
category = "combinatorics"
kind = "intermediate"
buffering = "full"
short_circuit = false
origin = "morelinq"
dotnet = ""
morelinq = "MoreEnumerable.Permutations"
python_equivalent = "map(list, itertools.permutations(xs))"
contract_args = "()"
since = "0.4.0"   # adjust to the release that ships it
card = "M29"
notes = "same order as itertools and MoreLINQ; no 20-element limit"
```

## 4. Tests
- **Ported:** none (D7, 0 % by design). MoreLINQ's 9 cases (cardinality 0 to 4, results unique for distinct input, laziness, independent lists) are a checklist with own equivalents. Skip categories: n/a.
- **Own unit tests** (`tests/unit/morelinq/test_permutations.py`, both `flp_type`s):
  - n = 0 → `[[]]`; n = 1 → `[[x]]`; n = 3 → the 6 permutations in the order shown in §7; n = 5 → 120 results, all distinct for distinct input.
  - **Order oracle:** for n = 0..7, `[list(p) for p in itertools.permutations(xs)]` equals the result (this pins the shared order).
  - Duplicates: `[1, 1, 2]` yields 6 results with repeats, in itertools order.
  - Result type is `FlpList`; mutating a yielded list (`add`) does not change the next one or a re-enumeration.
  - Deferral (`NoIterList`); the source is read once per enumeration (counting source); `permutations().first()` equals the source order.
  - 21-element source: `take(2)` works (deviation pinned).
- **Contracts** (auto): deferral, one-shot, FlpList not mutated.
- **Typing** (`tests/typing/test_types_permutations.py`): `assert_type(flp.it([1]).permutations(), FlpIt[FlpList[int]])`.

## 5. Differential harness
`difftest/specs/permutations.toml`; oracle `Operators/Permutations.cs` calling `MoreEnumerable.Permutations(source)` statically; each `IList<T>` serialises as a JSON array.
- Items: lengths 0..6 (720 results max per case), distinct ints, ints with duplicates, strings, ints with nulls.
- Terminals: `to_list`, `first`, `take(k)`, `count`.
- Probes: values (exact order), `trace` (source fully read before the first result).
- Expected: MATCH. A 21-element case with `take(2)`: `EXPECTED_DIFFERENCE` (reason: "OTHER: MoreLINQ OverflowException above 20 elements").
- The order claim was checked against master's source; if the pinned NuGet release implements permutations differently, the spec records the difference as a MISMATCH to investigate, never as a normalisation.

## 6. Benchmarks
`tests/benchmarks/test_bench_permutations.py`: sizes are element counts, not 1e3/1e5 (factorial output): n = 6 (720) and n = 8 (40,320):
- `native`: `[list(p) for p in itertools.permutations(data)]`
- `flpit-FlpIt` / `flpit-FlpList`: `.permutations().to_list()`.
- Target ratio ≤ 1.5× with `_adopt` (dominated by per-result object creation).

## 7. Docs
- Docstring: summary; `MoreLINQ: MoreEnumerable.Permutations()`; order statement ("same order as `itertools.permutations`"); n! warning; `Execution: Deferred; buffers the source, yields one new FlpList per permutation`; doctest:
  ```python
  >>> flp.it([1, 2, 3]).permutations().to_list()
  [[1, 2, 3], [1, 3, 2], [2, 1, 3], [2, 3, 1], [3, 1, 2], [3, 2, 1]]
  >>> flp.it([]).permutations().to_list()
  [[]]
  ```
- README deviation: no 20-element limit.
- Translation map: MoreLINQ `.Permutations()` / Python `itertools.permutations(xs)` → `.permutations()`.

## 8. Expected outcomes
- `permutations()` on all four types, order-identical to both references, documented as such.
- difftest spec with exact comparison, 0 MISMATCH.

## 9. Verification
VERIFY-std with `<op>=permutations`, plus:
```bash
uv run pytest -q tests/unit/morelinq/test_permutations.py
uv run python -c "from flpit import flp; print(flp.it([1, 2, 3]).permutations().to_list())"   # [[1, 2, 3], [1, 3, 2], [2, 1, 3], [2, 3, 1], [3, 1, 2], [3, 2, 1]]
uv run python -c "from flpit import flp; print(flp.it('abcd').permutations().count())"          # 24
```

## 10. Definition of Done
DoD-std, plus: the order oracle test against `itertools.permutations`; README deviation entry.

## 11. Risks / open questions
- Result element type: `FlpList` follows the board convention (B06, M02, M07, M08), at a per-result construction cost that B09's `_adopt` mitigates. Tuples (itertools' choice) would be faster and hashable; if the maintainer prefers tuples for combinatorics, change M29 and M30 together.
- Depends on B09 only for `_adopt`; if B09 has not landed, drop the dependency and accept the slower constructor.
