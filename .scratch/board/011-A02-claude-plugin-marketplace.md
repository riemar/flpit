---
id: A02
title: Claude plugin + marketplace in this repo
status: todo
priority: 011
effort: S
depends_on: [A01, F04]
upstream:
  dotnet: n/a
  morelinq: n/a
pr:
---

# A02: Claude plugin + marketplace in this repo

## 1. Goal
Make the A01 skill installable in two commands, versioned together with the library (D12):
```bash
claude plugin marketplace add riemar/flp
claude plugin install flpit@flp
```
(in-session: `/plugin marketplace add riemar/flp`, then `/plugin install flpit@flp`). Contributors working *in* this repo get the plugin suggested automatically.

**Repositories.** The canonical home is the upstream **[`riemar/flp`](https://github.com/riemar/flp)** (PyPI `flpit` is published from there, F04). [`AndreaCuneo/flp`](https://github.com/AndreaCuneo/flp) is a private fork (GitHub `parent`/`source` = `riemar/flp`, verified via the API) used for development and review: work lands on the fork first, then is proposed upstream by PR. All user-facing references (install commands, `homepage`, `repository`, marketplace `owner`) therefore point to **upstream**; the fork is only used for pre-merge testing (§4).

## 2. Scope
**In**
```
.claude-plugin/marketplace.json            # repo root = marketplace "flp"
plugins/flpit/
  .claude-plugin/plugin.json               # plugin "flpit"
  skills/flpit/...                         # from A01
  evals/...                                # from A01
  README.md                                # what it does, install, update, uninstall
.claude/settings.json                      # project: extraKnownMarketplaces + enabledPlugins for contributors
```
- CI validation job; version-sync check; release checklist step.

**Out:** commands/hooks/MCP (not chosen); submission to the public Claude plugin directory (possible later; the manifest fields are compatible).

## 3. Detailed design
### 3.1 `marketplace.json`
```json
{
  "name": "flp",
  "owner": { "name": "riemar", "url": "https://github.com/riemar" },
  "description": "Plugins for flpit, fluent LINQ for Python",
  "plugins": [
    {
      "name": "flpit",
      "source": "./plugins/flpit",
      "description": "Find and use flpit efficiently: LINQ/MoreLINQ-style Python pipelines, C# LINQ translation, lazy-evaluation pitfalls.",
      "version": "0.3.0",
      "category": "development",
      "tags": ["python", "linq", "iterables", "functional"]
    }
  ]
}
```
### 3.2 `plugin.json`
```json
{
  "name": "flpit",
  "displayName": "flpit: fluent LINQ for Python",
  "version": "0.3.0",
  "description": "Skill for discovering and efficiently using the flpit library.",
  "author": { "name": "riemar", "url": "https://github.com/riemar" },
  "homepage": "https://github.com/riemar/flp",
  "repository": "https://github.com/riemar/flp",
  "license": "MIT",
  "keywords": ["python", "linq", "morelinq", "itertools", "lazy"]
}
```
Skills are auto-discovered from `skills/`; evals from `evals/`.

### 3.3 Versioning policy
- A pinned `version` means users stay on it until it changes. **Plugin version = latest released library version** (the skill documents released APIs, and A01 excludes planned ops).
- Release checklist (F04 `RELEASING.md`), step "after release": bump `plugin.json` + `marketplace.json` versions to the new release in the same PR that moves `pyproject` to the next `.dev0`.
- CI check `scripts/check_plugin_version.py`: both JSON versions are equal **and** equal the newest released version in `CHANGELOG.md`. A skill-only fix between releases uses a post-release suffix (`0.3.0-1`), which the check allows.

### 3.4 Contributor convenience (`.claude/settings.json`)
```json
{
  "extraKnownMarketplaces": { "flp": { "source": { "source": "directory", "path": "." } } },
  "enabledPlugins": { "flpit@flp": true }
}
```
so working on the repo dog-foods the skill from the working tree (verify exact keys against the current settings docs during implementation).

### 3.5 CI job `plugin` (in `ci.yml`, paths: `.claude-plugin/**`, `plugins/**`)
```yaml
- uses: actions/setup-node@<sha>
- run: npm i -g @anthropic-ai/claude-code@<pinned>
- run: claude plugin validate . --strict                 # marketplace
- run: claude plugin validate plugins/flpit --strict     # plugin manifest + layout
- run: uv run python scripts/check_plugin_version.py
```
No API key is needed for validation. Evals stay in the manual `plugin-eval.yml` (A01).

## 4. Tests
- CI `plugin` job green; negative check: remove `name` from plugin.json → validate fails.
- Manual install test from a scratch directory:
  1. Before the upstream merge: `claude plugin marketplace add ./` (local checkout) or `claude plugin marketplace add AndreaCuneo/flp@<branch>` (private fork: needs git credentials with access to the fork). After the upstream merge: `claude plugin marketplace add riemar/flp`.
  2. `claude plugin install flpit@flp`
  3. New session: ask "translate this C# LINQ query to Python", and check the skill is invoked (visible in the transcript) and references are read on demand.
  4. `claude plugin update flpit` after a version bump picks up the change.
  5. `claude plugin uninstall flpit` cleans up.

## 5. Differential harness
n/a

## 6. Benchmarks
n/a (eval pass rates from A01 act as the quality metric).

## 7. Docs
- `plugins/flpit/README.md` and README section "Using flpit with AI coding agents": install/update/uninstall, what the skill knows, version policy.
- RELEASING.md: version-bump step.

## 8. Expected outcomes
- Two-command install; validated manifests in CI; plugin version never drifts from the released library.
- Contributors get the skill automatically in this repo.

## 9. Verification
```bash
claude plugin validate . --strict && claude plugin validate plugins/flpit --strict
uv run python scripts/check_plugin_version.py
tmp=$(mktemp -d) && cd "$tmp" && claude plugin marketplace add /home/user/flp && claude plugin install flpit@flp -y \
  && claude plugin list | grep flpit
```

## 10. Definition of Done
- [ ] marketplace.json, plugin.json, plugin README
- [ ] `.claude/settings.json` for contributors
- [ ] CI `plugin` job + version-sync script
- [ ] Manual install/update/uninstall test documented in PR
- [ ] RELEASING.md step

## 11. Risks / open questions
- **Fork vs upstream**: if this card is merged on the fork before upstream, the marketplace on the fork works only for people with fork access (it is private). The public install path exists only once upstream `riemar/flp` carries `.claude-plugin/marketplace.json` on its default branch. Marketplace `name` stays `flp` in both, so `flpit@flp` is identical; users should not add both marketplaces (duplicate marketplace name).
- **Upstream is private** (as of 2026-10-03): `claude plugin marketplace add riemar/flp` works only for users whose git credentials can read the repo. Public distribution of the plugin requires either making `riemar/flp` public, or publishing the marketplace from a separate public repo (marketplace `source` of type `github` pointing at it). Decide before announcing the install command in the README.
- Confirm with the upstream maintainer the `owner`/`author` identity to publish (GitHub handle `riemar` is used as a placeholder for a display name).
- Plugin/marketplace schemas evolve quickly. Validation runs with a pinned CLI version that Dependabot (npm ecosystem, add to dependabot.yml) bumps.
- If users want the skill without Claude Code, the `skills/flpit/` folder is self-contained and can be copied or zipped as is.
