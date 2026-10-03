---
id: N11
title: shuffle
status: todo
priority: 055
effort: S
depends_on: [F05, F06, F07, F08, F09, L07, L08, L10]
upstream:
  dotnet: ShuffleTests.cs @ dotnet/runtime main 6f1d9331 (13 [Fact]/[Theory])
  morelinq: Shuffle.cs (reference only, D7; superseded by the .NET 10 operator)
pr:
---

# N11: `shuffle`

## 1. Goal
`Shuffle()` (.NET 10) returns the elements in random order as a deferred query, without mutating the source, so `flp.lst(cards).shuffle().take(5)` reads like the intent. Python's `random.shuffle` works in place on a list and returns `None`, which does not compose. This card adds the operator with an optional, Python-specific `rng=` keyword for reproducible results in tests and simulations.

## 2. Scope
**In:** `shuffle(*, rng=None)` on `_LinqOps`; count provider (N10).
**Out:** the .NET `Shuffle().Take(k)` fusion (reservoir sampling without a full shuffle; same distribution, so not observable except for speed; possible follow-up using `rng.sample`); cryptographic randomness by default (pass `rng=random.SystemRandom()`); a `seed=` int parameter (a `random.Random(seed)` is explicit and composable).

## 3. Detailed design
### 3.1 Signatures
```python
def shuffle(self, *, rng: random.Random | None = None) -> FlpIt[TItem]: ...
```
| .NET | flpit |
|---|---|
| `Shuffle<TSource>(source)` | `shuffle()` |
| (no overload; uses `Random.Shared`) | `shuffle(rng=random.Random(seed))`: **Python extension** |

### 3.2 Semantics
- Kind: intermediate, deferred. Buffering: full (the whole source is copied into a fresh list on the first `next()`). Short-circuit: none (`shuffle().take(1)` still consumes everything).
- Validation (eager): `rng` must be `None` or an object with a callable `shuffle` method (`random.Random`, `random.SystemRandom`, subclasses); otherwise `TypeError("rng must be a random.Random instance or None")`.
- Randomness: `rng=None` uses the `random` module's shared generator (`random.shuffle`), the analogue of .NET `Random.Shared`; so `random.seed(...)` affects it. With `rng`, that generator is used **statefully**: each enumeration draws new numbers from it, so two enumerations of the same query give (almost surely) different orders, but the sequence of orders is reproducible. For one fixed order, create a fresh `random.Random(seed)` per query or materialise once with `to_list()`.
- **Every enumeration reshuffles** (as .NET: the iterator shuffles on its first `MoveNext`).
- The source is never mutated (a `FlpList` receiver is copied; `random.shuffle` runs on the copy).
- Output is a permutation of the input: same multiset, `None` and duplicate elements kept; elements are never compared or hashed.
- Empty source → empty, the generator is not consumed.
- One-shot sources stay one-shot (second enumeration empty).
- Not suitable for security purposes unless `rng=random.SystemRandom()` (docstring note).
- **Deviation** (README § Intentional Semantic Deviations): the `rng` keyword is a Python extension; results are never comparable with .NET element by element (different generators).

### 3.3 Implementation sketch
```python
def shuffle(self, *, rng=None):
    if rng is not None and not callable(getattr(rng, "shuffle", None)):
        raise TypeError("rng must be a random.Random instance or None")
    shuffle_in_place = random.shuffle if rng is None else rng.shuffle
    src = self._source()
    def _generator():
        buf = list(src)
        shuffle_in_place(buf)
        yield from buf
    return FlpIt(_FactoryIterable(_generator, count=lambda: _cheap_count(src)))
```
- `random.shuffle` is Fisher-Yates in Python code (~0.3 µs/element on 3.12); `list(src)` is C. Time O(n), memory O(n).
- `random.shuffle` is looked up at call time of `shuffle()`, so monkeypatching `random.shuffle` in tests works only before building the query; tests use `rng=` instead.
- **FlpList fast path**: none (a copy is required anyway; `list(data)` is the fastest copy).
- Count provider: source count (as .NET `ShuffleIterator.GetCount`).

### 3.4 Registry entry
```toml
[operators.shuffle]
category = "ordering"
kind = "intermediate"
buffering = "full"
short_circuit = false
origin = "dotnet"
dotnet = "Enumerable.Shuffle"
morelinq = "MoreEnumerable.Shuffle"
python_equivalent = "buf = list(xs); random.shuffle(buf)"
since = "0.4.0"
card = "N11"
notes = "rng= keyword (random.Random) is a Python extension; reshuffles on every enumeration."
```

## 4. Tests
- **Ported** `tests/nettests/test_shuffle.py` from `ShuffleTests.cs` (13 cases). All tests are statistical or structural, so no seeding is needed:
  - `InvalidArguments` → `flp.it(None)` raises `SourceNoneError`.
  - `Count_ExpectedCountReturned`, `Enumeration_/ToArray_/ToList_AllElementsReturned` (lengths 0, 1, 2, 3, 100, over the F08 source variants): count and sorted-equality checks.
  - `*_ElementsAreRandomized` (1000 elements, two shuffles differ, including after `take(length ± 1)`): ported as is (collision probability ~1/1000!).
  - `ForcedToEnumeratorDoesntEnumerate` → `not isinstance(query, Iterator)`.
  - `First_Last_GetElement_Invalid_ExpectedExceptions` / `_Valid_ExpectedElements` / `_ProduceRandomElements` (retry up to 10 times): ported with `first`, `last`, `element_at`, `first_or_default`, `last_or_default`, `element_at_or_default` (L07, L08, L10).
  - `LONG_RUNNING`: `ValidateShuffleTakeRandomDistribution` (upstream `[OuterLoop]`, 3 modes × 3 sources × 100k shuffles); replaced in the default run by the own chi-square test below.
  - Target: 12/13 (92 %).
- **Own unit tests** (`tests/unit/test_shuffle.py`):
  - Determinism: `flp.it(xs).shuffle(rng=random.Random(42)).to_list()` equals `random.Random(42).shuffle` on a copy; two queries with fresh `Random(42)` agree; two enumerations of one query with one rng differ (stateful).
  - Source never mutated (FlpList backing list and a plain list unchanged after enumeration).
  - Deferral (`NoIterList`), one-shot generator, `None`/duplicate elements, incomparable elements (`object()`) never compared.
  - `rng="x"` / `rng=42` → `TypeError` at call; `random.SystemRandom()` accepted.
  - Uniformity: first position over 10 elements, 20k trials with `Random(1234)`, every value within ±15 % of 2000 (deterministic seed, so not flaky).
  - `try_get_non_enumerated_count()` equals the source count without enumerating.
- **Contracts**: auto via registry (deferral, full buffering, FlpList not mutated).
- **Typing**: `assert_type(flp.lst([1]).shuffle(), FlpIt[int])`; `shuffle(rng=random.Random(1))` accepted; `shuffle(1)` rejected (keyword-only).

## 5. Differential harness
`difftest/specs/shuffle.toml`: sources empty, singleton, ints with duplicates, strings with nulls. Element order is `UNCOMPARABLE` by nature (reason: "random order; different generators"). Structural probes compared and expected to MATCH: element count, sorted multiset, `elements_pulled` (full source before the first element), exception type for a null source.

## 6. Benchmarks
`tests/benchmarks/test_bench_shuffle.py`, sizes 1e3 and 1e5, `rng = random.Random(0)` recreated per round:
- `native`: `buf = list(data); rng.shuffle(buf)`.
- `flpit-FlpIt`: `flp.it(data).shuffle(rng=rng).to_list()`; `flpit-FlpList`: same on `flp.lst(data)`.
- Target ratio ≤ 1.3× (Fisher-Yates dominates).

## 7. Docs
- Docstring: "Returns the elements in random order (deferred; reshuffles on each enumeration)."; `.NET: Enumerable.Shuffle()`; Args (`rng`: Python extension, stateful use explained); Raises; Execution (deferred, full buffering, source not mutated); security note. Example:
  ```python
  >>> sorted(flp.it(range(5)).shuffle())
  [0, 1, 2, 3, 4]
  >>> import random
  >>> flp.it(range(5)).shuffle(rng=random.Random(42)).to_list()
  [3, 1, 2, 4, 0]
  ```
- README matrix row; deviation entry (`rng` extension).
- Translation map: `random.shuffle(lst)` (in place) / `random.sample(xs, len(xs))` / `.Shuffle()` → `.shuffle()`; MoreLINQ `Shuffle(rand)` → `.shuffle(rng=...)`.

## 8. Expected outcomes
- `shuffle` on all four types, composable and non-mutating, reproducible with `rng=`.
- 12 ported .NET tests green, own statistical tests deterministic, benchmark recorded, difftest structural probes MATCH.

## 9. Verification
VERIFY-std with `<op>=shuffle`, plus:
```bash
uv run pytest -q tests/nettests/test_shuffle.py -rs        # 1 LONG_RUNNING skip
uv run python -c "import random; from flpit import flp; print(flp.it(range(5)).shuffle(rng=random.Random(42)).to_list())"
# [3, 1, 2, 4, 0]
```

## 10. Definition of Done
DoD-std, plus the `rng` extension documented in docstring, README deviations and the translation map.

## 11. Risks / open questions
- The doctest's exact output depends on CPython's `random.shuffle` algorithm, stable since 3.2 and identical on 3.12/3.13 (checked); if 3.14 ever changed it, switch the doctest to `sorted(...)` only.
- `Shuffle().Take(k)` fusion: worth a follow-up only if a user benchmark shows the full shuffle dominating; it changes how much randomness is consumed, so reproducibility with `rng` would change for that composition.
