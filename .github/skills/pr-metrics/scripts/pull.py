"""Fetch merged PRs for the pr-metrics skill.

Writes raw.json: run metadata, window dates, reconciliation result and one
record per merged PR. No filtering or metric logic here (see metrics.py).

Usage:
  python pull.py --config pr-metrics.config.yaml --out output/raw.json
Exit codes: 0 ok, 2 config or token error, 3 reconciliation mismatch,
4 GitHub API error.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
    import yaml
except ModuleNotFoundError as e:
    sys.exit(f"ERROR: required package '{e.name}' is missing. Run this script with the project's Python "
             f"(.venv\\Scripts\\python), or install the packages: "
             f".venv\\Scripts\\python -m pip install -r requirements-dev.txt")

VERSION = "1.0"
API = "https://api.github.com/graphql"
SEARCH_CAP = 1000
PAGE_SIZE = 25

# Defaults mirror METRICS.md section 6. Only keys pull.py needs.
DEFAULTS = {"branches": [], "window_days": 28, "revert_window_days": 14}

REPO_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) { defaultBranchRef { name } }
}"""

SEARCH_QUERY = """
query($q: String!, $cursor: String) {
  rateLimit { remaining resetAt }
  search(query: $q, type: ISSUE, first: %d, after: $cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number title body url createdAt mergedAt baseRefName authorAssociation
        author { login __typename }
        mergeCommit { oid }
        commits(first: 100) { totalCount nodes { commit { oid authoredDate } } }
        files(first: 100) { totalCount nodes { path additions deletions } }
      }
    }
  }
}""" % PAGE_SIZE


def fail(code, message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(path):
    try:
        cfg = yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        fail(2, f"cannot read config {path}: {e}")
    repo = cfg.get("repo", "")
    if not isinstance(repo, str) or repo.count("/") != 1 or repo == "owner/name":
        fail(2, "config key 'repo' must be set as owner/name")
    merged = {**DEFAULTS, **cfg}
    for key in ("window_days", "revert_window_days"):
        if not isinstance(merged[key], int) or merged[key] < 1:
            fail(2, f"config key '{key}' must be a positive whole number")
    if not isinstance(merged["branches"], list):
        fail(2, "config key 'branches' must be a list")
    return merged


def read_token(env_file=".env"):
    """GITHUB_TOKEN from the environment, else from a .env file in the working folder."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    path = Path(env_file)
    if not path.is_file():
        return None
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().removeprefix("export ").strip() == "GITHUB_TOKEN":
            return value.strip().strip('"').strip("'") or None
    return None


def graphql(session, query, variables):
    """POST a GraphQL query. One retry on GitHub's 'slow down' responses."""
    for attempt in (1, 2):
        try:
            r = session.post(API, json={"query": query, "variables": variables}, timeout=60)
        except requests.RequestException as e:
            fail(4, f"network error calling GitHub: {e}")
        if r.status_code == 401:
            fail(2, "GitHub rejected the token (401). Check GITHUB_TOKEN.")
        slow_down = r.status_code == 429 or (
            r.status_code == 403 and "rate limit" in r.text.lower())
        if slow_down and attempt == 1:
            wait = int(r.headers.get("Retry-After", "60"))
            print(f"GitHub asked to slow down; waiting {wait}s and retrying once.")
            time.sleep(wait)
            continue
        if slow_down:
            reset = r.headers.get("X-RateLimit-Reset")
            when = iso(datetime.fromtimestamp(int(reset), timezone.utc)) if reset else "unknown"
            fail(4, f"GitHub rate limit reached. Resets at {when}. Rerun after that.")
        if r.status_code == 403:
            fail(2, "GitHub refused access (403). Check the token's repo access.")
        if r.status_code != 200:
            fail(4, f"GitHub API returned HTTP {r.status_code}.")
        body = r.json()
        if body.get("errors"):
            fail(4, "GitHub API error: " + "; ".join(e.get("message", "?") for e in body["errors"]))
        return body["data"]
    fail(4, "GitHub API retry failed.")


def windows(now, window_days, revert_days):
    w, r = timedelta(days=window_days), timedelta(days=revert_days)
    win = {
        "current": (now - w, now),
        "previous": (now - 2 * w, now - w),
        "cfr_eval": (now - r - w, now - r),
    }
    start = min(s for s, _ in win.values())
    return win, (start, now)


def to_record(node):
    author = node.get("author") or {}
    commits = node["commits"]
    files = node["files"]
    return {
        "number": node["number"],
        "title": node["title"],
        "body": node.get("body") or "",
        "url": node["url"],
        "author": {"login": author.get("login"), "type": author.get("__typename", "Unknown")},
        "author_association": node["authorAssociation"],
        "base_ref": node["baseRefName"],
        "created_at": node["createdAt"],
        "merged_at": node["mergedAt"],
        "merge_commit": (node.get("mergeCommit") or {}).get("oid"),
        "commits": [{"oid": c["commit"]["oid"], "authored_date": c["commit"]["authoredDate"]}
                    for c in commits["nodes"]],
        "commits_truncated": commits["totalCount"] > len(commits["nodes"]),
        "files": files["nodes"],
        "files_truncated": files["totalCount"] > len(files["nodes"]),
    }


def fetch_branch(session, repo, branch, start, end):
    # Whole-day search widened by a day each side; exact filtering happens in metrics.py.
    d1 = (start - timedelta(days=1)).date().isoformat()
    d2 = (end + timedelta(days=1)).date().isoformat()
    q = f"repo:{repo} is:pr is:merged base:{branch} merged:{d1}..{d2}"
    prs, cursor, reported, remaining = [], None, None, None
    while True:
        data = graphql(session, SEARCH_QUERY, {"q": q, "cursor": cursor})
        search = data["search"]
        remaining = data["rateLimit"]["remaining"]
        if reported is None:
            reported = search["issueCount"]
            if reported > SEARCH_CAP:
                fail(4, f"{reported} PRs match on branch '{branch}', above GitHub's search cap "
                        f"of {SEARCH_CAP}. Reduce window_days.")
        prs += [to_record(n) for n in search["nodes"] if n]
        if not search["pageInfo"]["hasNextPage"]:
            break
        cursor = search["pageInfo"]["endCursor"]
    return q, reported, prs, remaining


def main():
    ap = argparse.ArgumentParser(description="Fetch merged PRs for pr-metrics.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    token = read_token()
    if not token:
        fail(2, "No GitHub token found. Add GITHUB_TOKEN to the .env file in the project folder.")

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}",
                            "User-Agent": f"pr-metrics-skill/{VERSION}"})

    owner, name = cfg["repo"].split("/")
    repo_data = graphql(session, REPO_QUERY, {"owner": owner, "name": name})
    if not repo_data.get("repository"):
        fail(2, f"repo {cfg['repo']} not found or not accessible with this token.")
    default_branch = repo_data["repository"]["defaultBranchRef"]["name"]
    branches = cfg["branches"] or [default_branch]

    now = datetime.now(timezone.utc).replace(microsecond=0)
    win, (fetch_start, fetch_end) = windows(now, cfg["window_days"], cfg["revert_window_days"])

    slices, by_number, remaining = [], {}, None
    for branch in branches:
        q, reported, prs, remaining = fetch_branch(session, cfg["repo"], branch, fetch_start, fetch_end)
        slices.append({"query": q, "reported": reported, "fetched": len(prs)})
        for pr in prs:
            by_number[pr["number"]] = pr

    ok = all(s["reported"] == s["fetched"] for s in slices)
    raw = {
        "meta": {
            "tool_version": VERSION,
            "repo": cfg["repo"],
            "default_branch": default_branch,
            "branches": branches,
            "run_at": iso(now),
            "windows": {k: {"start": iso(s), "end": iso(e)} for k, (s, e) in win.items()},
            "fetch_range": {"start": iso(fetch_start), "end": iso(fetch_end)},
            "config": {k: cfg[k] for k in ("window_days", "revert_window_days")},
        },
        "reconciliation": {"status": "ok" if ok else "mismatch", "slices": slices},
        "prs": sorted(by_number.values(), key=lambda p: p["merged_at"]),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(raw, indent=2))

    truncated = sum(p["commits_truncated"] or p["files_truncated"] for p in raw["prs"])
    print(f"Fetched {len(raw['prs'])} merged PRs from {cfg['repo']} "
          f"({iso(fetch_start)} to {iso(fetch_end)}).")
    print(f"Reconciliation: {raw['reconciliation']['status']}. Truncated PRs: {truncated}. "
          f"API budget remaining: {remaining}.")
    print(f"Wrote {out}")
    if not ok:
        for s in slices:
            print(f"  {s['query']}: GitHub reported {s['reported']}, fetched {s['fetched']}",
                  file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
