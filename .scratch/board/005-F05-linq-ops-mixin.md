---
id: F05
title: "`_LinqOps` mixin + argument-validation unification"
status: todo
priority: 005
effort: L
depends_on: [F03]
upstream:
  dotnet: n/a (ArgumentNullException semantics from every *Tests.cs `*_ThrowsArgumentNullException` test)
  morelinq: n/a
pr:
---

# F05: `_LinqOps` mixin + argument-validation unification

## 1. Goal
Before ~80 operators are added, remove the structural duplication between `FlpIt` and `FlpList` (D1) so that each operator is **written, typed, documented and tested once**. At the same time, establish the shared validation helpers and exception types every later card uses. This card is behaviour-preserving except for the deliberate, .NET-aligned move of argument validation to call time.

## 2. Scope
**In**
- New internal base `_LinqOps[TItem]` holding every LINQ operator now on `FlpIt` (`append … to_list`).
- `FlpIt(_LinqOps[TItem], Iterable[TItem])`, `FlpList(_LinqOps[TItem], Collection[TItem])`; `OrderedIt`/`Grouping` unchanged (inherit through FlpIt).
- FlpList keeps **only** genuine fast paths: `count()` (no predicate) → `len`, `any()` (no predicate) → `len > 0`, `last()` → `[-1]` and reverse scan with predicate, `element_at` → index, `to_list` → copy, `__contains__`, plus its Collection/List<T> API (`add`, `add_range`, dunders).
- Fixes the drift: **`FlpList.concat`** (missing today), consistent `first_or_default`/`single` paths.
- Validation helpers in `flpit/core/_validation.py`:
  - `_require_not_none(value, param)` → `ArgumentNoneError(param)`
  - `_require_callable(fn, param)` → `ArgumentNoneError` if None, `TypeError` if not callable
  - `_require_index(n, param)` → `operator.index(n)` (rejects float/str with `TypeError`)
  - `_require_non_negative(n, param)` / `_require_positive(n, param)` → `ArgumentOutOfRangeError`
- Exceptions module `flpit/core/errors.py` (re-exported from `flpit.core.linq` and `flpit` for compatibility):
  - `ArgumentNoneError(TypeError)` with `.param_name`, message `Value cannot be null. (Parameter '<name>')` (.NET wording)
  - `SourceNoneError`, `PredicateNoneError`, `SelectorNoneError` become subclasses of `ArgumentNoneError` (existing `isinstance`/`except` code keeps working); `SelectorNoneError` gets the real parameter name instead of always `keySelector`.
  - `ArgumentOutOfRangeError(ValueError)` (used by `chunk(0)` today: currently a bare `ValueError`, so this is compatible)
  - `DuplicateKeyError(ValueError)` (reserved for L18)
- **Eager argument validation** on all existing deferred operators (`where`, `select`, `select_many`, `distinct_by`, `zip`, `concat`, `group_by`, `order_by*`, `then_by*`, `cast`, `of_type`): `None` callables/sources now raise at call time, not at first enumeration (matches .NET `ArgumentNullException` timing; rules.md "Callbacks & Exceptions" unaffected, since callbacks still run lazily).
- Public-API guard tests (see §4).

**Out:** new operators; renaming; PEP 695 syntax migration; any semantic change other than validation timing.

## 3. Detailed design
### 3.1 Shape
```python
class _LinqOps(Generic[TItem]):
    __slots__ = ()

    def _source(self) -> Iterable[TItem]:
        """Iterable that operators enumerate. FlpIt: self (keeps OrderedIt sorting);
        FlpList: the backing list object (live view: mutations before enumeration are visible,
        like .NET List<T>)."""
        raise NotImplementedError

    def where(self, predicate: Callable[[TItem], bool]) -> FlpIt[TItem]:
        """Filters ... (single docstring, inherited by FlpIt/FlpList)."""
        _require_callable(predicate, "predicate")
        src = self._source()
        def _generator() -> Iterator[TItem]:
            for item in src:
                if predicate(item):
                    yield item
        return FlpIt(_FactoryIterable(_generator))
    ...
```
- `FlpIt._source()` returns `self`; `FlpList._source()` returns `self.__list.data`.
- `FlpIt` is referenced inside `_LinqOps` methods at call time, so defining `_LinqOps` before `FlpIt` in the same module is fine (no import cycle).
- `as_type` stays per class (must return `self` with the class's own type; `typing.Self` cannot rebind the type parameter).
- Typing: return annotations use `FlpIt[...]`/`OrderedIt[...]` explicitly; `self` is un-annotated, so pyrefly infers `TItem` from the subclass's specialisation. **Spike first** (half a day): verify `assert_type(FlpList[int]([1]).select(str), FlpIt[str])` under pyrefly strict and pyright before converting everything.
- Module layout (import path `flpit.core.linq` stays valid):
  ```
  flpit/core/errors.py       # exceptions
  flpit/core/_validation.py  # helpers
  flpit/core/_iterables.py   # _FactoryIterable, _Sentinel, _SENTINEL, _MISSING
  flpit/core/linq.py         # _LinqOps, FlpIt, OrderedIt, Grouping, FlpList (+ re-exports)
  ```
  Splitting `_LinqOps` per category into separate files is deferred until linq.py exceeds ~2,500 lines (likely after Phase 1); a later card can do it mechanically with mixin composition (`class _LinqOps(_Filtering, _Projection, ...)`).
- Remove `_guard_empty`'s reliance on name mangling (`self._FlpList__list`): `min`/`max`/`min_by`/`max_by` move to the mixin using the `_extreme` helper (`default=_MISSING`), which is also O(n) with no try/except overhead.

### 3.2 Docstrings with a mixin (answers the interview question)
- One docstring per operator on `_LinqOps`. `help(FlpList.where)`, `inspect.getdoc`, Pylance/PyCharm hovers and doctest collection all resolve inherited docstrings.
- FlpList fast-path overrides **may** omit docstrings: `inspect.getdoc` falls back to the base class. The completeness test (below) uses `inspect.getdoc`, so overrides stay covered.
- Doctest examples live once (on the mixin) and are run once; FlpList parity is covered by unit tests parametrized with `flp_type`.

### 3.3 Behaviour-change table (goes to CHANGELOG "Changed")
| Call | Before | After |
|---|---|---|
| `flp.it(xs).where(None)` | TypeError at enumeration | `PredicateNoneError` at call |
| `flp.it(xs).select(None)` | TypeError at enumeration | `SelectorNoneError('selector')` at call |
| `flp.it(xs).concat(None)` | TypeError at enumeration | `ArgumentNoneError('second')` at call |
| `flp.lst(xs).concat(ys)` | AttributeError | works (lazy) |
| `flp.it(xs).chunk(0)` | ValueError | `ArgumentOutOfRangeError` (still a ValueError) |

## 4. Tests
- **Entire existing suite must pass unchanged**, except tests that asserted lazy `None` failures (update them to eager and list them in the PR).
- New `tests/contracts/test_api_parity.py`: every public operator on `FlpIt` is available on `FlpList` with the same signature (`inspect.signature` equality, allow-list for `then_by*` on `OrderedIt`, `key` on `Grouping`, `add/add_range` on FlpList).
- New `tests/contracts/test_docstrings.py`: for each of `FlpIt`, `FlpList`, `OrderedIt`, `Grouping` and the `flp` factory module, every public callable has a non-empty `inspect.getdoc`, whose first line ends with a period.
- New `tests/contracts/test_public_api_snapshot.py`: compares the sorted public names of each class and of `flpit.__all__` against `tests/contracts/public_api.txt`. Every later card updates this file, which makes API additions explicit in review.
- New `tests/unit/test_argument_validation.py`: for each deferred op, `None` raises the right error **without** iterating (`NoIterList` source), and the error's `param_name` is correct.
- FlpList fast paths: each override is cross-checked against the generic implementation (`_LinqOps.<op>(lst, ...)`) on random data with Hypothesis.

## 5. Differential harness
n/a (F09 builds on the unified validation: `ArgumentNoneError` maps to `ArgumentNullException`).

## 6. Benchmarks
Run the existing ordering benchmark plus a quick `where/select/sum` pipeline on FlpList before and after: **no regression > 5 %** (the mixin removes one `FlpIt(...)` wrapper per FlpList call, so a small gain is expected). Record the numbers in the PR.

## 7. Docs
- README: an "Errors" section listing the exception hierarchy and when validation happens.
- `.agents/rules.md`: new section "Implementation pattern": implement on `_LinqOps`, FlpList override only for fast paths, use `_validation` helpers.

## 8. Expected outcomes
- `linq.py` shrinks by ~350 lines; each new operator costs one method.
- FlpList/FlpIt parity is enforced by a test, so drift like the missing `concat` cannot recur.
- Argument errors are uniform, .NET-worded, eager and catchable via `ArgumentNoneError`/`ArgumentOutOfRangeError`.

## 9. Verification
```bash
uv run pytest -q                                   # full suite green
uv run pytest -q tests/contracts                   # parity, docstrings, API snapshot
uv run pyrefly check && uvx pyright src            # strict clean; pyright informational
uv run python - <<'EOF'
from flpit import flp, ArgumentNoneError
print(flp.lst([1,2]).concat([3]).to_list())        # [1, 2, 3]
try: flp.it(iter([])).where(None)
except ArgumentNoneError as e: print(e.param_name) # predicate
EOF
uv run pytest -q -m benchmark tests/benchmarks --benchmark-compare   # vs saved baseline from main
```

## 10. Definition of Done
- [ ] Spike result (typing inference through the mixin) documented in PR before the full conversion
- [ ] `_LinqOps` hosts all operators; FlpList only fast paths + collection API
- [ ] errors/_validation modules; old names still importable from `flpit` and `flpit.core.linq`
- [ ] Eager validation on all deferred ops; behaviour table in CHANGELOG
- [ ] Parity, docstring and API-snapshot contract tests
- [ ] No benchmark regression > 5 %
- [ ] rules.md updated

## 11. Risks / open questions
- **Type inference through `self` on a generic mixin** may degrade in mypy/pyright (pyrefly is the target). Fallback: annotate `self: _LinqOps[TItem]` explicitly on each method.
- `__slots__` with multiple inheritance: `_LinqOps` must declare `__slots__ = ()` to keep FlpIt's slots effective.
- Live-view semantics of `FlpList._source()` (mutating the list between query creation and enumeration is visible) is unchanged from today and matches .NET `List<T>`; it's now documented explicitly.
