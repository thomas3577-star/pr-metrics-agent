---
name: pr-metrics
description: Measures a GitHub repo's PR review process (time to merge, change failure rate proxy) over a configurable window, using defined non-vanity metrics. Use when asked for PR metrics, time to merge, PR cycle time, review flow or change failure rate for a repo.
---

# PR metrics skill

Fetches PR data for a configured repo, computes the metrics defined in `references/METRICS.md`, and writes `output/results.json` plus HTML and Excel reports.

## Before you start

- **Read `references/METRICS.md` first.** It defines every metric, the common rules and the pairings. Follow it exactly.
- **Python 3.10 or later**, with dependencies installed once:
  `pip install -r .github/skills/pr-metrics/scripts/requirements.txt`
- **GitHub token** with read access to the target repo, in a `.env` file at the workspace root (`GITHUB_TOKEN=...`) or in the `GITHUB_TOKEN` environment variable. For a public repo, a fine-grained token with public read-only access is enough. **Never read, open or display `.env`.**
- **Config file** `pr-metrics.config.yaml` at the workspace root. Template: `assets/config.example.yaml`.

## Run steps

Run from the workspace root, exactly as written. Run each command on its own and check it succeeded before running the next; never join commands together. Use the project's own Python in `.venv`: on Windows `.venv\Scripts\python`, on Mac or Linux `.venv/bin/python`. Do not search for `.venv` first; file search skips it. If the command fails because `.venv` is missing, stop and tell the user to follow the README setup.

If step 1 or 2 fails, stop and report the error. If step 3 fails, the numbers in `output/results.json` are still valid; report them and say the report files were not created.

1. **Fetch** the current and previous windows, and reconcile counts against GitHub search:
   `.venv\Scripts\python .github/skills/pr-metrics/scripts/pull.py --config pr-metrics.config.yaml --out output/raw.json`
2. **Compute** the metrics:
   `.venv\Scripts\python .github/skills/pr-metrics/scripts/metrics.py --config pr-metrics.config.yaml --in output/raw.json --out output/results.json`
3. **Render** the reports:
   `.venv\Scripts\python .github/skills/pr-metrics/scripts/report.py --in output/results.json --out-dir output`

On Mac or Linux, replace `.venv\Scripts\python` with `.venv/bin/python`.

## Outputs

| File | Contents |
|---|---|
| `output/raw.json` | Fetched PR data, run metadata and the reconciliation result |
| `output/results.json` | Every metric per window and split, the PR rows behind each number, and data-quality flags |
| `output/report.html` | Human-readable report, primary and counter-metrics side by side |
| `output/report.xlsx` | One sheet per metric plus PR-level rows |

## Interpreting results

- Numbers come only from `output/results.json`.
- Check `data_quality` first: reconciliation status, segments flagged "too few PRs for p85", truncated PRs. `truncated_prs` lists counted PRs only; `truncated_prs_excluded` lists truncated PRs that were excluded (e.g. bots). `pull.py`'s printed count covers both.
- Quote durations and dates using the ready-to-display fields (`_display`, `display`), e.g. "2.7 days", "15 Oct 2026 to 14 Nov 2026 (UTC)". Never convert hours or dates yourself.
- If `reconciliation.status` is not `ok`, do not report any metric.
- Report only metrics in METRICS.md's catalogue. Questions with status "Planned" are "not yet measured".

## Errors

| Symptom | Likely cause | Action |
|---|---|---|
| 401 or 403, or "No GitHub token found" | Token missing, expired or without access | Ask the user to check the `.env` file themselves. Never open it |
| Rate limit reached | Too many API calls | Wait for the reset time the script prints, then rerun |
| Reconciliation mismatch | Incomplete fetch | Rerun step 1. If it persists, report the counts |
| Config validation error | Missing or invalid key | Show the key and the expected format |
