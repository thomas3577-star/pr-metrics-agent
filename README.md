# PR metrics agent

A GitHub Copilot custom agent and portable Agent Skill that measures a repo's pull request review process with defined, non-vanity metrics.

Every metric traces back to a goal and a question (Goal Question Metric), is paired with a counter-metric so it can't be gamed quietly, and is computed by scripts rather than by the AI. The agent orchestrates, checks the data and explains the results; it never does the arithmetic.

This project targets **Windows** (PowerShell in VS Code).

- **Metric definitions:** [METRICS.md](.github/skills/pr-metrics/references/METRICS.md)
- **Work not yet decided:** [BACKLOG.md](BACKLOG.md)

---

## Status

| Part | State |
|---|---|
| Metric definitions (METRICS.md v2) | Done |
| Agent and skill files | Done |
| `pull.py`: fetch PR data | Done, 23 automated tests |
| `metrics.py`: compute metrics | Done, 54 automated tests |
| `report.py`: HTML and Excel reports | Not started |

**Measured in v1:** time to merge, change failure rate proxy.
**Planned:** time per stage, skipped or rushed reviews, PR size, stale work (see BACKLOG.md).

---

## How it works

```
You, in Copilot Chat
        │
        ▼
Custom agent (thin) ──────────▶ GitHub MCP server (spot checks only)
  config, guardrails, narrative
        │
        ▼
Skill: pr-metrics
  SKILL.md · METRICS.md · config template
  pull.py ──▶ metrics.py ──▶ results.json ──▶ report.py ──▶ HTML + Excel
  (fetch)     (compute)                       (present)
     │
     ▼
GitHub API
```

---

## Repo layout

```
.github/
  copilot-instructions.md             Always-on rules for every Copilot agent in this repo
  agents/pr-metrics.agent.md          Thin custom agent
  skills/pr-metrics/                  Portable skill: copy this folder to reuse
    SKILL.md                          When to use, run steps
    references/METRICS.md             Metric definitions
    scripts/                          pull.py, metrics.py, report.py, requirements.txt
    assets/config.example.yaml        Config template with defaults
pr-metrics.config.yaml                Settings for the repo being measured
.env.example                          Template for .env (the token file, never committed)
tests/                                Automated tests and saved GitHub responses
requirements-dev.txt                  Packages for development and testing
BACKLOG.md                            Undecided work (not read by the agent)
output/                               Generated files (not committed)
```

---

## Setup (once)

Run every command from the project folder, in the VS Code terminal (`` Ctrl+` ``).

No activation step is needed: every command calls the project's own Python inside `.venv` directly. This avoids Windows' "running scripts is disabled" error and works on locked-down laptops.

### 1. Check Python

```
python --version
```

You need 3.10 or later.

### 2. Create the virtual environment

A virtual environment keeps these packages separate from the rest of your machine.

```
python -m venv .venv
```

### 3. Install packages

```
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

### 4. Create a GitHub token

1. On github.com: profile picture → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Name `pr-metrics`, expiration 30 days.
3. Repository access: **Public repositories (read-only)**. For a private repo, grant read access to that repo only.
4. Leave permissions unchanged and generate. Copy the token; it is shown once.

---

## Add the token to `.env` (once)

1. Copy `.env.example` to a new file named `.env` in the project folder.
2. Paste the token after `GITHUB_TOKEN=`, for example `GITHUB_TOKEN=github_pat_...`.
3. Save. `.env` is listed in `.gitignore`, so git never commits it.

> **Keep `.env` private.** It holds the token in plain text. Never commit it, attach it, or paste its contents into Copilot Chat. If the token leaks, revoke it on github.com and create a new one.

---

## Run the tests

After pulling updates, run the install command from setup step 3 again first. New packages may have been added.

```
.venv\Scripts\python -m pytest
```

Expected: `77 passed`. The tests use saved GitHub responses, so they need no token or network.

---

## Fetch PR data

```
.venv\Scripts\python .github/skills/pr-metrics/scripts/pull.py --config pr-metrics.config.yaml --out output/raw.json
```

Expected output:

```
Fetched 118 merged PRs from prometheus/prometheus (2026-10-17T05:28:11Z to 2026-11-14T05:28:11Z).
Reconciliation: ok. Truncated PRs: 0. API budget remaining: 4987.
Wrote output/raw.json
```

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 2 | Config or token problem: the message says which |
| 3 | Incomplete fetch (reconciliation mismatch): rerun |
| 4 | GitHub API error or rate limit: the message gives the reset time |

---

## Configure a different repo

Edit `pr-metrics.config.yaml`. Keys left out use the defaults in METRICS.md section 6; the full list with comments is in `assets/config.example.yaml`.

```yaml
repo: owner/name
branches: []          # empty = the repo's default branch
window_days: 28       # see METRICS.md rule 3.2
clock: calendar       # or "business"
```

Set `branches` to the branch your team's everyday PRs merge into. Usually that is `main`. If your team merges features into `develop` first, use `branches: [develop]`.

---

## Use with Copilot

1. Open this folder in VS Code with GitHub Copilot enabled.
2. In Copilot Chat, pick **pr-metrics** from the agent dropdown.
3. Ask, for example: "Run PR metrics for the configured repo."

The agent confirms the config with you, runs the skill, checks data quality and reports. It never computes numbers itself, never ranks individuals, and has read-only GitHub access.

> If you connect the GitHub MCP server, turn on its read-only mode so the agent cannot write to GitHub even by mistake.

---

## Known limits

- Only merged PRs into the configured branches are measured.
- The change failure rate is a proxy: it counts reverted PRs only and always undercounts.
- Business hours assume a single team timezone.
- The fetch stops if more than 1,000 PRs match; use a shorter window.
- Cycle time is not measured. Commit dates turned out to be unreliable. Details in BACKLOG.md.
