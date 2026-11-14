# Backlog

Work not yet decided. **Not read by the agent or the scripts.** Items move into METRICS.md only once fully defined.

## Metrics to define

| Question | Proposed metric | Open points |
|---|---|---|
| Where do PRs spend the most time? | Time per stage: coding, waiting for first review, in review, waiting to merge | Stage boundaries; PRs with no draft or no review |
| Are reviews skipped or rushed? | % merged without approval; rubber-stamp rate on M+ PRs | Proposed thresholds: implied reading speed above 500 lines an hour, zero comments |
| Are PRs small enough to review well? | PR size p85; % XL | None beyond rule 3.6 |
| Is unfinished work piling up? | Open PR age p85; % abandoned | Does abandoned include open PRs inactive for N days? |
| (context) | Weekly throughput | Team-level only, never a target |
| (counter) | Review rounds | Definition of a round |

Each needs a pairing in METRICS.md section 5.

## Dropped metrics

### Cycle time

We dropped it in version 2.

**Why:** we checked three repos. On all three, people open the PR about 6 minutes after their first commit, so cycle time gave almost the same number as time to merge. And in 5 to 10% of PRs, people had rewritten their commits, which made the commit dates wrong.

| Repo | Time from first commit to PR | PRs with rewritten commits |
|---|---|---|
| prometheus/prometheus | 6 min | 10% |
| cli/cli | 6 min | 5% |
| grafana/k6 | 6 min | 6% |

**How to bring it back later:**
- **Best way:** use the ticket's start date from Jira (when it moves to "In Progress") instead of the commit date. Needs each PR linked to a ticket.
- **Fallback:** use commit dates, but skip PRs with rewritten commits.

**Not yet known:** company teams might open PRs later than public projects do.

## Before the first data pull

- Write one hypothesis per measured question, dated. Must be done before seeing any data.

## Open design decisions

- Storage: persist data between runs, or pull fresh each run (version 1 pulls fresh).
- Business hours for distributed teams.
- Governance metric (merges that bypass rules): skipped for now; likely needs admin access.
- Feature lead time: needs a Jira link.
- Deployment time: only for repos using GitHub Deployments.
- Scheduled runs with GitHub Actions.
- **Window length:** 14 days is too short for smaller repos, which have too few PRs per window. Change the default to 28 days?
- **Skill loading:** stop Copilot loading the skill during setup. Parked for now.
- Repos merging over 1,000 PRs in the fetch range: pull.py stops today; would need date slicing.
- PRs with over 100 commits or files: fetched partially and flagged; full pagination if this proves common.

## To verify on the first data pull

- **Revert button text:** still unknown. There were no reverts in the first pull.
- **Branch mix:** still unknown. Only `main` was fetched.
- **Generated files:** found one not covered by the default patterns, `promql/parser/generated_parser.y.go`. Still to decide: the API "golden" test files (`openapi_3.x_golden.yaml`).
