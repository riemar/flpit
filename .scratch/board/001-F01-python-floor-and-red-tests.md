---
id: F01
title: Python floor 3.12 + red tests
status: todo
priority: 001
effort: S
depends_on: []
upstream:
  dotnet: n/a
  morelinq: n/a
pr:
---

# F01: Python floor 3.12 + red tests

## 1. Goal
Make `main` honest and green before any automation lands: the package must import on every declared Python version, and the default test run must pass deterministically. Without this, F03's CI would be red from day one.

## 2. Scope
**In**
- `requires-python = ">=3.12"` (D2), classifiers: drop 3.11, keep 3.12/3.13/3.14.
- Add `.python-version` (`3.12`) so `uv run` uses the floor version locally by default.
- Regenerate `uv.lock` (`uv lock`).
- Fix the 3 failing tests:
  1. `tests/nettests/test_order_by.py::test_SortsRandomizedEnumerableCorrectly[*-1000000]`: remove the wall-clock assertion `assert elapsed < 0.7  # not part of the original test` (D8). The functional assertion (sortedness) stays; the 1e6-element case moves to `tests/benchmarks/` in F07 (here: keep the case, drop the timing line; mark it `@pytest.mark.slow` if it exceeds ~2 s).
  2. `tests/test_namespace_move.py::test_import_via_redirect`: fails when `flp` was already imported earlier in the session, so the module-level `warnings.warn` fires once only. Fix the test, not the shim: purge `sys.modules` entries for `flp` before importing (use `monkeypatch.delitem(sys.modules, "flp", raising=False)`), then `importlib.import_module("flp")` inside `pytest.warns(DeprecationWarning)`.
- Fix the stale statement in `.agents/rules.md` ("FlpList extends `collections.UserList`"): FlpList now implements `Collection` (commit 2c88fa4).
- Register the `slow` marker in `pyproject.toml`.

**Out:** CI (F03), restructuring tests (F02), the rest of the duplication cleanup (F05).

## 3. Detailed design
### 3.1 `pyproject.toml` diff (intent)
```toml
requires-python = ">=3.12"
classifiers = [ ..., "Programming Language :: Python :: 3.12", "... :: 3.13", "... :: 3.14", ... ]  # 3.11 removed

[tool.pytest.ini_options]
addopts = "-m 'not benchmark and not slow'"
markers = ["benchmark: performance benchmarks", "slow: long functional tests (run in CI nightly / on demand)"]
```
### 3.2 Why not keep 3.11?
`typing.override` (3.12) is used in `OrderedIt`; 3.12 also unlocks PEP 695 syntax and faster generators. 3.11 reaches end of life in Oct 2027, so dropping it now is cheap.

### 3.3 Version bump
`0.2.0.dev1` → `0.2.0.dev2` is **not** needed: F04 derives the version from tags. Leave the version as is.

## 4. Tests
- The full suite on 3.12, 3.13 and 3.14 passes with 0 failures (`uv run -p 3.1x pytest`).
- `pytest -p no:randomly`-independent: run the namespace test alone and in the full suite and confirm it passes both ways.
- Add `tests/test_packaging.py`: asserts `importlib.metadata.metadata("flpit")["Requires-Python"] == ">=3.12"` and that `flpit.__version__` is a str.

## 5. Differential harness
n/a

## 6. Benchmarks
n/a (timing assertion removed; real benchmark lands in F07).

## 7. Docs
README: add "Requires Python 3.12+" under Installation. CHANGELOG created in F04; record this as "Changed: minimum Python is now 3.12" there.

## 8. Expected outcomes
- `uv run -p 3.12 pytest` → `0 failed`; same for 3.13, 3.14.
- `uv run -p 3.11 ...` refuses to install with a clear resolver message instead of an `ImportError` at import time.
- `.agents/rules.md` is accurate.

## 9. Verification
```bash
uv lock && git diff --stat uv.lock
for v in 3.12 3.13 3.14; do uv run -p $v pytest -q || exit 1; done
uv run -p 3.12 pytest -q tests/test_namespace_move.py          # alone
uv run -p 3.12 pytest -q tests/ -k "namespace or order_by"     # mixed order
uv run -p 3.11 python -c "import flpit" ; echo "expected: uv refuses (requires-python)"
uv run pyrefly check                                             # 0 errors
```

## 10. Definition of Done
- [ ] `requires-python`, classifiers, `.python-version`, lock updated
- [ ] 3 failing tests fixed without weakening functional assertions
- [ ] `slow` marker registered; default run excludes it
- [ ] rules.md corrected
- [ ] Suite green on 3.12, 3.13, 3.14

## 11. Risks / open questions
- 3.14 might surface new deprecation warnings (e.g. `decimal._ContextManager` typing); fix them in this card if they're trivial, otherwise in F03.
