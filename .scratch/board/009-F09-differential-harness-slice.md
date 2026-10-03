---
id: F09
title: "Differential harness: smallest end-to-end slice"
status: todo
priority: 009
effort: L
depends_on: [F06, F08]
upstream:
  dotnet: .NET 10 SDK (GA) as runtime oracle; .agents/testplan.md §6–§11, §28
  morelinq: MoreLINQ NuGet package (added when the first M card lands)
pr:
---

# F09: Differential harness: smallest end-to-end slice

## 1. Goal
Implement the first vertical slice of the private differential-testing system in `.agents/testplan.md` (D18): **one operator + .NET oracle process + Python runner + structured comparison + one execution probe + one deterministic regression test**, wired into CI. Then grow it with **one spec per operator card**, so every operator added from L01 onwards is checked against real .NET behaviour, not only against ported examples.

## 2. Scope
**In**
- `difftest/` (repo root, not shipped in the wheel):
  ```
  difftest/
    __main__.py             # CLI: run | repro | list | coverage
    protocol.py             # dataclasses for request/response (JSON Lines)
    functions.py            # portable function catalog (Python side)
    sources.py              # source kinds: list, one_shot, throwing_at(i), counting
    runner_py.py            # executes a scenario against flpit
    oracle.py               # manages the dotnet child process (stdin/stdout JSONL)
    normalize.py, compare.py, classify.py
    specs/<op>.toml         # per-operator spec (args schema, domains, probes, known diffs)
    oracle/                 # C# project
      Oracle.csproj         # net10.0, System.Text.Json, (later) MoreLinq
      Program.cs            # JSONL loop
      Functions.cs          # same catalog as functions.py
      Sources.cs            # same source kinds, with trace hooks
      Operators/*.cs        # one file per operator (Where.cs first)
  ```
- Slice operator: **`where`** (exercises predicate catalog, laziness, exceptions) with terminals `to_list`, `first`, `count`.
- Probe: **execution trace** (ordered events: `src.get_enumerator`, `src.move_next(i)`, `fn.call(name, arg)`, `yield(value)`, `throw(type, message)`).
- One deterministic regression test captured from a harness case into `tests/regressions/test_difftest_where.py` (via `python -m difftest repro --emit-pytest`).
- CI job `difftest` in `ci.yml` (`actions/setup-dotnet` 10.0.x, NuGet cache), required in `ci-ok`.
- Coverage command listing implemented registry operators without a spec (report-only in this card; becomes failing once L01 lands).

**Out:** composition generator, Hypothesis-driven generation, nightly fuzzing (X01). Operators other than `where` and `skip` (`skip` comes with L01 as the first card to use the slice).

## 3. Detailed design
### 3.1 Protocol (JSON Lines, one request per line, one response per line)
```json
{"v":1,"case":"where-0007","seed":7,
 "source":{"kind":"list","items":[1,2,3,4,5]},
 "pipeline":[{"op":"where","args":{"predicate":{"fn":"gt","arg":2}}}],
 "terminal":{"op":"to_list"},
 "probes":["trace"]}
```
```json
{"v":1,"case":"where-0007","status":"ok",
 "result":{"kind":"values","values":[3,4,5]},
 "trace":[["src.get_enumerator"],["src.move_next",0],["fn.call","gt",1],...,["src.move_next_end"]]}
```
Exceptions: `"result":{"kind":"exception","type":"InvalidOperationException","message":"Sequence contains no matching element","at":"terminal"}`.
- Values domain (portable, testplan §7): int (bounded ±2^31), str, bool, null, and lists of these; no floats in the slice (decimal/float formatting is classified later).

### 3.2 Portable function catalog (identical semantics on both sides, unit-tested in each language)
`identity, is_even, gt(k), lt(k), eq(k), mod(k), throws_on(k), count_calls (stateful), always_true, always_false, key_len (str)`. Each callable records `fn.call` trace events when the trace probe is on.

### 3.3 Exception mapping (`classify.py`)
| .NET | flpit | Comparison |
|---|---|---|
| `ArgumentNullException(param)` | `ArgumentNoneError(param_name)` | param name must match; timing must match (call vs enumeration) |
| `InvalidOperationException` "contains no elements" | `EmptySequenceError` | message equal (normalised punctuation) |
| "contains no matching element" | `NoMatchError` | idem |
| "more than one element" / "more than one matching element" | `Multiple*Error` | idem |
| `ArgumentOutOfRangeException` | `ArgumentOutOfRangeError` / `IndexError` (element_at) | type family + timing |
| catalog `throws_on` → `TestException` | `TestException` | type + position in trace |
Per testplan §27, message equality is primary and type is secondary.

### 3.4 Classification
`MATCH, MISMATCH, EXPECTED_DIFFERENCE(reason), UNCOMPARABLE(reason), INVALID_TEST_CASE, ORACLE_ERROR, PYTHON_ERROR, HARNESS_ERROR`. Spec files declare expected differences with a reason drawn from the F08 skip categories. CI fails on `MISMATCH`, `ORACLE_ERROR`, `PYTHON_ERROR`, `HARNESS_ERROR`.

### 3.5 Spec file (example `difftest/specs/where.toml`)
```toml
operator = "where"
dotnet = "Where"
[args.predicate]
type = "function"
catalog = ["is_even", "gt", "always_false", "throws_on"]
[domains]
sources = ["list", "one_shot", "throwing_at"]
items = "ints_small"            # predefined domain: [], [0], dup-heavy, negatives, range(0,20)
[terminals]
use = ["to_list", "first", "count"]
[probes]
trace = true
[[expected_difference]]
when = "source.kind == 'one_shot' and reenumerate"
reason = "OTHER: Python generators are one-shot; .NET IEnumerable re-enumerates"
```
Deterministic case generation: Cartesian product of domains, capped (`max_cases = 500`), case IDs stable (`<op>-<index>`), seed recorded.

### 3.6 Process model
- `oracle.py` starts `dotnet <built dll>` once per run (build with `dotnet build -c Release` beforehand; CI caches `~/.nuget/packages` and `difftest/oracle/bin`). Requests are batched and streamed, with a 10 s per-case timeout. ORACLE_ERROR on crash, and the oracle is restarted.
- Local developers without the .NET SDK: `python -m difftest run` prints a clear skip message; CI always runs it.

### 3.7 Commands
```
python -m difftest run [--op where] [--seed 0] [--max-cases N] [--json out.jsonl]
python -m difftest repro difftest/failures/<case>.json [--emit-pytest tests/regressions/...]
python -m difftest coverage          # implemented operators without specs (from registry)
python -m difftest list              # specs + case counts
```

## 4. Tests
- `tests/unit/difftest/`: catalog parity tests (Python side), protocol round-trip, normaliser, classifier (fixtures with synthetic oracle responses: no dotnet needed).
- C# side: `dotnet test` on a tiny `Oracle.Tests` project for the catalog and sources (run in the CI difftest job).
- **Planted-bug check** (proves the harness can fail): temporarily make `where` evaluate eagerly on a branch → harness reports MISMATCH on trace; revert. Link the failing run in the PR.
- The regression test emitted from a real case passes in the normal pytest run (no dotnet needed: expected values are frozen).

## 5. Differential harness
This card *is* the harness. Acceptance: `where` spec ≥ 300 cases, 0 MISMATCH, expected differences documented.

## 6. Benchmarks
Harness performance only: the full `where` spec completes in < 30 s in CI (oracle start included).

## 7. Docs
- `difftest/README.md`: architecture diagram (scenario → oracle/python → normalise → compare → classify), how to add an operator spec (what each operator card does), how to reproduce a failure.
- `.agents/testplan.md` §28 updated with "Slice delivered: F09".

## 8. Expected outcomes
- A working .NET-vs-Python comparison for `where` in CI, including timing of callbacks and exceptions (the hardest semantics to keep right).
- A repeatable recipe every later card uses (spec + optional C# operator file).
- Failures are reproducible from case ID + seed and can be frozen as pytest regressions.

## 9. Verification
```bash
dotnet --version                                  # 10.0.x
dotnet build difftest/oracle -c Release
uv run python -m difftest run --op where --json /tmp/where.jsonl
uv run python -m difftest run --op where | tail -5   # summary: MATCH n, EXPECTED_DIFFERENCE k, MISMATCH 0
uv run python -m difftest repro difftest/failures/<case>.json --emit-pytest tests/regressions/test_difftest_where.py
uv run pytest -q tests/regressions tests/unit/difftest
uv run python -m difftest coverage
```
CI: the `difftest` job is green and required by `ci-ok`; the planted-bug run is linked as red.

## 10. Definition of Done
- [ ] Protocol, catalog, sources, runner, oracle (C#), normaliser, comparator, classifier
- [ ] `where` spec with trace probe; 0 MISMATCH
- [ ] Planted-bug demonstration
- [ ] One frozen regression test
- [ ] CI job required; README for difftest
- [ ] Coverage command

## 11. Risks / open questions
- **Oracle version vs D6**: unit-test ports follow runtime `main`, but the runtime oracle uses .NET 10 GA. Operators only in `main` (FullJoin) are UNCOMPARABLE in the harness until GA (README open question 2). Option: add a nightly job using the daily .NET 11 SDK once it exists (X01).
- CI time: dotnet setup adds ~40 s; acceptable. The NuGet cache keeps it stable.
- Trace equality is strict (testplan §2.3). Where Python cannot represent .NET's `IList` fast-path traces (e.g. `Count` on a list doesn't enumerate in .NET), sources in the harness are always non-collection enumerables unless a spec explicitly opts in.
