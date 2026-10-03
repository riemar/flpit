---
id: F07
title: Benchmark infrastructure + tracked history
status: todo
priority: 007
effort: M
depends_on: [F03]
upstream:
  dotnet: n/a
  morelinq: n/a
pr:
---

# F07: Benchmark infrastructure + tracked history

## 1. Goal
Make "always include benchmarks" cheap and meaningful (D8). Each operator card adds one small file. Benchmarks compare flpit against the idiomatic native/itertools equivalent **in the same run** (ratios are far more stable than absolute times on shared CI runners). CI runs them on every PR **without gating**, and history is tracked on `gh-pages` with alert comments on regressions.

## 2. Scope
**In**
- `tests/benchmarks/_kit.py`: shared helpers and data builders
- Convention for `tests/benchmarks/test_bench_<op>.py`
- `scripts/bench_ratio.py`: turns pytest-benchmark JSON into a ratio table (Markdown, for the job summary) plus a `customSmallerIsBetter` JSON (for history)
- `.github/workflows/bench.yml`: PR run (summary + alert comment), `main` push (history to `gh-pages`)
- Port the existing ordering benchmark and `perf_baseline.py` scenarios into the kit format
- Move the 1e6 randomized sort case from nettests (F01 removed its timing assert) into `test_bench_order_by.py`

**Out:** gating on performance (explicitly non-gating per D8); memory benchmarks (an optional `tracemalloc` peak column is mentioned as future work).

## 3. Detailed design
### 3.1 Kit
```python
# tests/benchmarks/_kit.py
SIZES = (1_000, 100_000)

def ints(n: int, seed: int = 42) -> list[int]: ...           # deterministic random ints
def records(n: int) -> list[Rec]: ...                        # dataclass rows for key-selector ops

def triplet(op: str, *, native, flp_it, flp_lst, sizes=SIZES, data=ints):
    """Returns pytest params [(variant, size, fn, payload)] with ids '<op>-<variant>-<size>'
    and benchmark group '<op>-<size>' so the three variants print side by side."""
```
A card's benchmark file is ~15 lines:
```python
@pytest.mark.parametrize(*triplet("skip",
    native=lambda xs: list(islice(xs, len(xs)//2, None)),
    flp_it=lambda xs: flp.it(xs).skip(len(xs)//2).to_list(),
    flp_lst=lambda xs: flp.lst(xs).skip(len(xs)//2).to_list()))
def test_bench(benchmark, variant, size, fn, payload):
    benchmark.group = f"skip-{size}"
    benchmark.extra_info["variant"] = variant
    benchmark(fn, payload)
```
- **Fairness rules** (reviewed in every card): build input data outside the timed function; materialize both sides the same way (`list(...)` vs `.to_list()`, the FlpList-construction overhead is documented); use the most idiomatic native form (a comprehension if that is what people write, `itertools` if faster).
- `tests/benchmarks/conftest.py` (from F02) auto-marks `benchmark`; default `pytest` runs skip them.

### 3.2 `bench_ratio.py`
Reads `--benchmark-json` output, groups by `group`, computes `median(flpit-*) / median(native)`, and emits:
- Markdown table: op | size | FlpIt × | FlpList × | target | status (✅ within target, ⚠️ above). The target comes from the registry (`bench_target`, default by `buffering`, README §3.3).
- `ratios.json` in github-action-benchmark `customSmallerIsBetter` format: `[{"name": "skip-100000 FlpIt/native", "unit": "x", "value": 1.12}, ...]`.

### 3.3 Workflow `bench.yml`
```yaml
on:
  pull_request:
    paths: ["src/**", "tests/benchmarks/**", "pyproject.toml", "uv.lock"]
  push:
    branches: [main]
permissions: { contents: read }
jobs:
  bench:
    runs-on: ubuntu-latest          # single fixed runner type + python for comparability
    permissions:
      contents: write               # only used on push to main (gh-pages)
      pull-requests: write          # alert comments on PRs
    steps:
      - checkout, setup-uv (python 3.13), uv sync --locked --dev
      - run: uv run pytest -m benchmark tests/benchmarks -q
               --benchmark-json=bench.json --benchmark-min-rounds=10 --benchmark-warmup=on
      - run: uv run python scripts/bench_ratio.py bench.json --md >> "$GITHUB_STEP_SUMMARY"
             && uv run python scripts/bench_ratio.py bench.json --json ratios.json
      - uses: benchmark-action/github-action-benchmark@<sha>
        with:
          name: flpit ratios (flpit / native)
          tool: customSmallerIsBetter
          output-file-path: ratios.json
          gh-pages-branch: gh-pages
          benchmark-data-dir-path: dev/bench
          auto-push: ${{ github.event_name == 'push' }}
          comment-on-alert: true
          alert-threshold: "130%"
          fail-on-alert: false          # D8: never gates
          github-token: ${{ secrets.GITHUB_TOKEN }}
      - upload-artifact: bench.json, ratios.json
```
- The ratio series is the primary signal; absolute timings (`tool: pytest` on `bench.json`) are pushed as a second, informational series.
- Fork PRs: the token is read-only, so the comment step degrades to job-summary only (`continue-on-error` on the action for forks).
- One-time setup: create the orphan `gh-pages` branch; enable Pages from `gh-pages` (charts at `https://andreacuneo.github.io/flp/dev/bench/`).

## 4. Tests
- `tests/unit/test_bench_kit.py`: `triplet` produces 3×len(sizes) params with the right ids and groups; `bench_ratio.py` on a fixture JSON produces the expected table and JSON (golden files).
- `uv run pytest -m benchmark tests/benchmarks --benchmark-disable` in the normal CI `test` job (each benchmark function executes once as a smoke test, so broken benchmarks fail CI even though timings never gate).

## 5. Differential harness
n/a

## 6. Benchmarks
Seed set (ported): `order_by` (levels 1/2/4/8, sizes 1e4/1e5), cached-enumeration ordering, key-selector call count, `where→select→sum` pipeline (from `perf_baseline.py`), `sum`/`average` with Decimal context overhead, 1e6 randomized sort.

## 7. Docs
- README "Performance" section: links to the gh-pages charts and explains the ratio methodology.
- CONTRIBUTING: "Writing a benchmark" (kit usage + fairness rules).

## 8. Expected outcomes
- Each PR shows a ratio table in its job summary within ~3 min.
- `main` builds a continuous history chart; regressions above 30 % produce a commit/PR comment.
- Adding a benchmark costs about 15 lines per operator.

## 9. Verification
```bash
uv run pytest -q -m benchmark tests/benchmarks --benchmark-json=/tmp/b.json
uv run python scripts/bench_ratio.py /tmp/b.json --md        # table printed
uv run pytest -q -m benchmark tests/benchmarks --benchmark-disable   # smoke (CI test job)
uv run pytest -q tests/unit/test_bench_kit.py
```
After merge: the `gh-pages` branch has `dev/bench/data.js`; the Pages URL renders charts. A deliberately slowed PR (e.g. `time.sleep(0)` loop in `skip`) receives an alert comment while CI stays green.

## 10. Definition of Done
- [ ] Kit + seed benchmarks ported
- [ ] bench_ratio.py with golden tests
- [ ] bench.yml (non-gating), gh-pages + Pages configured
- [ ] Benchmark smoke step in ci.yml test job
- [ ] README/CONTRIBUTING sections

## 11. Risks / open questions
- Runner noise: mitigated by ratios, min-rounds, and the alert-only policy. If noise still triggers false alerts, raise the threshold to 150 % instead of adding retries.
- `customSmallerIsBetter` series names must stay stable across renames; changing a benchmark id starts a new series (acceptable).
