---
name: pr-metrics
description: Measures a GitHub repo's PR review process (cycle time, time to merge, change failure rate proxy) over a configurable window, using defined non-vanity metrics. Use when asked for PR metrics, PR cycle time, time to merge, review flow or change failure rate for a repo.
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

Run from the workspace root. Stop at the first failing step and report the error.

If a `.venv` folder exists, use its Python instead of `python` (Windows: `.venv\Scripts\python`; Mac or Linux: `.venv/bin/python`). Never activate the environment and never change system settings such as the PowerShell execution policy.

1. **Fetch** the current and previous windows, and reconcile counts against GitHub search:
   `python .github/skills/pr-metrics/scripts/pull.py --config pr-metrics.config.yaml --out output/raw.json`
2. **Compute** the metrics:
   `python .github/skills/pr-metrics/scripts/metrics.py --config pr-metrics.config.yaml --in output/raw.json --out output/results.json`
3. **Render** the reports:
   `python .github/skills/pr-metrics/scripts/report.py --in output/results.json --out-dir output`

## Outputs

| File | Contents |
|---|---|
| `output/raw.json` | Fetched PR data, run metadata and the reconciliation result |
| `output/results.json` | Every metric per window and split, the PR rows behind each number, and data-quality flags |
| `output/report.html` | Human-readable report, primary and counter-metrics side by side |
| `output/report.xlsx` | One sheet per metric plus PR-level rows |

## Interpreting results

- Numbers come only from `output/results.json`.
- Check `data_quality` first: reconciliation status, segments flagged "too few PRs for p85", guard-adjusted PRs.
- If `reconciliation.status` is not `ok`, do not report any metric.
- Report only metrics in METRICS.md's catalogue. Questions with status "Planned" are "not yet measured".

## Errors

| Symptom | Likely cause | Action |
|---|---|---|
| 401 or 403, or "No GitHub token found" | Token missing, expired or without access | Ask the user to check the `.env` file themselves. Never open it |
| Rate limit reached | Too many API calls | Wait for the reset time the script prints, then rerun |
| Reconciliation mismatch | Incomplete fetch | Rerun step 1. If it persists, report the counts |
| Config validation error | Missing or invalid key | Show the key and the expected format |
