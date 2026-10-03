---
id: F03
title: CI quality gates workflow
status: todo
priority: 003
effort: M
depends_on: [F02]
upstream:
  dotnet: n/a
  morelinq: n/a
pr:
---

# F03: CI quality gates workflow

## 1. Goal
Every PR and every push to `main` is checked automatically with the gates chosen in D11: tests on 3.12–3.14 (ubuntu, plus windows/macOS on the newest), pyrefly strict, ruff lint + format, coverage floor, doctests. Everything runs through **uv**, with locked dependencies and SHA-pinned actions.

## 2. Scope
**In**
- `.github/workflows/ci.yml` (this card)
- `ruff` added to the dev group plus a `[tool.ruff]` config; a one-time `ruff format` + `ruff check --fix` commit (kept as a **separate commit** in the PR so blame stays readable; listed in `.git-blame-ignore-revs`)
- `pytest-cov` added to the dev group; `[tool.coverage]` config
- `.github/dependabot.yml` for `github-actions` (weekly) and `uv` (weekly, grouped)
- `.github/pull_request_template.md` with the DoD-std checklist (board README §4)
- README badges: CI, coverage (from the job summary), PyPI version, Python versions

**Out:** release (F04), benchmark job (F07), difftest job (F09), docs-check step (`gen_docs.py --check`, added by F06 to this workflow), plugin validation (A02).

## 3. Detailed design
### 3.1 Workflow
```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>            # v5
      - uses: astral-sh/setup-uv@<sha>          # v7, enable-cache: true
      - run: uv sync --locked --dev
      - run: uv run ruff check --output-format=github .
      - run: uv run ruff format --check .
      - run: uv run pyrefly check
      - run: uv lock --check                    # lockfile up to date

  test:
    needs: lint
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest]
        python: ["3.12", "3.13", "3.14"]
        include:
          - { os: windows-latest, python: "3.14" }
          - { os: macos-latest,   python: "3.14" }
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@<sha>
      - uses: astral-sh/setup-uv@<sha>
        with: { python-version: "${{ matrix.python }}", enable-cache: true }
      - run: uv sync --locked --dev
      - run: uv run pytest -q --cov --cov-branch --cov-report=xml --cov-report=term-missing --junitxml=junit.xml
      - run: uv run pytest -q --doctest-modules src
      - if: matrix.os == 'ubuntu-latest' && matrix.python == '3.12'
        run: |
          uv run coverage report --fail-under=95 --format=markdown >> "$GITHUB_STEP_SUMMARY"
      - if: matrix.os == 'ubuntu-latest' && matrix.python == '3.12' && github.event_name == 'pull_request'
        run: uv run --with diff-cover diff-cover coverage.xml --compare-branch=origin/${{ github.base_ref }} --fail-under=100
      - uses: actions/upload-artifact@<sha>
        if: always()
        with: { name: "junit-${{ matrix.os }}-${{ matrix.python }}", path: junit.xml }

  build:
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
      - uses: astral-sh/setup-uv@<sha>
      - run: uv build
      - run: uv run --isolated --no-project --with dist/*.whl python -c "import flpit, flp; print(flpit.__version__)"
      - run: uvx twine check --strict dist/*     # metadata/README render check

  slow:
    if: github.event_name == 'push' || contains(github.event.pull_request.labels.*.name, 'run-slow')
    runs-on: ubuntu-latest
    steps: [checkout, setup-uv, "uv sync --locked --dev", "uv run pytest -q -m slow"]

  ci-ok:            # single required status for branch protection
    if: always()
    needs: [lint, test, build]
    runs-on: ubuntu-latest
    steps:
      - run: '[[ "${{ contains(needs.*.result, ''failure'') || contains(needs.*.result, ''cancelled'') }}" == "false" ]]'
```
- **Action pinning**: every `uses:` is pinned to a full commit SHA with a `# vX` comment; Dependabot keeps them fresh.
- **Fork PRs**: `permissions: contents: read` only; no secrets are needed by CI.
- **Coverage floor**: 95 % branch coverage on `src/` (current measured: 98 % on `main @ 2c88fa4`), plus `diff-cover` at 100 % on changed lines so every new operator is fully exercised.

### 3.2 Ruff config
```toml
[tool.ruff]
line-length = 120
target-version = "py312"
src = ["src", "tests"]
[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "C4", "PIE", "RUF", "PT", "PERF"]
ignore = ["E501"]                # formatter handles length
[tool.ruff.lint.per-file-ignores]
"tests/nettests/**" = ["N802", "PT011"]   # upstream-derived test names (CamelCase), broad raises
[tool.ruff.format]
docstring-code-format = true
```
### 3.3 Coverage config
```toml
[tool.coverage.run]
source = ["flpit", "flp"]
branch = true
[tool.coverage.report]
exclude_also = ["@overload", "if TYPE_CHECKING:", "raise NotImplementedError", "\\.\\.\\."]
```
### 3.4 Branch protection (manual, documented in the PR)
`main`: require `ci-ok`, require a PR, linear history optional, block force-push.

## 4. Tests
- Open the PR, then check: all matrix jobs green; job summary shows the coverage table.
- **Negative checks** (temporary commits on the PR, then reverted):
  1. Introduce an unused import → `lint` fails with a GitHub annotation.
  2. Add an uncovered branch → `diff-cover` fails.
  3. Break the lockfile (edit pyproject only) → `uv lock --check` fails.

## 5. Differential harness
n/a (job added by F09).

## 6. Benchmarks
n/a (job added by F07).

## 7. Docs
- README badges + "Contributing" section: `uv sync`, the VERIFY-std commands.
- `.github/pull_request_template.md` = DoD-std checklist.

## 8. Expected outcomes
- PRs show one required check `ci-ok`; median CI wall time < 4 min (cache enabled).
- Style is uniform (ruff), types strict (pyrefly), coverage ≥ 95 % enforced, new code 100 % covered.

## 9. Verification
```bash
# local parity
uv sync --locked --dev
uv run ruff check . && uv run ruff format --check . && uv run pyrefly check
uv run pytest -q --cov --cov-branch --cov-report=term-missing
uv run pytest -q --doctest-modules src
uv build && uvx twine check --strict dist/*
# workflow lint
uvx zizmor .github/workflows/          # GitHub Actions security linter: 0 high findings
uvx check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/ci.yml
```
Then: the PR checks page shows lint/test(5)/build green, plus the three negative checks observed failing.

## 10. Definition of Done
- [ ] ci.yml, dependabot.yml, PR template committed
- [ ] ruff + pytest-cov in dev group; configs in pyproject; `.git-blame-ignore-revs`
- [ ] Negative checks demonstrated (links in PR)
- [ ] `zizmor` clean
- [ ] Branch protection on `main` requiring `ci-ok` (maintainer action, confirmed in PR)

## 11. Risks / open questions
- Windows path/encoding differences in doctests (e.g. `repr` of Decimal): fix in place; never skip a doctest per-OS silently.
- 3.14 free-threaded build (3.14t) not included (not chosen in D11); trivial to add as an extra matrix row later.
