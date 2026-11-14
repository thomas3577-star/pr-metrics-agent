# Copilot instructions for this repo

These rules apply to every Copilot chat and agent in this repo.

## Python
- This repo is used on Windows with PowerShell.
- Use the project's virtual environment Python directly: `.venv\Scripts\python`.
- Never activate the virtual environment, and never change system settings such as the PowerShell execution policy.
- Set up for running only (when asked to set up the project to run the agent): if `.venv` does not exist, create it with `python -m venv .venv`; then install with `.venv\Scripts\python -m pip install -r .github\skills\pr-metrics\scripts\requirements.txt`.
- Set up for development and testing (when asked to set up for development, or to run the tests): as above, but install with `.venv\Scripts\python -m pip install -r requirements-dev.txt`.
- Run tests with `.venv\Scripts\python -m pytest`.

## Secrets
- Never open, read, print or edit `.env`. It holds the GitHub token. To check it exists, test only whether the file is present.

## Scope
- Run steps are in `README.md`; development steps and exact commands are in `MAINTAIN.md`. Metric definitions are in `.github/skills/pr-metrics/references/METRICS.md`. Never change metric definitions without being asked.
