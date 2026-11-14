"""Compute PR metrics for the pr-metrics skill.

Reads raw.json (from pull.py) and the config, applies references/METRICS.md,
and writes results.json. No GitHub calls, no formatting, no pairings
(pairings live only in METRICS.md and are applied by report.py).

Usage:
  python metrics.py --config pr-metrics.config.yaml --in output/raw.json --out output/results.json
Exit codes: 0 ok, 2 config or input error, 3 reconciliation not ok.
"""

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime
from pathlib import Path

import pathspec
import yaml

VERSION = "1.0"

# Defaults mirror METRICS.md section 6.
DEFAULT_NOISE = [
    "**/package-lock.json", "**/yarn.lock", "**/pnpm-lock.yaml", "**/go.sum",
    "**/Cargo.lock", "**/poetry.lock", "**/*.pb.go", "**/*_generated.*",
    "**/generated/**", "vendor/**", "third_party/**", "**/__snapshots__/**", "**/*.min.js",
]
DEFAULTS = {
    "branches": [], "window_days": 28, "clock": "calendar", "business_hours": None,
    "bots": [], "noise_patterns": DEFAULT_NOISE, "min_sample": 30,
    "revert_window_days": 14, "fix_keywords": ["fix", "regression", "hotfix"],
}
SIZE_LABELS = [(10, "XS"), (100, "S"), (400, "M"), (1000, "L")]  # below limit -> label; else XL
LABEL_ORDER = ["XS", "S", "M", "L", "XL"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TOP_FILES = 15

REF_NUMBER = re.compile(r"#(\d+)\b")
REF_LINK = re.compile(r"/pull/(\d+)\b")
REF_COMMIT = re.compile(r"This reverts commit ([0-9a-f]{7,40})", re.IGNORECASE)


def fail(code, message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- config ----------

def load_config(path):
    try:
        cfg = yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        fail(2, f"cannot read config {path}: {e}")
    merged = {**DEFAULTS, **cfg}
    if merged["clock"] not in ("calendar", "business"):
        fail(2, "config key 'clock' must be 'calendar' or 'business'")
    if merged["clock"] == "business":
        bh = merged.get("business_hours") or {}
        for key in ("timezone", "workdays", "start", "end"):
            if key not in bh:
                fail(2, f"clock is 'business' but business_hours.{key} is missing")
        if any(d not in WEEKDAYS for d in bh["workdays"]):
            fail(2, f"business_hours.workdays must use {', '.join(WEEKDAYS)}")
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(bh["timezone"])
        except Exception:
            fail(2, f"unknown timezone '{bh['timezone']}' in business_hours.timezone")
    for key in ("min_sample", "revert_window_days"):
        if not isinstance(merged[key], int) or merged[key] < 1:
            fail(2, f"config key '{key}' must be a positive whole number")
    return merged


# ---------- clocks ----------

def calendar_hours(start, end):
    return (end - start).total_seconds() / 3600


def business_hours(start, end, bh):
    """Working hours between two UTC times, in the team's timezone."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(bh["timezone"])
    workdays = {WEEKDAYS.index(d) for d in bh["workdays"]}
    holidays = set(bh.get("holidays") or [])
    day_start = dtime.fromisoformat(bh["start"])
    day_end = dtime.fromisoformat(bh["end"])
    a, b = start.astimezone(tz), end.astimezone(tz)
    total, day = 0.0, a.date()
    while day <= b.date():
        if day.weekday() in workdays and day.isoformat() not in holidays:
            open_ = datetime.combine(day, day_start, tz)
            close = datetime.combine(day, day_end, tz)
            lo, hi = max(a, open_), min(b, close)
            if hi > lo:
                total += (hi - lo).total_seconds() / 3600
        day += timedelta(days=1)
    return total


# ---------- per-PR facts ----------

def noise_matcher(patterns):
    """Gitignore-style matcher. pathspec 1.x calls the style 'gitignore'; older versions 'gitwildmatch'."""
    try:
        return pathspec.PathSpec.from_lines("gitignore", patterns)
    except (KeyError, LookupError):
        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


def size_label(lines):
    for limit, label in SIZE_LABELS:
        if lines < limit:
            return label
    return "XL"


def is_bot(pr, bot_logins):
    login = (pr["author"].get("login") or "").lower()
    return pr["author"].get("type") == "Bot" or login in bot_logins


def is_revert(pr):
    return pr["title"].strip().lower().startswith("revert")


def window_of(merged, windows):
    for name in ("current", "previous"):
        s, e = windows[name]
        if s <= merged < e:
            return name
    return None


# ---------- statistics ----------

def summarise(values, min_sample):
    n = len(values)
    out = {"count": n, "median_hours": None, "p85_hours": None, "p85_suppressed": False}
    if n == 0:
        return out
    out["median_hours"] = round(statistics.median(values), 2)
    if n >= min_sample and n >= 2:
        out["p85_hours"] = round(statistics.quantiles(values, n=100, method="inclusive")[84], 2)
    else:
        out["p85_suppressed"] = True
    return out


# ---------- change failure rate proxy ----------

def revert_targets(revert_pr, sha_to_pr):
    """PR numbers a revert PR points at: '#N', '/pull/N' or 'This reverts commit <ID>'."""
    text = revert_pr["body"] or ""
    targets = {int(n) for n in REF_NUMBER.findall(text)}
    targets |= {int(n) for n in REF_LINK.findall(text)}
    for sha in REF_COMMIT.findall(text):
        sha = sha.lower()
        for full, number in sha_to_pr.items():
            if full.startswith(sha):
                targets.add(number)
    targets.discard(revert_pr["number"])
    return targets


def cfr_proxy(all_prs, eligible, cfr_window, cfg):
    allow = timedelta(days=cfg["revert_window_days"])
    sha_to_pr = {}
    for pr in all_prs:
        for c in pr["commits"]:
            sha_to_pr[c["oid"].lower()] = pr["number"]
        if pr.get("merge_commit"):
            sha_to_pr[pr["merge_commit"].lower()] = pr["number"]

    reverts = [p for p in all_prs if is_revert(p)]
    reverted_by = defaultdict(list)
    for r in reverts:
        for target in revert_targets(r, sha_to_pr):
            reverted_by[target].append(r)

    keyword = re.compile(r"\b(" + "|".join(map(re.escape, cfg["fix_keywords"])) + r")\b", re.IGNORECASE)
    failed, candidates = [], []
    for pr in eligible:
        merged = ts(pr["merged_at"])
        hits = [r["number"] for r in reverted_by.get(pr["number"], [])
                if timedelta(0) <= ts(r["merged_at"]) - merged <= allow]
        if hits:
            failed.append({"number": pr["number"], "url": pr["url"], "reverted_by": sorted(hits)})
        for other in all_prs:
            if other is pr or is_revert(other) or not keyword.search(other["title"]):
                continue
            gap = ts(other["merged_at"]) - merged
            if not (timedelta(0) <= gap <= allow):
                continue
            body = other["body"] or ""
            refs = {int(n) for n in REF_NUMBER.findall(body)} | {int(n) for n in REF_LINK.findall(body)}
            if pr["number"] in refs:
                candidates.append({"number": other["number"], "url": other["url"],
                                   "title": other["title"], "references": pr["number"]})

    n = len(eligible)
    return {
        "evaluation_window": {"start": iso(cfr_window[0]), "end": iso(cfr_window[1])},
        "eligible": n,
        "failed": len(failed),
        "rate_percent": round(100 * len(failed) / n, 1) if n else None,
        "failed_prs": failed,
        "fix_pr_candidates": candidates,
        "label": "proxy",
    }


# ---------- main computation ----------

def compute(raw, cfg):
    if raw.get("reconciliation", {}).get("status") != "ok":
        fail(3, "reconciliation is not 'ok' in raw.json; refusing to compute. Rerun pull.py.")

    meta = raw["meta"]
    windows = {k: (ts(v["start"]), ts(v["end"])) for k, v in meta["windows"].items()}
    bots = {b.lower() for b in cfg["bots"]}
    noise = noise_matcher(cfg["noise_patterns"])
    clock = (lambda a, b: business_hours(a, b, cfg["business_hours"])) \
        if cfg["clock"] == "business" else calendar_hours

    rows, excluded = [], defaultdict(int)
    by_window = {"current": [], "previous": []}
    file_lines = defaultdict(int)
    truncated = []

    for pr in raw["prs"]:
        merged, opened = ts(pr["merged_at"]), ts(pr["created_at"])
        lines = sum(f["additions"] + f["deletions"] for f in pr["files"] if not noise.match_file(f["path"]))
        row = {
            "number": pr["number"], "url": pr["url"], "title": pr["title"],
            "author": pr["author"].get("login"),
            "created_at": pr["created_at"], "merged_at": pr["merged_at"],
            "size_lines": lines, "size_label": size_label(lines),
            "time_to_merge_hours": round(clock(opened, merged), 2),
            "is_revert": is_revert(pr), "window": None, "excluded": None,
        }
        if is_bot(pr, bots):
            row["excluded"] = "bot"
        else:
            row["window"] = window_of(merged, windows)
            if row["window"] is None:
                row["excluded"] = "outside_windows"
        if row["excluded"]:
            excluded[row["excluded"]] += 1
        else:
            by_window[row["window"]].append(row)
            for f in pr["files"]:
                file_lines[f["path"]] += f["additions"] + f["deletions"]
            if pr.get("commits_truncated") or pr.get("files_truncated"):
                truncated.append(pr["number"])
        rows.append(row)

    ms = cfg["min_sample"]
    time_to_merge, small = {}, []
    for name, wrows in by_window.items():
        overall = summarise([r["time_to_merge_hours"] for r in wrows], ms)
        by_size = {lab: summarise([r["time_to_merge_hours"] for r in wrows if r["size_label"] == lab], ms)
                   for lab in LABEL_ORDER}
        time_to_merge[name] = {"overall": overall, "by_size": by_size}
        if overall["p85_suppressed"]:
            small.append(f"{name} window overall ({overall['count']} PRs)")
        small += [f"{name} window, size {lab} ({s['count']} PRs)"
                  for lab, s in by_size.items() if s["p85_suppressed"] and s["count"]]

    s, e = windows["cfr_eval"]
    eligible = [p for p in raw["prs"]
                if not is_bot(p, bots) and not is_revert(p) and s <= ts(p["merged_at"]) < e]
    cfr = cfr_proxy(raw["prs"], eligible, windows["cfr_eval"], cfg)

    top = sorted(file_lines.items(), key=lambda kv: -kv[1])[:TOP_FILES]
    return {
        "meta": {
            "tool_version": VERSION, "repo": meta["repo"], "branches": meta["branches"],
            "data_as_of": meta["run_at"], "clock": cfg["clock"],
            "windows": meta["windows"], "min_sample": ms,
        },
        "metrics": {"time_to_merge": time_to_merge, "cfr_proxy": cfr},
        "data_quality": {
            "reconciliation": raw["reconciliation"]["status"],
            "prs_in_input": len(raw["prs"]),
            "prs_counted": {k: len(v) for k, v in by_window.items()},
            "prs_excluded": dict(excluded),
            "truncated_prs": truncated,
            "small_samples": small,
            "top_changed_files": [{"path": p, "lines": n, "excluded_as_noise": noise.match_file(p)}
                                  for p, n in top],
        },
        "prs": rows,
    }


def main():
    ap = argparse.ArgumentParser(description="Compute PR metrics for pr-metrics.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    try:
        raw = json.loads(Path(args.inp).read_text())
    except (OSError, json.JSONDecodeError) as e:
        fail(2, f"cannot read input {args.inp}: {e}")

    results = compute(raw, cfg)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))

    dq = results["data_quality"]
    ttm = results["metrics"]["time_to_merge"]["current"]["overall"]
    cfr = results["metrics"]["cfr_proxy"]
    print(f"PRs counted: current {dq['prs_counted']['current']}, previous {dq['prs_counted']['previous']}. "
          f"Excluded: {dq['prs_excluded'] or 'none'}.")
    print(f"Time to merge (current): median {ttm['median_hours']}h, "
          f"p85 {ttm['p85_hours'] if ttm['p85_hours'] is not None else 'suppressed'}.")
    print(f"CFR proxy: {cfr['failed']} of {cfr['eligible']} eligible PRs reverted.")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
