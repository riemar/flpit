---
id: L07
title: first / first_or_default (D5 migration)
status: todo
priority: 018
effort: M
depends_on: [F05, F06, F07, F08, F09]
upstream:
  dotnet: FirstTests.cs (18 [Fact]/[Theory]) + FirstOrDefaultTests.cs (24 [Fact]/[Theory]) @ dotnet/runtime main 6f1d9331
  morelinq: n/a
pr:
---

# L07: `first` / `first_or_default` (D5 migration)

## 1. Goal
Bring `first_or_default` in line with D5 (`first_or_default(predicate=..., *, default=None)`), the shape every later `*_or_default` operator (L08, L09, L10) copies. Today the signature is `first_or_default(default, predicate=...)`, the reverse of .NET's argument order, and it makes `first_or_default()` impossible. Because this is a **breaking change**, it ships with a one-minor deprecation shim. The card also backfills the missing `FirstTests.cs`/`FirstOrDefaultTests.cs` ports and fixes the bugs found in the current `first`/`first_or_default`.

## 2. Scope
**In:**
- `first()` / `first(predicate)` and `first_or_default()` / `(predicate)` / `(default=...)` / `(predicate, default=...)` on `_LinqOps`.
- Deprecation shim for the legacy positional shapes `first_or_default(default)` and `first_or_default(default, predicate)` for one minor version (added 0.3.0, removed 0.4.0).
- Bug fixes listed in 3.2; migration of in-repo legacy call sites (`tests/nettests/test_order_by.py`, `tests/luna_test_suite/*`, `tests/gemini_test_suite/*`).
- Ported `test_first.py` and `test_first_or_default.py`.
**Out:** an O(n) `OrderedIt.first()` that avoids the full sort (.NET's `OrderedIterator.TryGetFirst`). It changes key-selector call order across multi-key orderings; proposed as a follow-up card, not done here.

## 3. Detailed design
### 3.1 Signatures
```python
TDefault = TypeVar("TDefault")

@overload
def first(self) -> TItem: ...
@overload
def first(self, predicate: Callable[[TItem], object]) -> TItem: ...

@overload
def first_or_default(self) -> TItem | None: ...
@overload
def first_or_default(self, predicate: Callable[[TItem], object]) -> TItem | None: ...
@overload
def first_or_default(self, *, default: TDefault) -> TItem | TDefault: ...
@overload
def first_or_default(self, predicate: Callable[[TItem], object], *, default: TDefault) -> TItem | TDefault: ...
@overload
@deprecated("first_or_default(default, predicate) is deprecated; use first_or_default(predicate, default=...)")
def first_or_default(self, legacy_default: TDefault, predicate: Callable[[TItem], object], /) -> TItem | TDefault: ...
@overload
@deprecated("first_or_default(default) is deprecated; use first_or_default(default=...)")
def first_or_default(self, legacy_default: TDefault, /) -> TItem | TDefault: ...
```
`deprecated` comes from `typing_extensions` **under `TYPE_CHECKING` only** (typeshed ships the stub; zero runtime dependency); at runtime a no-op decorator is used on 3.12, `warnings.deprecated` on ≥ 3.13.

| .NET | Python |
|---|---|
| `First()` / `First(predicate)` | `first()` / `first(predicate)` |
| `FirstOrDefault()` | `first_or_default()` → `None` when empty |
| `FirstOrDefault(TSource defaultValue)` (.NET 6+) | `first_or_default(default=v)` |
| `FirstOrDefault(predicate)` | `first_or_default(predicate)` |
| `FirstOrDefault(predicate, TSource defaultValue)` (.NET 6+) | `first_or_default(predicate, default=v)` |

### 3.2 Semantics
- Kind: terminal. Short-circuit: stops at the first (matching) element; with a predicate that never matches, the whole source is scanned.
- Errors: `first()` on empty → `EmptySequenceError`; `first(pred)` with no match (including empty source) → `NoMatchError` (.NET throws the "no matching element" message in both cases).
- `first_or_default` never raises for empty / no match; returns `default` (`None` unless given). It **does not** catch exceptions: source, predicate and element exceptions propagate (current bug: `first_or_default` catches `EmptySequenceError`/`NoMatchError`, so a predicate that internally raises `NoMatchError` is silently turned into the default).
- Validation (eager, before any iteration): explicit `predicate=None` → `ArgumentNoneError("predicate")`. Current bug: `first(None)` goes through `where(None)` lazily, so an empty source raises `NoMatchError` and a non-empty one `TypeError: 'NoneType' object is not callable`.
- `None` elements are values: `flp.it([None, 1]).first()` is `None`, and `first_or_default()` returning `None` is ambiguous by design (same as .NET for reference types); docs point to `first_or_default(default=_MY_SENTINEL)`.
- **Deprecation shim (one minor):** the implementation signature is `first_or_default(self, predicate=_SENTINEL, *legacy, default=_SENTINEL)`.
  - `legacy` non-empty (two positionals) → legacy `(default, predicate)`; emits `DeprecationWarning` (stacklevel 2).
  - If the `default=` keyword is given, the call is new-API by definition (legacy code could not pass both); a single positional is the predicate (`(None, default=1)` → `ArgumentNoneError`).
  - Otherwise, one positional that is **not callable** (including `None`) → legacy `(default,)`; emits `DeprecationWarning`.
  - One callable positional → new API (predicate). A legacy call that passed a *callable default* positionally (`first_or_default(str)`) silently changes meaning; called out in CHANGELOG as the only undetectable shape.
  - Two positionals plus `default=` → `TypeError("first_or_default() got multiple values for argument 'default'")`; more than two positionals → `TypeError`.
  - Keyword calls (`first_or_default(default=1, predicate=p)`) had the same meaning before and after: no warning.
  - In 0.4.0 the shim is removed: one non-callable positional becomes a predicate argument (so `None` → `ArgumentNoneError`, `99` → `TypeError` at enumeration).
- On `OrderedIt`: sorts, then takes the first (stable: first among equal keys).

### 3.3 Implementation sketch
```python
def first(self, predicate=_SENTINEL):
    result = self._first_or_missing(predicate)
    if result is _MISSING:
        raise EmptySequenceError() if predicate is _SENTINEL else NoMatchError()
    return result

def first_or_default(self, predicate=_SENTINEL, *legacy, default=_SENTINEL):
    predicate, default = _resolve_legacy_first_or_default(predicate, legacy, default)  # warns, validates
    result = self._first_or_missing(predicate)
    return (None if default is _SENTINEL else default) if result is _MISSING else result

def _first_or_missing(self, predicate):
    if predicate is _SENTINEL:
        return next(iter(self), _MISSING)
    _require_not_none(predicate, "predicate")
    return next(filter(predicate, self), _MISSING)     # C-level, truthiness, short-circuits
```
- O(k) time (k = position of the first match), O(1) memory. `filter(predicate, ...)` calls the predicate exactly once per pulled element, same as .NET.
- `_require_not_none` runs before `iter(self)` so validation is eager even for one-shot sources.
- `_first_or_missing` is shared with L09 (`single`) and later `*_or_default` cards.
- **FlpList fast path:** none; `next(iter(list))` is already O(1). The FlpList delegating copies are deleted (mixin).

### 3.4 Registry entry
```toml
[operators.first]
category = "element"
kind = "terminal"
buffering = "streaming"
short_circuit = true
dotnet = "Enumerable.First"
python_equivalent = "next(iter(xs)) / next(filter(pred, xs))"
since = "0.1.0"

[operators.first_or_default]
category = "element"
kind = "terminal"
buffering = "streaming"
short_circuit = true
dotnet = "Enumerable.FirstOrDefault"
python_equivalent = "next(filter(pred, xs), default)"
since = "0.1.0"
changed = "0.3.0: D5 signature (predicate first, keyword-only default); legacy positional default deprecated, removed in 0.4.0"
```

## 4. Tests
- **Ported** `tests/nettests/test_first.py` from `FirstTests.cs` (18): all portable; `TestEmpty*<T>` generic helpers collapse to one Python case; `NullSource*` → `SourceNoneError`; `NullPredicate` → `ArgumentNoneError`. Target 100 %.
- **Ported** `tests/nettests/test_first_or_default.py` from `FirstOrDefaultTests.cs` (24): `default(int)` expectations are rewritten to `is None` with a `# NO_VALUE_TYPES: default(T) -> None` comment (ported, not skipped); `FirstOrDefault(defaultValue)` → `first_or_default(default=...)`. Target 100 %.
- **Migrated** legacy call sites: `tests/nettests/test_order_by.py` (`first_or_default(0)` → `first_or_default(default=0)`, `first_or_default(0, pred)` → `first_or_default(pred, default=0)`), `tests/luna_test_suite/test_regression_contracts.py`, `test_flplist_comprehensive.py`, `test_falsey_callbacks.py`, `test_exception_regressions.py`, `tests/gemini_test_suite/test_created_20260923.py`. The test run must emit no `DeprecationWarning` from in-repo code.
- **Own unit tests** (`tests/unit/test_first.py`, `tests/unit/test_first_or_default_legacy.py`):
  - Eager `ArgumentNoneError` for `first(None)`, `first_or_default(None, default=1)` on an empty source.
  - Predicate raising `NoMatchError` / `ValueError` propagates out of `first_or_default`.
  - Short-circuit: predicate and source pulls stop at the first match.
  - Legacy shim, each with `pytest.warns(DeprecationWarning)`: `(99)`, `(None)`, `(99, pred)`, `("d", FalseyPredicate())`; no warning for `(pred)`, `(default=1)`, `(pred, default=1)`, `(default=1, predicate=pred)`; `TypeError` for `(99, pred, default=1)` and for three positionals.
  - The documented ambiguity: `first_or_default(str)` is treated as a predicate (pinned so the behaviour cannot drift).
- **Contracts** (auto): terminal, short-circuit probe, FlpList not mutated.
- **Typing** (`tests/typing/test_types_first.py`, `test_types_first_or_default.py`): `assert_type(xs.first(), int)`, `assert_type(xs.first_or_default(), int | None)`, `assert_type(xs.first_or_default(default=0), int)`, `assert_type(xs.first_or_default(lambda x: x > 1, default="n/a"), int | str)`; the legacy shapes are reported as deprecated by pyrefly.

## 5. Differential harness
`difftest/specs/first.toml`, `first_or_default.toml`: sources typed `int?`/`string` on the oracle side (so .NET's default is `null`, matching `None`), empty / singleton / `None`-first / duplicates; predicates from the catalogue; defaults `{omitted, 0, -1, None}`; probes `result` or exception kind, `predicate_calls`, `elements_pulled`. Expected: all MATCH. The legacy shim is not part of the harness.

## 6. Benchmarks
`tests/benchmarks/test_bench_first.py` (covers both operators), sizes 1e3 / 1e5, match at `size // 2`:
- `native`: `next(filter(lambda x: x == half, data), None)`; no-predicate: `next(iter(data), None)`
- `flpit-FlpIt` / `flpit-FlpList`: `flp.it(data).first_or_default(lambda x: x == half)`, `.first()`
- Target ratio ≤ 1.5× for the predicate case. The no-predicate case is O(1); its ratio is reported but dominated by call overhead (document the absolute ns).

## 7. Docs
- Docstrings: `.NET: Enumerable.First / FirstOrDefault`; the `None`-element ambiguity; D5 keyword `default`; Execution: Terminal, short-circuits.
- Doctests: `flp.it([1, 2, 3]).first(lambda x: x > 1)` gives `2`; `flp.it([1, 2, 3]).first_or_default(lambda x: x > 5, default=-1)` gives `-1`; `print(flp.it([]).first_or_default())` prints `None`.
- README: "Breaking change v0.3.0: `first_or_default`" box (old → new table, shim removal in 0.4.0, the callable-default caveat). CHANGELOG: `Changed` (breaking) + `Deprecated`.
- Translation map: `next(iter(xs))` / `.First()` → `.first()`; `next(filter(p, xs), d)` / `.FirstOrDefault(p, d)` → `.first_or_default(p, default=d)`.

## 8. Expected outcomes
- D5 signature live with a working, tested shim; all in-repo call sites migrated, zero deprecation warnings in the test run.
- 42 newly ported .NET tests green; the three bugs (lazy `None` predicate, swallowed `NoMatchError`, `where`-based overhead) fixed and pinned.

## 9. Verification
VERIFY-std with `<op>=first` and `<op>=first_or_default`, plus:
```bash
uv run pytest -q -W error::DeprecationWarning tests/          # no legacy call left in the repo
uv run python -W always -c "from flpit import flp; print(flp.it([]).first_or_default(99))"
# DeprecationWarning: first_or_default(default) is deprecated; use first_or_default(default=...)
# 99
uv run python -c "from flpit import flp; print(flp.it([1, 2, 3]).first_or_default(lambda x: x > 5, default=-1))"   # -1
```

## 10. Definition of Done
DoD-std, plus: README breaking-change box; CHANGELOG `Changed`/`Deprecated` entries naming 0.4.0 as removal; a tracking issue (or a `0.4.0` milestone checklist item) for removing the shim.

## 11. Risks / open questions
- pyrefly may flag the deprecated one-positional overload as overlapping the predicate overload (a callable is also a `TDefault`). If so, drop that overload: legacy `first_or_default(99)` then becomes a static error while still working at runtime with the warning.
- A legacy callable default passed positionally cannot be detected (documented).
- Follow-up (proposed, not on the board yet): O(n) `OrderedIt.first`/`last` without sorting, matching .NET's `OrderedIterator.TryGetFirst/TryGetLast`.
