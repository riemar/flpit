---
id: X01
title: "Differential harness: compositions, property-based generation, full coverage"
status: todo
priority: 092
effort: L                # epic: 10 sub-increments, each its own PR (X01.1 ... X01.10)
depends_on: [F03, F06, F08, F09]   # plus: specs of the Phase 1 operators for X01.7 to be meaningful
upstream:
  dotnet: .NET 10 SDK (GA) System.Linq as runtime oracle; .agents/testplan.md §4, §5, §7–§18, §22, §24, §26–§28
  morelinq: MoreLINQ NuGet package (runtime oracle for M cards, pinned version)
pr:
---

# X01: Differential harness expansion (epic)

## 1. Goal
F09 delivers the trusted slice (one operator, oracle process, comparator, trace probe, one frozen regression) and every operator card adds a deterministic spec. That covers testplan levels 1 to 9 per operator, but not the two things the testplan calls mandatory and most likely to find bugs that example tests miss: **generated inputs** (Level 11, §12) and **operator compositions** (Level 10, §13), at a volume (§17) and with a reproducibility, regression and coverage discipline (§15, §16, §18) that makes "verified" a defensible statement (§24). This epic grows the harness in ten ordered, independently mergeable increments, each with its own outcome and check, so the harness proves it can catch planted bugs **before** the case count scales (§21, §22).

## 2. Scope
**In:** spec schema v2 with shape metadata; portable value and callback model v2; oracle throughput; deterministic corpus (Tier A) with stable case IDs; harness self-tests (mutation); Hypothesis generation (Tier B); composition generator (Tier C); regression capture and replay without .NET (Tier D); nightly CI job with a large fuzz budget; machine-readable coverage model and report; the testplan §26 command set.
**Out:** making the harness a public package (§1: private suite); comparer objects (D3: key selectors only, the catalogue covers keys); `IQueryable`; operators not implemented in flpit (§3.1); performance comparison with .NET (benchmarks are F07).

**Process rule:** one sub-increment = one branch = one PR titled `X01.n: ...`, merged in order (later steps rely on earlier ones). This card stays `doing` until X01.10 merges. Each PR keeps the F09 `difftest` PR job green and must not raise its wall time above 5 min.

## 3. Detailed design: ordered sub-increments
Assumed F09 baseline (names from the F09 card): `python -m difftest run | repro | list | coverage`, `difftest/specs/<op>.toml`, catalogue `functions.py` / `Functions.cs`, source kinds `list, one_shot, throwing_at(i), counting`, `trace` probe events, F09 classifications, `--emit-pytest` into `tests/regressions/`.

### X01.1 Spec schema v2: shapes, profiles, lint
- New spec sections: `[shape] input = "seq[T]"`, `output = "seq[T]" | "seq[U]" | "ordered[T]" | "seq[group[K,T]]" | "seq[list[T]]" | "scalar[bool|int|T|str]" | "void"`; `requires = ["orderable_key", "hashable", "str_items", ...]`; `cost = "linear" | "nlogn" | "factorial" | "exponential"` with `max_len`; `compose = true|false`; `comparison_profile = "exact" | "sorted_ties_unordered" (M28) | "scalar" | "grouping"`; `[param_names]` (Python ↔ .NET names for message comparison, e.g. `subset_size = "subsetSize"`).
- `python -m difftest lint`: validates every spec against the schema, checks catalogue references exist on both sides (the oracle answers `{"op":"__catalog__"}` with its names), and checks that every `status = "implemented"` registry operator (`_operators.toml`, F06) has a spec. F09's report-only coverage command becomes this failing gate.
- Migration of existing specs is mechanical (defaults: `compose = true`, `profile = "exact"`).
- **Outcome:** one schema for all specs; drift between registry, specs and catalogues fails CI.
- **Verify:** `uv run python -m difftest lint` → `N specs OK, 0 errors`; a spec with an unknown catalogue name or a missing `[shape]` makes it exit 1.

### X01.2 Portable value and callback model v2 (testplan §7, §10)
- Values: tagged records `{"type":"record","id":"o17","fields":{...}}` (object identity observable through `id`, testplan Level 9), nested lists, `char` ↔ 1-char `str`, and **floats** with explicit rules: finite doubles transported as `repr`/round-trip strings and compared exactly; NaN/inf allowed only in specs that declare a float rule (otherwise INVALID_TEST_CASE).
- Callbacks: `difftest/catalog.toml` becomes the **single source** of the catalogue; Python builds its table from it and the oracle reads the same file at start-up, so names, arities and parameters cannot drift. New entries: `field(name)`, `args_tuple` (M31), `key_tuple(k1, k2)`, `compose(f, g)`, stateful `counter` (reset per enumeration vs per scenario, both modelled), `throws_after(n)` (raises on the n-th call), `side_effect_log`.
- **Outcome:** Level 9 (records, identity) and stateful/side-effect callbacks become expressible for every op.
- **Verify:** `uv run pytest -q tests/unit/difftest/test_values.py` (Hypothesis round-trip: Python → JSON → oracle echo → Python is identity for the whole value domain); `dotnet test difftest/oracle.Tests` (catalogue parity: every entry evaluated on a fixed table on both sides, results compared).

### X01.3 Oracle throughput
- Batched JSONL (up to 512 cases per write, streamed responses), `--jobs N` oracle processes, per-case timeout, crash isolation (a crash classifies only the in-flight case as ORACLE_ERROR, the process restarts and the batch resumes), reset of all catalogue state between cases.
- **Outcome:** the throughput needed by Tiers B and C (§17).
- **Verify:** `uv run python -m difftest bench-harness --cases 20000` reports ≥ 2,000 simple cases/s per worker on a CI runner; a test-only `crash_on` catalogue entry yields exactly one ORACLE_ERROR and all other cases MATCH.

### X01.4 Deterministic corpus (Tier A, §14) and case identity (§18)
- Corpus axes from §14: input shapes (empty, one, two, many, all equal, all different, alternating, sorted, reverse sorted, duplicates, negatives, mixed, strings, nulls), execution shapes (list/re-iterable, one-shot, counting, side-effecting, throwing source, `collection` opt-in), callback shapes (always/never, first only, last only, multiple, stateful, side effect, throws). Per operator, axes are combined with an all-pairs covering array (not the full Cartesian product), filtered by spec `requires`/`max_len`.
- Case identity: `case_id = "<op-or-pipeline>-" + blake2b(canonical_json(scenario))[:10]`, canonical JSON with sorted keys; every case carries `generator_version` and `seed`. IDs are stable across machines and runs; F09's `<op>-<index>` IDs are kept as aliases in existing regressions.
- **Outcome:** Tier A ≥ 1,500 designed cases over the implemented operators; the PR job runs the corpus for operators touched by the diff (registry/spec/source mapping) plus a fixed 10 % sample of the rest.
- **Verify:** `uv run python -m difftest run --tier corpus --emit-cases out1.jsonl` twice: `sha256sum` identical; summary `MISMATCH 0`.

### X01.5 Harness self-tests: planted defects (§22), before scaling
- `python -m difftest selftest` runs the corpus against **mutants**: Python-side monkeypatches (eager `where`, `take` off by one, `distinct` via `set` (order lost), `first` pulling one extra element, `skip` ignoring negatives, wrong exception message, selector called twice) and oracle-side response mutators (reordered values, dropped trace event, altered message). Each mutant must be killed (some case is MISMATCH); comparator unit tests cover reordered sequences, the ties profile, and each exception classification of §9.
- **Outcome:** a mutation score; the harness is demonstrably able to fail before Tiers B and C are added.
- **Verify:** `uv run python -m difftest selftest` → `mutants killed: 10/10`; the CI `difftest` job runs it (fast: corpus subset).

### X01.6 Hypothesis generation, single operator (Tier B, §12)
- Strategies derived from each spec (argument domains, value model, catalogue callbacks with drawn parameters, source kinds). Property: `observe_dotnet(s) ≈ observe_python(s)` under the spec's profile and classification rules; expected differences declared in the spec are classified, not failed.
- Settings profiles: `pr` (derandomized, ~200 examples per op, fixed seed) and `nightly` (random seed printed and recorded, budget per op from `--max-examples`, `deadline=None`). The Hypothesis example database (`.hypothesis/`) is cached in CI so known failures replay first.
- Failures: Hypothesis shrinks across the process boundary (the oracle is called per example through X01.3's persistent process); the minimal case is written to `difftest/failures/<case_id>.json` with scenario, both observations, seed, generator version and the `@reproduce_failure` blob.
- **Outcome:** Tier B ≥ 50,000 generated cases per nightly run, scaling toward 250k as runtime allows.
- **Verify:** `uv run python -m difftest run --tier generated --seed 123 --max-examples 2000` twice gives the same case-ID set; with X01.5's "take off by one" mutant enabled, the reported counterexample has ≤ 3 source elements (shrinking works).

### X01.7 Composition generator (Tier C, §13)
- Pipelines are generated from X01.1 shapes: a typed grammar where the next operator is drawn among those whose `input` matches the current `output`, respecting `requires` (orderable keys for ordering, `then_by` only after `ordered`), `cost`/`max_len` guards (combinatorics only on ≤ 6 elements), and terminals ending the chain. Lengths: short 2–3, medium 4–6, long 7–10; repeated operators allowed.
- Composition features from §13/§14: materialisation boundaries (`to_list` then continue), branching and reuse (two queries derived from one base, both enumerated; the same query enumerated twice), operators that enumerate more than once, grouping followed by projection/flattening, set operator then filter, pagination chains.
- Oracle side: each `Operators/<Op>.cs` exposes a common `Apply(IEnumerable<object>, Args) → object` adaptor so a pipeline is a fold over stages (refactor F09's per-op files once, here). Trace events gain a `stage` index.
- **Outcome:** Tier C: tens of thousands of valid pipelines per nightly run; the PR job runs a derandomized 500-pipeline sample.
- **Verify:** `uv run python -m difftest run --tier compose --seed 7 --max-examples 1000` → `MISMATCH 0`, `INVALID_TEST_CASE < 5 %`, and the report lists **pair coverage** (every shape-compatible operator pair `a → b` exercised at least once).

### X01.8 Regression capture and replay without .NET (Tier D, §15)
- `python -m difftest promote difftest/failures/<case_id>.json --root-cause "..." --status fixed|expected` writes `difftest/regressions/<case_id>.json` (scenario, frozen .NET observation, classification, root cause, expected status, seed, generator version) and appends `difftest/regressions/INDEX.toml`.
- `tests/regressions/test_difftest_regressions.py` (normal pytest run, no dotnet) loads every regression, replays the Python side and compares with the frozen .NET observation; `expected` entries assert that the documented difference still exists, so fixing it forces a conscious update of the entry.
- Regressions are never deleted (§15): a test fails if `INDEX.toml` loses an entry. The nightly job re-validates frozen observations against the live oracle to detect oracle drift after SDK or NuGet bumps.
- **Outcome:** every meaningful discrepancy becomes a permanent, dotnet-free test (Tier D).
- **Verify:** promote a planted failure from X01.5; `uv run pytest -q tests/regressions` fails with the mutant and passes without it, on a machine without the .NET SDK.

### X01.9 Nightly CI job (large fuzz budget)
- `.github/workflows/difftest-nightly.yml`: `schedule` (`cron: "17 3 * * *"`) and `workflow_dispatch` (inputs `seed`, `budget_minutes`, `tiers`, `ops`). Steps: checkout, setup-uv, `actions/setup-dotnet` (10.0.x, `global.json` pins the SDK feature band), caches (NuGet, oracle build, `.hypothesis/`), build oracle, run tiers `corpus,generated,compose` with `--jobs 4` time-boxed to 60 min, seed `inputs.seed || github.run_id`, regression re-validation (X01.8), `selftest`.
- Outputs: artifacts `difftest/out/` (results JSONL, failures, `coverage.json`); job summary with counts per classification; for new MISMATCH case IDs, open or update one GitHub issue labelled `difftest-nightly` (deduplicated by case ID, containing the `repro` command). Permissions: `contents: read`, `issues: write` only. Workflow passes F03's `zizmor` and schema checks.
- Never gates PRs (same spirit as D8). Optional matrix leg with the daily .NET SDK (`continue-on-error: true`) for runtime-main-only operators (F09 risk, README open question 2).
- **Outcome:** a scheduled, reproducible large run whose failures arrive as actionable issues.
- **Verify:** `gh workflow run difftest-nightly.yml -f budget_minutes=5 -f seed=42` → green run with artifacts; the same with `-f ops=where` on a branch carrying an X01.5 mutant (and `--issue-dry-run`) reports the issue it would open.

### X01.10 Coverage model and report (§16, §24)
- Every case is tagged with the §16 dimensions it exercises (operator, overload/variation, argument shape, boundary kind, exception, ordering, duplicates, deferred execution, re-enumeration, one-shot, side effects, enumeration counts, key-selector/comparer replacement, object/reference, composition length bucket and pair, tier). `python -m difftest coverage --json difftest/out/coverage.json` aggregates tags and classifications into the §16 summary (operators implemented / with corpus / with generated / composition-enabled / execution probes / known intentional differences / uncomparable / open mismatches) plus per-dimension counts.
- `difftest/coverage_floor.toml` ratchets minimum counts per dimension; the nightly job fails (not PRs) if a dimension drops below its floor.
- README gains a short "Verification status" section in the §24 wording, generated by `scripts/gen_docs.py` from the last committed `difftest/coverage.snapshot.json` (refreshed by a PR when it changes).
- **Outcome:** completeness is measured by dimension, not raw test count.
- **Verify:** `uv run python -m difftest coverage --json /tmp/cov.json && python -c "import json; d=json.load(open('/tmp/cov.json')); print(d['summary']['open_mismatches'])"` → `0`; lowering a floor value below the current count passes, raising it above fails.

### 3.x Command set (testplan §26 mapping)
| testplan §26 | flpit |
|---|---|
| small deterministic verification | `uv run python -m difftest run --tier smoke` (or `uv run pytest -m difftest_smoke`) |
| full deterministic suite | `uv run python -m difftest run --tier corpus` |
| generated differential run | `uv run python -m difftest run --tier generated` |
| larger fuzz run | `uv run python -m difftest run --tier fuzz --budget-minutes 60` (generated + compose, nightly profile) |
| reproduce one failure | `uv run python -m difftest repro <case_id>` or `uv run pytest tests/regressions -k <case_id>` |
The thin pytest wrapper (`tests/difftest/test_tiers.py`, markers `difftest_smoke`, `difftest_generated`, `difftest_fuzz`) is deselected by default like `benchmark`.

## 4. Tests
- Per sub-increment unit tests under `tests/unit/difftest/` (schema/lint, value round-trip, catalogue parity, case-ID stability, pipeline grammar validity, promote/replay) that need no dotnet; C# tests in `difftest/oracle.Tests` run in the CI difftest job.
- Mutation self-test (X01.5) runs in every PR difftest job; regression replay (X01.8) runs in the normal pytest job.
- Operator ports, skip categories and % ported targets: n/a (infrastructure card).

## 5. Differential harness
This card is the harness. Acceptance at X01.10: Tier A ≥ 1,500 designed cases; Tier B ≥ 50,000 generated cases per nightly run; Tier C ≥ 20,000 valid pipelines per nightly run with full shape-compatible pair coverage; Tier D replaying all promoted regressions without dotnet; 0 open MISMATCH; every EXPECTED_DIFFERENCE/UNCOMPARABLE with a reason; mutation score 100 % on the planted set.

## 6. Benchmarks
Harness throughput only (not operator benchmarks): cases/s per worker (X01.3 target ≥ 2,000 simple cases/s), PR difftest job ≤ 5 min, nightly within its 60 min budget. Recorded in each sub-increment PR.

## 7. Docs
- `difftest/README.md`: tiers, spec schema v2 reference, catalogue file, how a card adds composition support (just `[shape]`), how to reproduce, promote and triage a nightly issue (the §19 pipeline as a checklist).
- `.agents/testplan.md` §28: progress log per sub-increment.
- README: "Verification status" (X01.10), wording per §24 (no "bug-free" claims).

## 8. Expected outcomes
- Generated and composed scenarios run against .NET every night, failures reproducible from case ID + seed and promotable to dotnet-free regressions.
- A coverage report that shows what is and is not verified, per §16 dimension.
- Every future operator card gets generation and composition coverage by declaring `[shape]` in its spec.

## 9. Verification
Per sub-increment as listed in §3; end-to-end after X01.10:
```bash
uv run python -m difftest lint
uv run python -m difftest selftest                                   # mutants killed: n/n
uv run python -m difftest run --tier corpus | tail -3                # MISMATCH 0
uv run python -m difftest run --tier generated --seed 1 --max-examples 5000 | tail -3
uv run python -m difftest run --tier compose --seed 1 --max-examples 2000 | tail -3
uv run pytest -q tests/regressions tests/unit/difftest               # no dotnet required
uv run python -m difftest coverage --json /tmp/cov.json
gh workflow run difftest-nightly.yml -f budget_minutes=10           # green, artifacts uploaded
```

## 10. Definition of Done
- [ ] X01.1 to X01.10 merged in order, each with its verify step shown in the PR
- [ ] Tier volume targets of §5 met in two consecutive nightly runs
- [ ] Mutation self-test green in PR CI; regression replay green without dotnet
- [ ] Nightly workflow scheduled, least-privilege permissions, zizmor clean, issue automation tested
- [ ] Coverage report + floors + README verification status
- [ ] difftest/README and testplan §28 updated

## 11. Risks / open questions
- **Runtime budget:** Hypothesis calls the oracle per example; X01.3's persistent batched process makes this cheap, but shrinking long pipelines can be slow. Mitigation: cap pipeline length during shrinking, per-example timeouts, time-boxed nightly.
- **Oracle drift:** SDK or MoreLINQ updates change observations. Pin the SDK (`global.json`) and the NuGet version; X01.8 re-validation detects drift explicitly instead of letting it surface as random MISMATCHes.
- **Two catalogues** were the main drift risk; X01.2 removes it with one `catalog.toml`.
- **Composition validity:** a too-permissive grammar wastes budget on INVALID_TEST_CASE, a too-strict one misses interactions; the < 5 % invalid target and the pair-coverage metric keep it honest.
- **Unordered results:** only operators whose .NET semantics are genuinely unordered may use a non-exact profile (§8); the profile is declared per spec and reviewed, never applied globally.
- **Floats:** enabling float domains needs the explicit rules of X01.2; operators whose text rendering differs (M25) keep those domains as EXPECTED_DIFFERENCE.
- Open question: should the nightly also run the corpus against the oldest supported Python (3.12) and newest (3.14)? Proposed: newest only nightly, full matrix weekly.
