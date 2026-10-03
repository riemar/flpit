# flpit improvement board

> Board for the roadmap: LINQ + MoreLINQ coverage, CI and release, and the agent skill/plugin.
> **One card (`.md` file) = one increment = one branch = one PR.**
> Cards are ordered by priority via their numeric prefix; the ID (e.g. `L01`) is stable even if a card is re-prioritised.

- Created: 2026-10-03, after analysing `main @ 2c88fa4` and an interview with the maintainer (decision log below).
- Upstream test oracle snapshots used for sizing:
  - `dotnet/runtime` `main @ 6f1d9331b9b477df73982a0fabedefe27f36d8a3` (`src/libraries/System.Linq/tests`)
  - `morelinq/MoreLINQ` `master @ d217ab1e8eac68247650c27e977b767dd66bcab0`. Used for API and semantics reference only; its tests are **not** copied (decision D7).

---

## 1. Current-state analysis (summary)

| Area | Finding | Addressed by |
|---|---|---|
| Runtime floor | `linq.py` imports `typing.override` (3.12+) but `requires-python = ">=3.11"`, so **importing the package fails on 3.11**. | F01 |
| Red tests | On 3.12: 1816 passed, 144 skipped, **3 failed**. Two are wall-clock asserts (`elapsed < 0.7`) in `tests/nettests/test_order_by.py::test_SortsRandomizedEnumerableCorrectly[*-1000000]`; one is `test_namespace_move.py::test_import_via_redirect`, which fails when `flp` was already imported earlier in the session (order-dependent `DeprecationWarning`). | F01 |
| CI/CD | No `.github/` at all, so no CI, no release automation, no lint. | F03, F04 |
| Duplication | Each operator is implemented on `FlpIt` and again as a delegating copy on `FlpList` (~40 pairs). `FlpList` has drifted: **`concat` is missing on `FlpList`** although the README advertises it. `rules.md` still says FlpList extends `UserList` (no longer true). | F05 |
| Argument validation | Inconsistent: `take`/`chunk` validate eagerly, `where(None)` fails lazily, `last(None)` raises `PredicateNoneError`, `SelectorNoneError` message names `keySelector` for every selector. | F05 |
| Operators present | `append, prepend, concat, any, all, where, select, select_many, take, cast, of_type, distinct, distinct_by, zip, chunk, order_by(+_descending), then_by(+_descending), group_by, aggregate, last, min, min_by, max, max_by, average/avg, sum, count, element_at, first, first_or_default, single, to_list`, plus factories `flp.it, flp.lst, flp.range, flp.repeat`. | — |
| .NET gaps | 40+ `System.Linq` methods missing (skip family, contains, reverse, *_or_default, set ops, joins, lookups, dictionaries, .NET 9/10 ops...). | Phase 1–2 |
| Ported .NET tests | 11 files (all, any, average, count, last, order_by, order_by_descending, sum, take, then_by, then_by_descending). Many implemented ops have **no ported tests** (where, select, select_many, first, single, distinct, zip, chunk, group_by, min/max, aggregate, cast, of_type, append/prepend, concat, range, repeat, to_list). | Phase 1/2 upgrades + Phase B backfill |
| Tests layout | Ad-hoc suites (`gemini_test_suite`, `luna_test_suite`, `core` with empty files, a script `perf_run_1.py`). | F02 |
| Docs | README only; docstrings are uneven (some one-liners, some none on FlpList). | F06 + every card |
| Benchmarks | `pytest-benchmark` installed; one ordering benchmark; benchmarks deselected by default (`-m 'not benchmark'`). | F07 + every card |
| Differential testing | `.agents/testplan.md` specifies a .NET oracle harness (JSON Lines); nothing is implemented. | F09 + every card |

---

## 2. Decision log (from the interview)

| # | Decision | Consequence for every card |
|---|---|---|
| D1 | **Shared operator mixin** (`_LinqOps`). Every operator is written once; `FlpList` overrides only real fast paths. Docstrings live once and are inherited (`inspect.getdoc` / IDE hovers resolve them); a CI test enforces non-empty docs. | Implement on the mixin. Add a FlpList override **only** with a measured fast path. |
| D2 | **Python >= 3.12** (3.12, 3.13, 3.14). | PEP 695 generics allowed in new code (keep style consistent with existing TypeVars until a dedicated refactor). |
| D3 | **Comparers: key-selector only.** No `IEqualityComparer`/`IComparer` objects. `*_by(key)` variants carry the comparer use-case. | Ported tests using custom comparers are rewritten with a key selector when the intent is preserved, otherwise skipped with reason `COMPARER_NOT_SUPPORTED`. |
| D4 | **Indexed overloads as suffix methods**: `where_indexed`, `select_indexed`, `select_many_indexed`, `take_while_indexed`, `skip_while_indexed`. Callback signature `(item, index)`, same as .NET. | Delivered in the same card as the base method (variations grouped). |
| D5 | **`*_or_default` use keyword `default=None`**: `first_or_default(predicate=..., *, default=None)`. Breaking change for `first_or_default` with a one-minor deprecation shim. | Overloads type the result as `TItem \| None` or `TItem \| TDefault`. |
| D6 | **Oracle = `dotnet/runtime` `main`.** Every ported file pins the upstream commit SHA. | `tests/nettests/UPSTREAM.toml` + file header. |
| D7 | **MoreLINQ (Apache-2.0): own tests only.** No copying of MoreLINQ tests or code; its docs/signatures are only a behavioural reference. The differential harness can still use the **MoreLINQ NuGet package** as a runtime oracle (no source copied). | M-cards write their own tests in `tests/unit/morelinq/`. |
| D8 | **Benchmarks**: pytest-benchmark vs native/itertools equivalent, a CI job that **runs but never gates**, tracked history (github-action-benchmark → `gh-pages`, alert comment only), and wall-clock asserts removed from unit tests. | Every card ships `tests/benchmarks/test_bench_<op>.py`. |
| D9 | **Docs = docstrings + README** (no site). Google-style docstrings with runnable `Examples` (doctests in CI), and a README operator matrix generated from the operator registry. | Every card: docstring + registry entry + regenerated README. |
| D10 | **Release on GitHub Release** (tag `vX.Y.Z`); version derived from the tag (`uv version --frozen`); `uv build` → GitHub build provenance (`actions/attest-build-provenance`) → PEP 740 attestations via Astral's preview action **`astral-sh/attest-action`** (SHA-pinned, directly above publish, same job; CLI fallback `pypi-attestations sign`) → `uv publish` (trusted publishing/OIDC; uploads `*.publish.attestation` automatically, uv ≥ 0.9.12) from the `pypi` environment with a **required reviewer**. | F04 |
| D11 | **PR gates**: pytest matrix 3.12–3.14 (ubuntu, plus windows and macOS on the newest), pyrefly strict, ruff lint + format, coverage floor. | Every card must keep them green. |
| D12 | **Plugin in this repo as marketplace** (`.claude-plugin/marketplace.json`, `plugins/flpit/`). | — |
| D13 | **Skill = SKILL.md + generated API reference + .NET/MoreLINQ/itertools → flpit translation map**. | Every card regenerates the skill references (CI checks staleness). |
| D14 | **Priority = value × dependency**: core .NET gaps, then modern .NET (9/10/main), then curated MoreLINQ, then niche. | Order of cards below. |
| D15 | **1 card = 1 PR**; cards carry status front-matter. Releases are cut manually. | — |
| D16 | **Curated MoreLINQ (~35 ops)**; skip ToDataTable, Acquire, Trace, Random*, ToArrayByIndex, Memoize, Batch (= chunk), and duplicates of .NET ops. | Phase 3/4 list. |
| D17 | **Conversions**: `to_dictionary` → `dict` (raises `DuplicateKeyError` on duplicates), `to_set` (alias `to_hash_set`) → `set`, `to_lookup` → new immutable `Lookup[TKey, TItem]`. | L18–L20. |
| D18 | **Differential harness included early** (F09); every operator card registers a harness spec and passes the differential CI job. | Every card. |
| D19 | **Test tree reorganised** (F02); nothing deleted, only moved. | — |

### Open questions, to be resolved inside the named card (each card proposes a default)
1. Keyword collision: `Except` becomes **`except_`** (PEP 8 trailing underscore) with `except_by`. Alternative: `difference`. → L23
2. FullJoin is only in runtime `main`, not in a GA SDK. The harness oracle runs on .NET 10 GA, so `full_join` is verified by ported unit tests only until GA. → N06, F09
3. `Take(Range)` / `ElementAt(Index)` map to Python `slice` / negative ints. → L10, N09
4. Rename the `range(start, count)` factory? It shadows the builtin inside `flp`; kept as-is, documented. → B07

---

## 3. Conventions (all cards)

### 3.1 API
- **Naming**: snake_case of the .NET/MoreLINQ name; Python keywords get a trailing `_` (`except_`). Builtin-shadowing method names are fine (`min`, `sum`, `reversed` is *not* used: `.reverse()` mirrors .NET).
- **Arguments**: optional args use the existing `_SENTINEL` pattern; explicitly passing `None` for a required callable raises `ArgumentNoneError(param_name)` (a `TypeError`, introduced in F05; existing `PredicateNoneError`/`SelectorNoneError` become subclasses).
- **Eager argument validation, lazy evaluation**: deferred operators validate arguments *at call time* (like .NET iterator wrappers), then do all element work lazily inside a generator wrapped by `_FactoryIterable` (re-iterable when the source is).
- **Return types**: intermediate → `FlpIt[T]` (`OrderedIt[T]` for ordering); terminal → plain value; materialisers → `FlpList` / `dict` / `set` / `Lookup`.
- **FlpList**: never mutated by LINQ operators. Overrides allowed only for O(1)/O(k) fast paths whose observable behaviour (values, exceptions, callback calls) is identical.
- **Fast paths on FlpIt for `Sequence` sources** (e.g. `take_last` slicing a `list`): allowed only if results, exceptions and callback invocation counts are identical; tests must cover both a `list` source and the `non_collection` fixture.
- **Exceptions**: reuse the existing taxonomy (`EmptySequenceError`, `NoMatchError`, `MultipleElementsError`, `MultipleMatchesError`, `SourceNoneError`, ...). New ones (F05/cards): `ArgumentNoneError(TypeError)`, `ArgumentOutOfRangeError(ValueError)`, `DuplicateKeyError(ValueError)`. Index out of range on `element_at` stays `IndexError`. Messages mirror .NET wording.
- **Typing**: `@overload` per .NET overload/variation; `pyrefly` strict must be clean; each card adds `tests/typing/test_types_<op>.py` with `typing.assert_type` checks.

### 3.2 Tests (layout after F02)
```
tests/
  unit/                 # own tests (incl. tests/unit/morelinq/<op>.py for MoreLINQ ops)
  contracts/            # registry-driven invariants: deferral, one-shot, short-circuit, no FlpList mutation
  nettests/             # ported from dotnet/runtime main; UPSTREAM.toml pins SHA per file
  typing/               # assert_type checks, run by pyrefly
  benchmarks/           # pytest-benchmark, marker `benchmark`
difftest/               # differential harness (python runner + dotnet oracle)
```
- **Porting rules (F08)**: one `test_<op>.py` per upstream `*Tests.cs`; keep the upstream test names (snake_case) for traceability; parametrize with the `flp_type` fixture (FlpIt + FlpList); every non-portable case is kept as an explicit `pytest.skip(reason=<CATEGORY>: detail)` with categories `COMPARER_NOT_SUPPORTED`, `NO_VALUE_TYPES`, `NO_SPAN_OR_ARRAY`, `NO_INDEX_RANGE_TYPE`, `INTERNAL_OPTIMIZATION`, `NO_NULLABLE_DISTINCTION`, `LONG_RUNNING`, `OTHER`. Skips are counted by `scripts/nettest_report.py` (the former `nettest_skips.py`) into the README table.
- **Contract tests**: each operator's registry entry declares `kind = intermediate|terminal|factory` and `buffering = streaming|partial|full`, plus `short_circuit = true|false`. `tests/contracts/` auto-parametrizes over the registry, so a new operator gets deferral/one-shot/short-circuit checks for free once registered.

### 3.3 Benchmarks
- `tests/benchmarks/test_bench_<op>.py`, groups `"<op>-<size>"`, sizes `1_000` and `100_000`, three variants: `flpit-FlpIt`, `flpit-FlpList`, `native` (most idiomatic stdlib/itertools equivalent, written as a reviewer would expect).
- The card states a **target ratio** (median flpit / median native). Defaults: streaming ops ≤ 1.5×, buffering ops ≤ 1.3×, terminal short-circuit ops ≤ 1.5×. Missing the target is documented in the PR, not a hard block (D8).

### 3.4 Docs
- Google-style docstring: summary line; `.NET:` (or `MoreLINQ:`) equivalence line; `Args`, `Returns`, `Raises`; `Execution:` (Deferred/Terminal, Streaming/Buffering, short-circuits, re-iterability); `Examples:` doctests (run via `pytest --doctest-modules src`).
- Registry entry in `src/flpit/_operators.toml` (F06), which drives the README operator matrix, the skill API reference and the translation map (`scripts/gen_docs.py`, checked in CI with `--check`).
- Intentional deviations go in README § "Intentional Semantic Deviations".
- `CHANGELOG.md` entry under `## [Unreleased]` (Keep a Changelog).

### 3.5 Differential harness (F09)
- Each card adds `difftest/specs/<op>.toml` (argument schema, data domains, probes) and, if needed, the C# side in `difftest/oracle/Operators/<Op>.cs` (MoreLINQ ops call the MoreLINQ NuGet package).
- The `difftest` CI job must report **0 MISMATCH** for the operator; `EXPECTED_DIFFERENCE`/`UNCOMPARABLE` entries need a reason in the spec.

---

## 4. Standard Definition of Done (referenced by every card as **DoD-std**)
- [ ] Implemented on `_LinqOps` (and FlpList fast path only if justified with a benchmark)
- [ ] `_operators.toml` entry (kind, buffering, short_circuit, dotnet/morelinq name, python equivalent, category)
- [ ] Google-style docstring with doctest examples
- [ ] Unit tests + contract tests passing (both `FlpIt` and `FlpList`)
- [ ] Upstream tests ported (L/N/B cards) **or** own behavioural tests (M cards), skips categorised
- [ ] `tests/typing/test_types_<op>.py`
- [ ] `tests/benchmarks/test_bench_<op>.py` + ratio recorded in the PR description
- [ ] `difftest/specs/<op>.toml` + oracle op; difftest job: 0 MISMATCH
- [ ] `uv run python scripts/gen_docs.py` run (README matrix, skill references, translation map)
- [ ] `CHANGELOG.md` updated
- [ ] All PR gates green (tests matrix, pyrefly, ruff, coverage floor, doctests, docs-check)

### Standard verification commands (**VERIFY-std**)
```bash
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run pyrefly check
uv run pytest -q                                   # unit + contracts + nettests + typing
uv run pytest -q --doctest-modules src
uv run pytest -q -m benchmark tests/benchmarks/test_bench_<op>.py --benchmark-group-by=group
uv run python scripts/gen_docs.py --check
uv run python -m difftest run --op <op>            # requires dotnet SDK locally; always runs in CI
```

---

## 5. Priority list

Status values: `todo`, `doing`, `review`, `done`, `dropped`. Effort: S ≤ ½ day, M ≤ 1–2 days, L > 2 days.

### Phase 0: Foundation (blocking, in order)
| # | ID | Card | Effort | Depends |
|---|---|---|---|---|
| 001 | F01 | [Python floor 3.12 + red tests](001-F01-python-floor-and-red-tests.md) | S | — |
| 002 | F02 | [Test tree reorganisation](002-F02-test-tree-reorg.md) | S | F01 |
| 003 | F03 | [CI quality gates workflow](003-F03-ci-quality-gates.md) | M | F02 |
| 004 | F04 | [Release: PyPI trusted publishing + attestations (uv)](004-F04-release-pypi-trusted-publishing.md) | M | F03 |
| 005 | F05 | [`_LinqOps` mixin + argument-validation unification](005-F05-linq-ops-mixin.md) | L | F03 |
| 006 | F06 | [Operator registry, docstring conventions, docs generator](006-F06-operator-registry-and-docs.md) | M | F05 |
| 007 | F07 | [Benchmark infrastructure + tracked history](007-F07-benchmark-infra.md) | M | F03 |
| 008 | F08 | [.NET test porting kit + registry-driven contract tests](008-F08-nettest-porting-kit.md) | M | F06 |
| 009 | F09 | [Differential harness: smallest end-to-end slice](009-F09-differential-harness-slice.md) | L | F06 |
| 010 | A01 | [Agent skill (SKILL.md + generated references)](010-A01-agent-skill.md) | M | F06 |
| 011 | A02 | [Claude plugin + marketplace in this repo](011-A02-claude-plugin-marketplace.md) | S | A01, F04 |

### Phase 1: Core .NET LINQ gaps (daily-use value)
| # | ID | Card | Effort |
|---|---|---|---|
| 012 | L01 | [skip](012-L01-skip.md) | S |
| 013 | L02 | [take_while (+ indexed)](013-L02-take-while.md) | S |
| 014 | L03 | [skip_while (+ indexed)](014-L03-skip-while.md) | S |
| 015 | L04 | [take_last](015-L04-take-last.md) | S |
| 016 | L05 | [skip_last](016-L05-skip-last.md) | S |
| 017 | L06 | [contains](017-L06-contains.md) | S |
| 018 | L07 | [first / first_or_default (D5 migration)](018-L07-first-or-default.md) | M |
| 019 | L08 | [last_or_default](019-L08-last-or-default.md) | S |
| 020 | L09 | [single / single_or_default](020-L09-single-or-default.md) | S |
| 021 | L10 | [element_at (from-end) / element_at_or_default](021-L10-element-at-or-default.md) | S |
| 022 | L11 | [reverse](022-L11-reverse.md) | S |
| 023 | L12 | [default_if_empty](023-L12-default-if-empty.md) | S |
| 024 | L13 | [flp.empty](024-L13-empty.md) | S |
| 025 | L14 | [sequence_equal](025-L14-sequence-equal.md) | S |
| 026 | L15 | [where_indexed + WhereTests backfill](026-L15-where-indexed.md) | M |
| 027 | L16 | [select_indexed + SelectTests backfill](027-L16-select-indexed.md) | M |
| 028 | L17 | [select_many overloads (result selector, indexed)](028-L17-select-many-overloads.md) | M |
| 029 | L18 | [to_dictionary](029-L18-to-dictionary.md) | M |
| 030 | L19 | [to_set / to_hash_set](030-L19-to-set.md) | S |
| 031 | L20 | [to_lookup + Lookup type](031-L20-to-lookup.md) | M |
| 032 | L21 | [union / union_by](032-L21-union.md) | M |
| 033 | L22 | [intersect / intersect_by](033-L22-intersect.md) | S |
| 034 | L23 | [except_ / except_by](034-L23-except.md) | S |
| 035 | L24 | [group_by overloads (element/result selector)](035-L24-group-by-overloads.md) | M |
| 036 | L25 | [join](036-L25-join.md) | M |
| 037 | L26 | [group_join](037-L26-group-join.md) | M |
| 038 | L27 | [min / max selector overloads + MinBy/MaxBy backfill](038-L27-min-max-overloads.md) | M |
| 039 | L28 | [aggregate result-selector overload + backfill](039-L28-aggregate-result-selector.md) | S |

### Phase 2: Modern .NET (9 / 10 / main)
| # | ID | Card | Effort |
|---|---|---|---|
| 040 | N01 | [index](040-N01-index.md) | S |
| 041 | N02 | [count_by](041-N02-count-by.md) | S |
| 042 | N03 | [aggregate_by](042-N03-aggregate-by.md) | S |
| 043 | N04 | [left_join](043-N04-left-join.md) | M |
| 044 | N05 | [right_join](044-N05-right-join.md) | M |
| 045 | N06 | [full_join](045-N06-full-join.md) | M |
| 046 | N07 | [order / order_descending](046-N07-order.md) | S |
| 047 | N08 | [zip 3-way + ZipTests backfill](047-N08-zip-three-way.md) | M |
| 048 | N09 | [take(slice) (Take(Range))](048-N09-take-slice.md) | M |
| 049 | N10 | [try_get_non_enumerated_count](049-N10-try-get-non-enumerated-count.md) | S |
| 050 | N11 | [shuffle](050-N11-shuffle.md) | S |
| 051 | N12 | [flp.sequence / flp.infinite_sequence](051-N12-sequence.md) | S |

### Phase B: Backfill .NET tests for existing operators (parallelisable, interleave freely)
| # | ID | Card | Effort |
|---|---|---|---|
| 052 | B01 | [append / prepend](052-B01-append-prepend.md) | S |
| 053 | B02 | [concat](053-B02-concat.md) | S |
| 054 | B03 | [cast](054-B03-cast.md) | S |
| 055 | B04 | [of_type](055-B04-of-type.md) | S |
| 056 | B05 | [distinct / distinct_by](056-B05-distinct.md) | S |
| 057 | B06 | [chunk](057-B06-chunk.md) | S |
| 058 | B07 | [flp.range](058-B07-range.md) | S |
| 059 | B08 | [flp.repeat](059-B08-repeat.md) | S |
| 060 | B09 | [to_list](060-B09-to-list.md) | S |

### Phase 3: Curated MoreLINQ (high value)
| # | ID | Card | Effort |
|---|---|---|---|
| 061 | M01 | [pairwise](061-M01-pairwise.md) | S |
| 062 | M02 | [window / window_left / window_right](062-M02-window.md) | M |
| 063 | M03 | [scan / scan_right](063-M03-scan.md) | S |
| 064 | M04 | [pre_scan](064-M04-pre-scan.md) | S |
| 065 | M05 | [lag](065-M05-lag.md) | S |
| 066 | M06 | [lead](066-M06-lead.md) | S |
| 067 | M07 | [segment](067-M07-segment.md) | S |
| 068 | M08 | [split](068-M08-split.md) | S |
| 069 | M09 | [group_adjacent](069-M09-group-adjacent.md) | M |
| 070 | M10 | [run_length_encode](070-M10-run-length-encode.md) | S |
| 071 | M11 | [fill_forward / fill_backward](071-M11-fill-forward-backward.md) | S |
| 072 | M12 | [pad / pad_start](072-M12-pad.md) | S |
| 073 | M13 | [interleave](073-M13-interleave.md) | S |
| 074 | M14 | [zip_longest](074-M14-zip-longest.md) | S |
| 075 | M15 | [equi_zip](075-M15-equi-zip.md) | S |
| 076 | M16 | [cartesian](076-M16-cartesian.md) | S |
| 077 | M17 | [flatten](077-M17-flatten.md) | M |
| 078 | M18 | [traverse_depth_first / traverse_breadth_first](078-M18-traverse.md) | S |
| 079 | M19 | [maxima / minima](079-M19-maxima-minima.md) | S |
| 080 | M20 | [tag_first_last](080-M20-tag-first-last.md) | S |
| 081 | M21 | [take_every](081-M21-take-every.md) | S |
| 082 | M22 | [take_until / skip_until](082-M22-take-until-skip-until.md) | S |
| 083 | M23 | [at_least / at_most / exactly / count_between](083-M23-count-bounds.md) | S |
| 084 | M24 | [starts_with / ends_with](084-M24-starts-ends-with.md) | S |
| 085 | M25 | [to_delimited_string](085-M25-to-delimited-string.md) | S |
| 086 | M26 | [for_each / consume](086-M26-for-each-consume.md) | S |

### Phase 4: Niche MoreLINQ
| # | ID | Card | Effort |
|---|---|---|---|
| 087 | M27 | [rank / rank_by](087-M27-rank.md) | S |
| 088 | M28 | [partial_sort / partial_sort_by](088-M28-partial-sort.md) | M |
| 089 | M29 | [permutations](089-M29-permutations.md) | S |
| 090 | M30 | [subsets](090-M30-subsets.md) | S |
| 091 | M31 | [fold](091-M31-fold.md) | S |

### Future / epics
| # | ID | Card |
|---|---|---|
| 092 | X01 | [Differential harness: compositions, property-based generation, full coverage](092-X01-difftest-expansion.md) |

### Dependency sketch
```
F01 → F02 → F03 ─┬→ F04 ──────────────┐
                 ├→ F05 → F06 ─┬→ F08 ─┼→ every L/N/B/M card
                 └→ F07 ───────┤  F09 ─┤
                               └→ A01 → A02 (needs F04 for versioning)
L06 contains ← L21–L23 set ops reuse the hashing helper
L20 Lookup ← L26 group_join, N04–N06 joins reuse lookup building
L15/L16 indexed pattern ← L02/L03/L17 indexed variants (either order; first one lands the helper)
```

---

## 6. Card template
See [`_template.md`](_template.md).
