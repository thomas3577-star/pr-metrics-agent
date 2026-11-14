"""Tests for metrics.py, organised by METRICS.md rule. Run from the repo root: pytest

Exact-answer cases use small made-up PRs built below.
Whole-run checks use trimmed real data from three repos (tests/fixtures/real_*.json).
"""

import importlib.util
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
SCRIPT = ROOT / ".github/skills/pr-metrics/scripts/metrics.py"

spec = importlib.util.spec_from_file_location("metrics", SCRIPT)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)

# Windows used by the made-up data: previous = 1-15 Oct, current = 15-29 Oct,
# CFR evaluation = previous (14-day window, 14-day revert allowance).
META = {
    "repo": "o/r", "branches": ["main"], "run_at": "2026-10-29T00:00:00Z",
    "windows": {
        "current": {"start": "2026-10-15T00:00:00Z", "end": "2026-10-29T00:00:00Z"},
        "previous": {"start": "2026-10-01T00:00:00Z", "end": "2026-10-15T00:00:00Z"},
        "cfr_eval": {"start": "2026-10-01T00:00:00Z", "end": "2026-10-15T00:00:00Z"},
    },
}


def pr(number, merged, opened=None, title="Change", body="", author="dev", author_type="User",
       files=None, commits=None, merge_commit=None):
    return {
        "number": number, "title": title, "body": body, "url": f"https://github.com/o/r/pull/{number}",
        "author": {"login": author, "type": author_type}, "author_association": "MEMBER",
        "base_ref": "main", "created_at": opened or merged, "merged_at": merged,
        "merge_commit": merge_commit or f"{number:040x}",
        "commits": commits or [{"oid": f"{number:039x}a", "authored_date": opened or merged}],
        "commits_truncated": False,
        "files": files if files is not None else [{"path": "main.go", "additions": 5, "deletions": 0}],
        "files_truncated": False,
    }


def raw(prs, status="ok"):
    return {"meta": META, "reconciliation": {"status": status, "slices": []}, "prs": prs}


def cfg(**overrides):
    return {**metrics.DEFAULTS, **overrides}


def run(prs, **overrides):
    return metrics.compute(raw(prs), cfg(**overrides))


def row(results, number):
    return next(r for r in results["prs"] if r["number"] == number)


# ---------- Rule 3.1: who counts ----------

def test_bot_by_type_excluded():
    res = run([pr(1, "2026-10-20T00:00:00Z", author="renovate", author_type="Bot")])
    assert row(res, 1)["excluded"] == "bot"
    assert res["data_quality"]["prs_excluded"] == {"bot": 1}


def test_bot_by_config_list_excluded_case_insensitive():
    res = run([pr(1, "2026-10-20T00:00:00Z", author="Release-Helper")], bots=["release-helper"])
    assert row(res, 1)["excluded"] == "bot"


def test_deleted_author_is_kept():
    p = pr(1, "2026-10-20T00:00:00Z")
    p["author"] = {"login": None, "type": "Unknown"}
    assert row(run([p]), 1)["excluded"] is None


# ---------- Rule 3.2: windows ----------

def test_window_start_included_end_excluded():
    res = run([pr(1, "2026-10-15T00:00:00Z"), pr(2, "2026-10-29T00:00:00Z"), pr(3, "2026-10-01T00:00:00Z")])
    assert row(res, 1)["window"] == "current"
    assert row(res, 2)["excluded"] == "outside_windows"
    assert row(res, 3)["window"] == "previous"


def test_every_pr_counted_or_excluded_never_both():
    res = run([pr(1, "2026-10-20T00:00:00Z"), pr(2, "2026-09-01T00:00:00Z"),
               pr(3, "2026-10-05T00:00:00Z", author_type="Bot")])
    for r in res["prs"]:
        assert (r["window"] is None) != (r["excluded"] is None)


# ---------- Rules 3.6 and 3.7: size ----------

def test_noise_files_ignored_in_size():
    files = [{"path": "web/ui/pnpm-lock.yaml", "additions": 3000, "deletions": 0},
             {"path": "go.sum", "additions": 200, "deletions": 50},
             {"path": "api/v1/types.pb.go", "additions": 900, "deletions": 0},
             {"path": "main.go", "additions": 40, "deletions": 10}]
    assert row(run([pr(1, "2026-10-20T00:00:00Z", files=files)]), 1)["size_lines"] == 50


def test_custom_noise_pattern_from_config():
    files = [{"path": "promql/parser/generated_parser.y.go", "additions": 1400, "deletions": 0},
             {"path": "main.go", "additions": 5, "deletions": 0}]
    res = run([pr(1, "2026-10-20T00:00:00Z", files=files)],
              noise_patterns=metrics.DEFAULT_NOISE + ["**/generated_parser.y.go"])
    assert row(res, 1)["size_lines"] == 5


@pytest.mark.parametrize("lines,label", [(9, "XS"), (10, "S"), (99, "S"), (100, "M"),
                                         (399, "M"), (400, "L"), (999, "L"), (1000, "XL")])
def test_size_label_boundaries(lines, label):
    assert metrics.size_label(lines) == label


# ---------- Rules 3.3 and 4.1: time to merge ----------

def test_time_to_merge_calendar_hours():
    res = run([pr(1, "2026-10-20T12:00:00Z", opened="2026-10-18T00:00:00Z")])
    assert row(res, 1)["time_to_merge_hours"] == 60.0


BH = {"timezone": "Asia/Kolkata", "workdays": ["Mon", "Tue", "Wed", "Thu", "Fri"],
      "start": "09:00", "end": "18:00", "holidays": ["2026-10-20"]}


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_business_hours_same_day():
    # 10:00 to 15:00 IST on Thursday 15 Oct = 5 working hours
    assert metrics.business_hours(utc("2026-10-15T04:30:00Z"), utc("2026-10-15T09:30:00Z"), BH) == 5.0


def test_business_hours_skip_night_and_weekend():
    # Friday 16 Oct 17:00 IST to Monday 19 Oct 10:00 IST = 1 h Friday + 1 h Monday
    assert metrics.business_hours(utc("2026-10-16T11:30:00Z"), utc("2026-10-19T04:30:00Z"), BH) == 2.0


def test_business_hours_skip_holiday():
    # Monday 19 Oct 17:00 IST to Wednesday 21 Oct 10:00 IST; Tuesday 20 Oct is a holiday
    assert metrics.business_hours(utc("2026-10-19T11:30:00Z"), utc("2026-10-21T04:30:00Z"), BH) == 2.0


def test_business_clock_used_when_configured():
    res = run([pr(1, "2026-10-15T09:30:00Z", opened="2026-10-15T04:30:00Z")],
              clock="business", business_hours=BH)
    assert row(res, 1)["time_to_merge_hours"] == 5.0


# ---------- Rule 3.4: statistics ----------

def test_median_and_p85_match_hand_calculation():
    values = [float(h) for h in range(1, 41)]  # 40 PRs: 1..40 hours
    s = metrics.summarise(values, 30)
    assert s["median_hours"] == 20.5
    assert s["p85_hours"] == round(statistics.quantiles(values, n=100, method="inclusive")[84], 2) == 34.15


def test_under_min_sample_hides_p85():
    s = metrics.summarise([1.0, 2.0, 3.0], 30)
    assert s["median_hours"] == 2.0 and s["p85_hours"] is None and s["p85_suppressed"] is True


def test_empty_window_handled():
    s = metrics.summarise([], 30)
    assert s == {"count": 0, "median_hours": None, "p85_hours": None, "p85_suppressed": False,
                 "median_display": None, "p85_display": None}


@pytest.mark.parametrize("hours,text", [(1.14, "1.1 hours"), (47.94, "47.9 hours"),
                                        (48, "2.0 days"), (63.83, "2.7 days"), (1199.13, "50.0 days")])
def test_display_rule(hours, text):
    assert metrics.display_duration(hours) == text


def test_summary_display_values():
    s = metrics.summarise([float(h) for h in range(1, 41)], 30)
    assert s["median_display"] == "20.5 hours" and s["p85_display"] == "34.2 hours"  # 34.15 rounds up
    assert metrics.summarise([1.0], 30)["p85_display"] == "hidden (fewer than 30 PRs)"


def test_window_and_timestamp_display():
    res = run([pr(1, "2026-10-20T00:00:00Z")])
    w = res["meta"]["windows"]
    assert w["current"]["display"] == "15 Oct 2026 to 29 Oct 2026 (UTC)"
    assert w["previous"]["display"] == "1 Oct 2026 to 15 Oct 2026 (UTC)"
    assert res["metrics"]["cfr_proxy"]["evaluation_window"]["display"] == "1 Oct 2026 to 15 Oct 2026 (UTC)"
    assert res["meta"]["data_as_of_display"] == "29 Oct 2026, 00:00 UTC"


def test_cfr_rate_display():
    c = cfr_for(pr(200, "2026-10-07T00:00:00Z", title="Revert x", body="Reverts o/r#100"))
    assert c["rate_display"] == "100.0% (1 of 1 PRs reverted)"


def test_small_samples_reported_in_data_quality():
    res = run([pr(1, "2026-10-20T00:00:00Z")])
    assert "current window overall (1 PRs)" in res["data_quality"]["small_samples"]


# ---------- Rule 4.2: change failure rate proxy ----------

ORIG = "2026-10-05T00:00:00Z"  # inside the CFR evaluation window


def cfr_for(revert, *others):
    return run([pr(100, ORIG, commits=[{"oid": "abcdef1234567890" + "0" * 24, "authored_date": ORIG}],
                   merge_commit="fedcba9876543210" + "0" * 24), revert, *others])["metrics"]["cfr_proxy"]


@pytest.mark.parametrize("body", [
    "Reverts o/r#100",                                   # GitHub Revert button
    "Reverts #100, broke the build",                     # hand-written
    "Undo https://github.com/o/r/pull/100 please",       # full link
    "This reverts commit abcdef1.",                      # git revert, short commit ID
    "This reverts commit fedcba9876543210" + "0" * 24,   # git revert, merge commit ID
])
def test_revert_detected_by_each_reference_style(body):
    c = cfr_for(pr(200, "2026-10-07T00:00:00Z", title='Revert "Change"', body=body))
    assert c["failed"] == 1 and c["failed_prs"][0]["reverted_by"] == [200]


def test_revert_after_allowance_not_counted():
    c = cfr_for(pr(200, "2026-10-20T00:00:01Z", title="Revert x", body="Reverts o/r#100"))
    assert c["failed"] == 0


def test_revert_pr_not_eligible_itself():
    c = cfr_for(pr(200, "2026-10-07T00:00:00Z", title="Revert x", body="Reverts o/r#100"))
    assert c["eligible"] == 1  # only PR 100; the revert PR is excluded


def test_reverted_twice_counts_once():
    c = cfr_for(pr(200, "2026-10-07T00:00:00Z", title="Revert x", body="Reverts o/r#100"),
                pr(201, "2026-10-08T00:00:00Z", title="Revert again", body="#100"))
    assert c["failed"] == 1 and c["failed_prs"][0]["reverted_by"] == [200, 201]


def test_bot_revert_counts():
    c = cfr_for(pr(200, "2026-10-07T00:00:00Z", title="Revert x", body="Reverts o/r#100",
                   author="renovate", author_type="Bot"))
    assert c["failed"] == 1


def test_revert_word_mid_title_ignored():
    c = cfr_for(pr(200, "2026-10-07T00:00:00Z", title="fix logic when config change is reverted",
                   body="Reverts o/r#100"))
    assert c["failed"] == 0


def test_fix_pr_listed_but_not_counted():
    c = cfr_for(pr(200, "2026-10-07T00:00:00Z", title="fix: regression from #100", body="Follow-up to #100"))
    assert c["failed"] == 0
    assert [f["number"] for f in c["fix_pr_candidates"]] == [200]


def test_cfr_reports_window_and_proxy_label():
    c = cfr_for(pr(200, "2026-10-07T00:00:00Z", title="Revert x", body="Reverts o/r#100"))
    assert c["evaluation_window"]["start"] == "2026-10-01T00:00:00Z" and c["label"] == "proxy"
    assert c["rate_percent"] == 100.0


# ---------- Safety ----------

def test_reconciliation_mismatch_stops(tmp_path, monkeypatch):
    with pytest.raises(SystemExit) as e:
        metrics.compute(raw([pr(1, "2026-10-20T00:00:00Z")], status="mismatch"), cfg())
    assert e.value.code == 3


@pytest.mark.parametrize("bad", ["clock: sundial\n", "min_sample: 0\n",
                                 "clock: business\nbusiness_hours: {timezone: UTC}\n",
                                 "clock: business\nbusiness_hours: {timezone: Mars/Base, workdays: [Mon], start: '09:00', end: '18:00'}\n"])
def test_bad_config_exits_2(tmp_path, bad):
    path = tmp_path / "c.yaml"
    path.write_text(bad)
    with pytest.raises(SystemExit) as e:
        metrics.load_config(path)
    assert e.value.code == 2


def test_missing_timezone_data_gives_install_hint(tmp_path, monkeypatch, capsys):
    path = tmp_path / "c.yaml"
    path.write_text("clock: business\nbusiness_hours: {timezone: Asia/Kolkata, workdays: [Mon], "
                    "start: '09:00', end: '18:00'}\n")
    import zoneinfo
    def no_data(key):
        raise zoneinfo.ZoneInfoNotFoundError(key)
    monkeypatch.setattr(zoneinfo, "ZoneInfo", no_data)
    monkeypatch.setattr(metrics, "tzdata_installed", lambda: False)
    with pytest.raises(SystemExit) as e:
        metrics.load_config(path)
    assert e.value.code == 2
    assert "pip install -r requirements-dev.txt" in capsys.readouterr().err


# ---------- Data quality ----------

def test_top_changed_files_flag_noise():
    files = [{"path": "go.sum", "additions": 500, "deletions": 0},
             {"path": "main.go", "additions": 10, "deletions": 0}]
    top = run([pr(1, "2026-10-20T00:00:00Z", files=files)])["data_quality"]["top_changed_files"]
    assert top[0] == {"path": "go.sum", "lines": 500, "excluded_as_noise": True}
    assert top[1]["excluded_as_noise"] is False


def test_truncated_prs_split_counted_and_excluded():
    bot = pr(1, "2026-10-20T00:00:00Z", author="renovate", author_type="Bot")
    bot["files_truncated"] = True
    human = pr(2, "2026-10-21T00:00:00Z")
    human["commits_truncated"] = True
    dq = run([bot, human])["data_quality"]
    assert dq["truncated_prs"] == [2]
    assert dq["truncated_prs_excluded"] == [{"number": 1, "excluded": "bot"}]


# ---------- Whole run on real data from three repos ----------

@pytest.mark.parametrize("repo", ["prometheus", "cli", "k6"])
def test_real_data_whole_run(repo, tmp_path, monkeypatch):
    data = json.loads((FIXTURES / f"real_{repo}.json").read_text())
    res = metrics.compute(data, cfg())
    dq = res["data_quality"]
    # every PR either counted or excluded with a reason, none lost
    assert len(res["prs"]) == dq["prs_in_input"] == len(data["prs"])
    assert sum(dq["prs_counted"].values()) + sum(dq["prs_excluded"].values()) == dq["prs_in_input"]
    assert dq["prs_excluded"].get("bot", 0) >= 1 and dq["prs_excluded"].get("outside_windows", 0) >= 1
    assert all(r["time_to_merge_hours"] >= 0 and r["size_lines"] >= 0 for r in res["prs"])
    # results.json must be valid JSON end to end
    json.loads(json.dumps(res))


def test_real_prometheus_lockfiles_ignored_parser_counted():
    data = json.loads((FIXTURES / "real_prometheus.json").read_text())
    res = metrics.compute(data, cfg())
    # PR 20017: 5,269 lines in total, of which 4,606 are go.sum and pnpm-lock.yaml
    assert row(res, 20017)["size_lines"] == 5269 - 4606
    # PR 19683 touches the generated parser, which the default patterns do not catch
    files = {f["path"] for f in next(p for p in data["prs"] if p["number"] == 19683)["files"]}
    assert "promql/parser/generated_parser.y.go" in files
    assert row(res, 19683)["size_lines"] == sum(
        f["additions"] + f["deletions"] for f in next(p for p in data["prs"] if p["number"] == 19683)["files"])
