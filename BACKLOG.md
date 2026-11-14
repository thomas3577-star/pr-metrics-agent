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

## Before the first data pull

- Write one hypothesis per measured question, dated. Must be done before seeing any data.

## Open design decisions

- Storage: persist data between runs, or pull fresh each run (version 1 pulls fresh).
- Business hours for distributed teams.
- Governance metric (merges that bypass rules): skipped for now; likely needs admin access.
- Feature lead time: needs a Jira link.
- Deployment time: only for repos using GitHub Deployments.
- Scheduled runs with GitHub Actions.
- Repos merging over 1,000 PRs in the fetch range: pull.py stops today; would need date slicing.
- PRs with over 100 commits or files: fetched partially and flagged; full pagination if this proves common.

## To verify on the first data pull

- Default body text of GitHub's Revert button ("Reverts owner/repo#N").
- Reference repo's branch mix (default branch vs release branches).
- Reference repo's label names.
- Reference repo's generated files not matched by default noise patterns (e.g. the generated query-language parser).
- Whether GitHub's API size counts honour `linguist-generated`.
- Whether skills load in your VS Code version.
- Whether the GraphQL API can filter PRs by merged or updated time, or whether the search API with date slices is needed.
