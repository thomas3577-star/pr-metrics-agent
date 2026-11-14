"""Tests for report.py. Run from the repo root: pytest"""

import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
SCRIPTS = ROOT / ".github/skills/pr-metrics/scripts"
METRICS_DOC = ROOT / ".github/skills/pr-metrics/references/METRICS.md"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


report = load("report")
metrics = load("metrics")


@pytest.fixture
def results():
    """Real results computed from the trimmed Prometheus data, plus a hostile title and a known author."""
    data = json.loads((FIXTURES / "real_prometheus.json").read_text())
    res = metrics.compute(data, dict(metrics.DEFAULTS))
    counted = next(r for r in res["prs"] if r["window"])
    counted["title"] = "<script>alert(1)</script> & co"
    counted["author"] = "secret-developer-name"
    return res


def render(results, tmp_path, doc=METRICS_DOC):
    pairs = report.read_pairings(doc)
    html = report.render_html(results, pairs, report.metrics_version(doc))
    xlsx = tmp_path / "report.xlsx"
    report.render_xlsx(results, pairs, xlsx)
    return html, openpyxl.load_workbook(xlsx)


# ---------- pairings come only from METRICS.md ----------

def test_pairings_read_from_metrics_md():
    pairs = report.read_pairings(METRICS_DOC)
    assert {(p, c) for p, c, _ in pairs} == {("time_to_merge", "cfr_proxy"), ("cfr_proxy", "time_to_merge")}


def test_pair_shown_once_with_both_notes():
    pairs = report.unique_pairs(report.read_pairings(METRICS_DOC))
    assert len(pairs) == 1 and len(pairs[0]["gaming"]) == 2


def test_missing_pairings_section_stops(tmp_path):
    doc = tmp_path / "METRICS.md"
    doc.write_text("# Metrics\n\n## 4. Metric catalogue\nnothing here\n")
    with pytest.raises(SystemExit) as e:
        report.read_pairings(doc)
    assert e.value.code == 2


def test_unknown_metric_in_pairings_stops(tmp_path):
    doc = tmp_path / "METRICS.md"
    doc.write_text("## 5. Pairings\n\n| Primary metric | Counter-metric | Gaming |\n|---|---|---|\n"
                   "| Lines of code | CFR proxy | x |\n")
    with pytest.raises(SystemExit) as e:
        report.read_pairings(doc)
    assert e.value.code == 2


# ---------- HTML ----------

def test_html_shows_display_values_and_windows(results, tmp_path):
    html, _ = render(results, tmp_path)
    m = results["metrics"]
    for value in (m["time_to_merge"]["current"]["overall"]["median_display"],
                  m["cfr_proxy"]["rate_display"],
                  results["meta"]["windows"]["current"]["display"],
                  results["meta"]["data_as_of_display"]):
        assert value in html


def test_html_shows_primary_beside_counter(results, tmp_path):
    html, _ = render(results, tmp_path)
    pair = html.split("<div class='pair'>")[1].split("</div></div>")[0]
    assert "Time to merge" in pair and "Change failure rate (proxy)" in pair


def test_html_hidden_p85_text(results, tmp_path):
    results["metrics"]["time_to_merge"]["previous"]["overall"]["p85_display"] = "hidden (fewer than 30 PRs)"
    html, _ = render(results, tmp_path)
    assert "hidden (fewer than 30 PRs)" in html


def test_html_escapes_titles(results, tmp_path):
    html, _ = render(results, tmp_path)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_is_self_contained(results, tmp_path):
    html, _ = render(results, tmp_path)
    assert "<script src" not in html and "<link" not in html


# ---------- no individual names anywhere ----------

def test_no_author_names_in_html_or_excel(results, tmp_path):
    html, wb = render(results, tmp_path)
    assert "secret-developer-name" not in html
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            assert "secret-developer-name" not in [str(v) for v in row]
            assert "Author" not in [str(v) for v in row]


# ---------- Excel ----------

def test_excel_sheets(results, tmp_path):
    _, wb = render(results, tmp_path)
    assert wb.sheetnames == ["Summary", "By size", "CFR", "Data quality", "PRs"]


def test_excel_prs_include_excluded_with_reason(results, tmp_path):
    _, wb = render(results, tmp_path)
    rows = list(wb["PRs"].iter_rows(values_only=True))
    header, body = rows[0], rows[1:]
    reasons = {r[header.index("Excluded because")] for r in body}
    assert len(body) == len(results["prs"])
    assert {"bot", "outside_windows"} <= reasons


def test_excel_summary_uses_display_values(results, tmp_path):
    _, wb = render(results, tmp_path)
    values = [r[1] for r in wb["Summary"].iter_rows(values_only=True)]
    assert results["metrics"]["cfr_proxy"]["rate_display"] in values
    assert results["meta"]["windows"]["previous"]["display"] in values


# ---------- whole run on all three repos ----------

@pytest.mark.parametrize("repo", ["prometheus", "cli", "k6"])
def test_main_writes_both_files(repo, tmp_path, monkeypatch):
    data = json.loads((FIXTURES / f"real_{repo}.json").read_text())
    res_path = tmp_path / "results.json"
    res_path.write_text(json.dumps(metrics.compute(data, dict(metrics.DEFAULTS))))
    monkeypatch.setattr("sys.argv", ["report.py", "--in", str(res_path), "--out-dir", str(tmp_path / "out")])
    report.main()
    res = json.loads(res_path.read_text())
    base = report.report_basename(res)
    assert (tmp_path / "out" / f"{base}.html").stat().st_size > 1000
    assert (tmp_path / "out" / f"{base}.xlsx").stat().st_size > 1000


def test_report_filename_has_repo_and_data_time():
    res = {"meta": {"repo": "grafana/k6", "data_as_of": "2026-11-14T12:20:31Z"}}
    assert report.report_basename(res) == "report-grafana-k6-2026-11-14-1220UTC"
