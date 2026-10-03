---
id: F02
title: Test tree reorganisation
status: todo
priority: 002
effort: S
depends_on: [F01]
upstream:
  dotnet: n/a
  morelinq: n/a
pr:
---

# F02: Test tree reorganisation

## 1. Goal
Give every later card an obvious place for its tests, contracts, typing checks and benchmarks (README §3.2), and make the existing ad-hoc suites discoverable by intent rather than by the tool that generated them. Nothing is deleted: tests are only moved or renamed (D19).

## 2. Scope
**In**
| From | To |
|---|---|
| `tests/core/*.py` (non-empty) | `tests/unit/` |
| `tests/core/test_order_by.py` (0 lines) | deleted (empty file, nothing to preserve) |
| `tests/luna_test_suite/*` | `tests/unit/` (e.g. `test_lazy_core.py`); files whose content is about invariants (`test_resource_and_iterator_semantics.py`, `test_falsey_callbacks.py`, `test_regression_contracts.py`) → `tests/contracts/` |
| `tests/gemini_test_suite/test_created_20260923.py` | `tests/unit/test_mixed_scenarios.py` (rename only) |
| `tests/core/test_ordering_benchmark.py` | `tests/benchmarks/test_bench_order_by.py` |
| `tests/perf_run_1.py` (script) | `tests/benchmarks/perf_baseline.py`, kept as a manual script, excluded from collection (`python_files` pattern does not match `perf_*`) |
| `nettest_skips.py` (root) | `scripts/nettest_report.py` (logic unchanged; generalised in F08) |
| `tests/test_namespace_move.py` | `tests/unit/test_namespace_move.py` |
| — | new empty packages `tests/typing/`, `tests/contracts/` (with `__init__.py`) |

- Duplicate-name collisions (e.g. `tests/core/test_any.py` vs `tests/nettests/test_any.py`): rename the unit one to `test_any_unit.py`, since pytest `rootdir`-relative module names must stay unique with `__init__.py` packages.
- `pyproject.toml`: `testpaths = ["tests"]`, `python_files = ["test_*.py"]`, keep `pythonpath`.
- Use `git mv` so history follows (`git log --follow`).

**Out:** rewriting or deduplicating tests (several luna/gemini tests overlap; dedup is opportunistic inside later cards).

## 3. Detailed design
Final layout:
```
tests/
  conftest.py          # fixtures flp_type, run_once, tracker, non_collection (unchanged)
  helpers.py
  unit/
  contracts/
  nettests/            # unchanged
  typing/
  benchmarks/
scripts/
  nettest_report.py
```
`tests/benchmarks/conftest.py` applies `pytest.mark.benchmark` to every item in that directory (`pytest_collection_modifyitems`), so individual files don't need to remember the marker.

## 4. Tests
- Collected test count before == after (excluding the 0-line file): `uv run pytest --collect-only -q | tail -1` before and after; record both numbers in the PR.
- Benchmarks still deselected by default; `-m benchmark` selects exactly the moved ordering benchmarks.

## 5. Differential harness
n/a

## 6. Benchmarks
Only moved. Running `uv run pytest -m benchmark tests/benchmarks` must work.

## 7. Docs
README "Migrated .NET Unit Tests" section: the command to regenerate the table becomes `uv run python scripts/nettest_report.py`. Add `tests/README.md` (10 lines) describing each folder's purpose (copy of README §3.2 of the board).

## 8. Expected outcomes
- Same pass/skip counts as after F01; clean folder semantics.
- `git log --follow tests/unit/test_mixed_scenarios.py` shows the gemini history.

## 9. Verification
```bash
uv run pytest --collect-only -q | tail -1      # equal to pre-move count
uv run pytest -q                               # green
uv run pytest -q -m benchmark tests/benchmarks --benchmark-disable   # collects & runs once
uv run python scripts/nettest_report.py        # prints the table
git status --porcelain | grep -v '^R' ; echo "expect only renames + new __init__/conftest/README"
```

## 10. Definition of Done
- [ ] All moves via `git mv`; counts equal
- [ ] New folders with `__init__.py`
- [ ] benchmarks conftest auto-marker
- [ ] tests/README.md
- [ ] Suite green

## 11. Risks / open questions
- Importing `tests.helpers` from moved files: the existing imports use `from tests.helpers import ...`, which still works because `tests/` stays a package.
