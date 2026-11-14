# PR metrics: definitions

Version 1 · 2026-11-14

**Purpose:** single source of truth for every PR metric. The agent and the scripts follow this file. To change what a number means, change it here first and log it in the change log.

**Rules for agents and scripts**
1. Compute and report only the metrics in the metric catalogue (section 4).
2. For any question with status "Planned", report "not yet measured". Never infer, invent or approximate a definition.
3. Never show a primary metric without its counter-metric (section 5).
4. Quote numbers only from `results.json`. Never compute them in conversation.

---

## 1. Goal

Analyse the PR review process to identify bottlenecks and risks, with respect to flow speed, review effectiveness and work hygiene, from the viewpoint of the team that owns the repo, in the context of the configured repo over a configurable window.

## 2. Questions

| Goal area | Question | Status | Metrics |
|---|---|---|---|
| Flow speed | How long does a PR take to merge? | Measured | Cycle time, Time to merge |
| Flow speed | Where do PRs spend the most time? | Planned | None yet |
| Review effectiveness | Are reviews skipped or rushed? | Planned | None yet |
| Review effectiveness | Are merged changes stable? | Measured | Change failure rate proxy |
| Work hygiene | Are PRs small enough to review well? | Planned | None yet |
| Work hygiene | Is unfinished work piling up? | Planned | None yet |

## 3. Common rules

**3.1 Population.** PRs in the configured repo, targeting the configured branches (default: the repo's default branch). Bot authors are excluded: GitHub account type "Bot", plus any login in the configured bot list.

**3.2 Windows.** Window length is `window_days` (default 14). Each run computes:
- Current window: the `window_days` days ending at the run time.
- Previous window: the `window_days` days immediately before the current window.

A PR belongs to a window by the time it was merged.

**3.3 Clock.** `calendar` (default) or `business`. Business hours use one team timezone, workdays, working hours and an optional holiday list. GitHub does not record each person's timezone, so business hours are unreliable for distributed teams.

**3.4 Statistics.** Each metric reports the median, the 85th percentile (p85) and the count. Percentiles use linear interpolation. If a segment has fewer than `min_sample` PRs (default 30), report the median and the count only, flagged "too few PRs for p85". Durations are stored in hours and displayed in days to one decimal place.

**3.5 Splits.** Every metric is also reported by:
- **Size label** (rule 3.6).
- **Author type**, from GitHub's author association: *team* = OWNER, MEMBER, COLLABORATOR; *external* = all other values.

**3.6 PR size and size labels.** PR size = lines added plus lines deleted, summed over files that do not match a noise pattern (rule 3.7).

| Label | Lines |
|---|---|
| XS | under 10 |
| S | 10 to 99 |
| M | 100 to 399 |
| L | 400 to 999 |
| XL | 1,000 or more |

"M+" means M or larger (100 lines or more). PR size here is a split dimension only, not a reported metric.

**3.7 Noise files.** Files matching `noise_patterns` are excluded from PR size. Defaults: lockfiles (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `go.sum`, `Cargo.lock`, `poetry.lock`), generated code (`*.pb.go`, `*_generated.*`, `**/generated/**`), vendored code (`vendor/**`, `third_party/**`), snapshots (`**/__snapshots__/**`), minified files (`*.min.js`).

## 4. Metric catalogue

### 4.1 Cycle time

| Item | Definition |
|---|---|
| Answers | How long does a PR take to merge? |
| Measures | First commit → merged |
| Start | Author date of the PR's earliest commit. **Guard:** if that date is more than `guard_days` (default 30) before the PR was opened, use the PR-opened time instead and flag the PR |
| End | Merged time |
| Included | PRs merged in the window, per rule 3.1 |
| Statistics | Rule 3.4, current and previous window |
| Data-quality output | Count of guard-adjusted PRs |
| Known limits | Commit dates come from authors' machines. Excludes deployment time |

### 4.2 Time to merge

| Item | Definition |
|---|---|
| Answers | How long does a PR take to merge? |
| Measures | PR opened → merged |
| Start | PR-opened time |
| End | Merged time |
| Included | PRs merged in the window, per rule 3.1 |
| Statistics | Rule 3.4, current and previous window |
| Known limits | Ignores work done before the PR was opened. Comparable with GitHub's native "time to merge" |

### 4.3 Change failure rate proxy (CFR proxy)

| Item | Definition |
|---|---|
| Answers | Are merged changes stable? |
| Measures | Share of merged PRs later reverted |
| Formula | Failed PRs ÷ eligible PRs, as a percentage, with both counts |
| Evaluation window | A window of `window_days` ending `revert_window_days` before the run time, so every eligible PR has had the full revert allowance. With the defaults (14 and 14) this equals the previous window. The report shows its dates |
| Eligible PRs | Merged in the evaluation window, per rule 3.1, excluding revert PRs |
| Revert PR | A merged PR whose title starts with "Revert" (case-insensitive) |
| Failed PR | An eligible PR referenced by a revert PR merged within `revert_window_days` (default 14) of it. A reference is either "#N" for the PR's number (as written by GitHub's Revert button) or "This reverts commit <ID>" where the ID is one of the PR's commits or its merge commit (as written by `git revert`). A PR counts once, however many reverts it has |
| Fix-PR candidates | Merged PRs within `revert_window_days` that reference an eligible PR and contain a `fix_keywords` word in the title (default: fix, regression, hotfix). Listed for review only. **Not counted in the proxy** |
| Known limits | Misses fixes made forward without a revert and failures fixed outside GitHub, so it always undercounts. Always label it "proxy" |

## 5. Pairings

A primary metric is never shown without its counter-metric.

| Primary metric | Counter-metric | Gaming it catches |
|---|---|---|
| Cycle time | CFR proxy | Going faster by cutting quality |
| Time to merge | Cycle time | Opening PRs late to look fast |
| CFR proxy | Cycle time | Going slower to avoid failures |

## 6. Config reference

| Key | Default | Meaning |
|---|---|---|
| `repo` | none (required) | owner/name |
| `branches` | repo default branch | Target branches included |
| `window_days` | 14 | Window length |
| `clock` | calendar | `calendar` or `business` |
| `business_hours` | none | timezone, workdays, start, end, holidays |
| `bots` | empty | Extra bot logins to exclude |
| `noise_patterns` | rule 3.7 list | File patterns excluded from size |
| `min_sample` | 30 | Minimum PRs for p85 |
| `guard_days` | 30 | Cycle time guard |
| `revert_window_days` | 14 | Revert allowance |
| `fix_keywords` | fix, regression, hotfix | Fix-PR candidate words |

## 7. Change log

| Date | Version | Change | Why |
|---|---|---|---|
| 2026-11-14 | 1 | Goal, questions, common rules, cycle time, time to merge, CFR proxy, pairings | First version |
