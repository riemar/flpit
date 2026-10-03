---
id: F08
title: .NET test porting kit + registry-driven contract tests
status: todo
priority: 008
effort: M
depends_on: [F06]
upstream:
  dotnet: dotnet/runtime main, src/libraries/System.Linq/tests (pinned per file)
  morelinq: n/a
pr:
---

# F08: .NET test porting kit + registry-driven contract tests

## 1. Goal
Porting `*Tests.cs` files should be **mechanical, traceable and complete**:
- every upstream test is either ported or explicitly skipped with a categorised reason,
- every port pins the upstream commit (D6: oracle is `main`, which moves),
- upstream drift is detected automatically.

Also add generic contract tests that every registered operator gets for free (deferral, one-shot, short-circuit, no FlpList mutation, argument validation timing).

## 2. Scope
**In**
- `tests/nettests/UPSTREAM.toml`: `file → {upstream_path, sha, ported_on, upstream_test_count}`
- `scripts/port_scaffold.py <Name>Tests.cs`: fetches the file at a given SHA (default: current `main` HEAD, resolved and pinned) and writes `tests/nettests/test_<op>.py` with the licence header plus **one stub per `[Fact]`/`[Theory]`** (snake_cased name; `[InlineData]` rows become `pytest.mark.parametrize` tuples where literal) and a `pytest.skip("TODO: port")` body
- `tests/nettests/_skip.py`: `class Skip(StrEnum)` categories (README §3.2) and `nskip(cat, detail)` / `@nskip_mark(cat, detail)` helpers
- `scripts/nettest_report.py` (from F02): adds `--check-complete` (every upstream test name present in the port; no `TODO: port` left), a per-category skip table, and README-table regeneration (folded into `gen_docs.py` targets)
- `.github/workflows/upstream-drift.yml`: weekly cron; for each `UPSTREAM.toml` entry, diffs the pinned SHA against `main` for that file; opens/updates one issue "Upstream LINQ tests changed: <files>" with the diff summary
- `tests/contracts/test_operator_contracts.py`: registry-driven invariants (below)
- Retrofit the existing 11 nettest files: add header SHA + UPSTREAM.toml entries, convert ad-hoc skips to categories

**Out:** porting new files (done by operator cards).

## 3. Detailed design
### 3.1 Header (generated)
```python
"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported from dotnet/runtime src/libraries/System.Linq/tests/SkipTests.cs
@ 6f1d9331b9b477df73982a0fabedefe27f36d8a3 (ported 2026-10-xx).
Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
Independent Python port adapted to flpit's API and semantics.
"""
```
### 3.2 Translation guide (CONTRIBUTING "Porting .NET tests")
| C# construct | Python |
|---|---|
| `[Fact] void Foo()` | `def test_foo(flp_type):` |
| `[Theory] [InlineData(...)]` | `@pytest.mark.parametrize(...)` |
| `[MemberData(nameof(X))]` | module-level generator `x_cases()` |
| `Assert.Throws<ArgumentNullException>("predicate", ...)` | `with pytest.raises(ArgumentNoneError) as e: ...; assert e.value.param_name == "predicate"` |
| `Assert.Throws<InvalidOperationException>` | `EmptySequenceError` / `NoMatchError` / `Multiple*Error` per message |
| `NumberRangeGuaranteedNotCollectionType(...)` | `non_collection(...)` fixture |
| `new FastInfiniteEnumerator<T>()` | `itertools.count()` |
| `ThrowsOnMatchEnumerable` / `DelegateIterator` | `tests/helpers.py` equivalents (`Bomb`, `broken_iterator`, new `DelegateIterator`) |
| `RunOnce()` | `run_once` fixture |
| `int?` / nullable value types | `int \| None` (often `NO_NULLABLE_DISTINCTION` skip) |
| `IEqualityComparer` args | key selector rewrite or `COMPARER_NOT_SUPPORTED` (D3) |
| Tests on `IList`/`IPartition`/`Span` internals | `INTERNAL_OPTIMIZATION` / `NO_SPAN_OR_ARRAY` |

### 3.3 Registry-driven contracts (`tests/contracts/test_operator_contracts.py`)
Each registry entry may provide `contract_args = "<python expr>"` (example arguments, e.g. `"(lambda x: x > 1,)"`). For every implemented operator × `flp_type` (FlpIt, FlpList):
| Invariant | Applies to | How |
|---|---|---|
| construction does not iterate | `kind=intermediate` | source = `NoIterList`/`broken_iterator`; calling the op must not raise |
| callbacks not called before enumeration | intermediate | `tracker` fixture → `call_count == 0` after construction |
| one-shot source stays one-shot | intermediate | generator source; enumerate twice → second empty |
| re-iterable source re-iterates | intermediate | list source; two enumerations equal |
| short-circuit | `short_circuit=true` | instrumented source counts pulled items; ≤ the operator's declared bound (`contract_max_pull`) |
| FlpList not mutated | all on FlpList | snapshot before/after |
| None arg validated eagerly | all with callable args | `ArgumentNoneError` raised without iterating |
New operators thus get ~10 checks by adding `contract_args` to their registry entry.

## 4. Tests
- Unit tests for `port_scaffold.py` against a small fixture `.cs` file (Facts, Theories with InlineData, MemberData): golden output.
- `nettest_report.py --check-complete` passes on the retrofitted 11 files (missing upstream tests get explicit skips with categories).
- Contract suite runs green over all currently implemented operators. Any real violation found is fixed in this card if trivial, otherwise filed as a card note.

## 5. Differential harness
n/a (F09 reuses the skip categories as its `EXPECTED_DIFFERENCE`/`UNCOMPARABLE` reasons for consistency).

## 6. Benchmarks
n/a

## 7. Docs
CONTRIBUTING "Porting .NET tests" with the translation guide; README nettest table now shows `ported / skipped-by-category / upstream total` per file.

## 8. Expected outcomes
- Porting a file starts from a complete stub list, so nothing is silently dropped.
- README shows honest parity numbers; drift in upstream `main` surfaces as a weekly issue.
- Every operator automatically gets deferral/one-shot/short-circuit/validation contract checks.

## 9. Verification
```bash
uv run python scripts/port_scaffold.py SkipTests.cs --dry-run | head -40     # header + stubs
uv run python scripts/nettest_report.py --check-complete                      # 0
uv run pytest -q tests/contracts/test_operator_contracts.py
uv run pytest -q tests/nettests -rs | grep -c "COMPARER_NOT_SUPPORTED"        # categories visible
gh workflow run upstream-drift.yml && gh run watch                           # issue opened/updated only if drift
```

## 10. Definition of Done
- [ ] UPSTREAM.toml + headers for the 11 existing ports
- [ ] port_scaffold.py (+ tests), `_skip.py`, report `--check-complete` in CI lint job
- [ ] upstream-drift workflow
- [ ] Registry-driven contract suite green
- [ ] CONTRIBUTING porting guide

## 11. Risks / open questions
- Scaffold parsing C# with regexes is best-effort; it only needs names and literal `InlineData`, and complex members are left as stubs for humans.
- The drift workflow needs `issues: write`; it never edits code.
