"""Render the pr-metrics reports for people.

Reads results.json (from metrics.py) and the pairings table in references/METRICS.md,
and writes an HTML report (self-contained, works offline) and an Excel workbook, named
with the repo and the data-as-of time, e.g. report-grafana-k6-2026-11-14-1220UTC.html.
No calculations: every number shown comes from results.json as a display value.
Author names are never shown, to prevent per-person rankings.

Usage:
  python report.py --in output/results.json --out-dir output
Exit codes: 0 ok, 2 input or METRICS.md error.
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font
except ModuleNotFoundError as e:
    sys.exit(f"ERROR: required package '{e.name}' is missing. Run this script with the project's Python "
             f"(.venv\\Scripts\\python), or install the packages: "
             f".venv\\Scripts\\python -m pip install -r requirements-dev.txt")

VERSION = "1.0"
DEFAULT_METRICS_DOC = Path(__file__).resolve().parent.parent / "references" / "METRICS.md"

# Names used in METRICS.md's pairings table -> keys in results.json.
METRIC_KEYS = {"time to merge": "time_to_merge", "cfr proxy": "cfr_proxy"}
METRIC_TITLES = {"time_to_merge": "Time to merge", "cfr_proxy": "Change failure rate (proxy)"}
LABEL_ORDER = ["XS", "S", "M", "L", "XL"]


def fail(code, message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


# ---------- METRICS.md ----------

def read_pairings(doc_path):
    """Pairings from METRICS.md section 'Pairings': [(primary_key, counter_key, gaming), ...]."""
    try:
        text = Path(doc_path).read_text(encoding="utf-8")
    except OSError as e:
        fail(2, f"cannot read METRICS.md at {doc_path}: {e}")
    m = re.search(r"^##\s+\d*\.?\s*Pairings\s*$(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        fail(2, "METRICS.md has no 'Pairings' section; cannot decide which metrics to show together.")
    pairs = []
    for line in m.group(1).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not line.strip().startswith("|"):
            continue
        if cells[0].lower().startswith("primary") or set(cells[0]) <= set("-: "):
            continue
        keys = []
        for name in cells[:2]:
            key = METRIC_KEYS.get(name.lower())
            if not key:
                fail(2, f"METRICS.md pairings table names an unknown metric: '{name}'.")
            keys.append(key)
        pairs.append((keys[0], keys[1], cells[2] if len(cells) > 2 else ""))
    if not pairs:
        fail(2, "METRICS.md 'Pairings' section has no rows.")
    return pairs


def metrics_version(doc_path):
    m = re.search(r"Version\s+(\d+)", Path(doc_path).read_text(encoding="utf-8"))
    return m.group(1) if m else "?"


def unique_pairs(pairs):
    """Show each pair of metrics once, keeping every 'gaming it catches' note."""
    seen, out = {}, []
    for primary, counter, gaming in pairs:
        key = frozenset((primary, counter))
        if key in seen:
            seen[key]["gaming"].append(gaming)
        else:
            seen[key] = {"primary": primary, "counter": counter, "gaming": [gaming]}
            out.append(seen[key])
    return out


# ---------- HTML ----------

CSS = """
body{font-family:Segoe UI,Arial,sans-serif;margin:2rem auto;max-width:980px;color:#222;line-height:1.5;padding:0 1rem}
h1{font-size:1.6rem;margin-bottom:.2rem}h2{font-size:1.2rem;margin-top:2rem;border-bottom:1px solid #ddd;padding-bottom:.3rem}
.muted{color:#666;font-size:.9rem}.pair{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:1rem 0}
.card{border:1px solid #ddd;border-radius:8px;padding:1rem}.card h3{margin:0 0 .5rem;font-size:1rem}
.tag{font-size:.75rem;background:#eef;color:#335;border-radius:4px;padding:1px 6px;margin-left:6px}
table{border-collapse:collapse;width:100%;font-size:.9rem;margin:.5rem 0}th,td{border-bottom:1px solid #eee;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f6f6f6}.bar{background:#7a8fd6;height:10px;border-radius:3px}.note{font-size:.85rem;color:#555}
@media print{.pair{break-inside:avoid}}
"""


def esc(x):
    return html.escape("" if x is None else str(x))


def ttm_card(res, role):
    m = res["metrics"]["time_to_merge"]
    w = res["meta"]["windows"]
    rows = "".join(
        f"<tr><td>{name.title()}<br><span class='muted'>{esc(w[name]['display'])}</span></td>"
        f"<td>{esc(m[name]['overall']['median_display'] or 'no PRs')}</td>"
        f"<td>{esc(m[name]['overall']['p85_display'] or 'no PRs')}</td>"
        f"<td>{m[name]['overall']['count']}</td></tr>"
        for name in ("current", "previous"))
    return (f"<div class='card'><h3>Time to merge<span class='tag'>{role}</span></h3>"
            f"<table><tr><th>Window</th><th>Median</th><th>p85</th><th>PRs</th></tr>{rows}</table>"
            f"<p class='note'>PR opened to merged.</p></div>")


def cfr_card(res, role):
    c = res["metrics"]["cfr_proxy"]
    return (f"<div class='card'><h3>Change failure rate (proxy)<span class='tag'>{role}</span></h3>"
            f"<p><strong>{esc(c['rate_display'])}</strong></p>"
            f"<p class='muted'>Evaluation window: {esc(c['evaluation_window']['display'])}</p>"
            f"<p class='note'>Counts merged PRs later reverted. Misses fixes made without a revert, "
            f"so it always undercounts.</p></div>")


CARDS = {"time_to_merge": ttm_card, "cfr_proxy": cfr_card}


def size_section(res):
    m = res["metrics"]["time_to_merge"]
    hours = [m[w]["by_size"][lab]["median_hours"] or 0 for w in ("current", "previous") for lab in LABEL_ORDER]
    top = max(hours) or 1
    rows = ""
    for lab in LABEL_ORDER:
        cells = ""
        for w in ("current", "previous"):
            s = m[w]["by_size"][lab]
            width = int(100 * (s["median_hours"] or 0) / top)
            cells += (f"<td>{esc(s['median_display'] or 'no PRs')} <span class='muted'>({s['count']} PRs)</span>"
                      f"<div class='bar' style='width:{width}%'></div></td>")
        rows += f"<tr><td>{lab}</td>{cells}</tr>"
    return ("<h2>Time to merge by PR size</h2>"
            "<table><tr><th>Size</th><th>Current median</th><th>Previous median</th></tr>"
            f"{rows}</table><p class='note'>Size = lines changed, ignoring lockfiles and generated files. "
            "XS under 10, S 10 to 99, M 100 to 399, L 400 to 999, XL 1,000 or more. "
            "Medians only: segments are usually too small for p85.</p>")


def cfr_section(res):
    c = res["metrics"]["cfr_proxy"]
    failed = "".join(f"<li><a href='{esc(f['url'])}'>#{f['number']}</a> reverted by "
                     f"{', '.join('#' + str(n) for n in f['reverted_by'])}</li>" for f in c["failed_prs"])
    cands = "".join(f"<li><a href='{esc(f['url'])}'>#{f['number']}</a> {esc(f['title'])} "
                    f"<span class='muted'>(references #{f['references']})</span></li>"
                    for f in c["fix_pr_candidates"])
    return ("<h2>Change failure rate details</h2>"
            f"<p>Evaluation window: {esc(c['evaluation_window']['display'])}. {esc(c['rate_display'])}.</p>"
            f"<h3>Reverted PRs</h3>{'<ul>' + failed + '</ul>' if failed else '<p>None.</p>'}"
            f"<h3>Fix-PR candidates (for review, not counted)</h3>{'<ul>' + cands + '</ul>' if cands else '<p>None.</p>'}")


def quality_section(res):
    d = res["data_quality"]
    excl = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in d["prs_excluded"].items()) or "none"
    small = "".join(f"<li>{esc(s)}</li>" for s in d["small_samples"])
    trunc_ex = ", ".join(f"#{t['number']} ({t['excluded']})" for t in d.get("truncated_prs_excluded", [])) or "none"
    files = "".join(f"<tr><td>{esc(f['path'])}</td><td>{f['lines']:,}</td>"
                    f"<td>{'Ignored (noise)' if f['excluded_as_noise'] else 'Counted'}</td></tr>"
                    for f in d["top_changed_files"])
    return ("<h2>Data quality</h2><ul>"
            f"<li>Reconciliation with GitHub: <strong>{esc(d['reconciliation'])}</strong></li>"
            f"<li>PRs fetched: {d['prs_in_input']}. Counted: current {d['prs_counted']['current']}, "
            f"previous {d['prs_counted']['previous']}. Excluded: {esc(excl)}.</li>"
            f"<li>Truncated PRs counted: {', '.join('#' + str(n) for n in d['truncated_prs']) or 'none'}. "
            f"Excluded: {esc(trunc_ex)}.</li></ul>"
            f"<h3>Too few PRs for p85</h3>{'<ul>' + small + '</ul>' if small else '<p>None.</p>'}"
            "<h3>Files with the most lines changed</h3>"
            f"<table><tr><th>File</th><th>Lines</th><th>In PR size</th></tr>{files}</table>"
            "<p class='note'>Generated or lock files marked 'Counted' may need adding to the noise patterns.</p>")


def pr_section(res):
    rows = "".join(
        f"<tr><td><a href='{esc(r['url'])}'>#{r['number']}</a></td><td>{esc(r['title'])}</td>"
        f"<td>{r['window']}</td><td>{r['size_label']} ({r['size_lines']:,})</td>"
        f"<td>{esc(r['time_to_merge_display'])}</td></tr>"
        for r in sorted(res["prs"], key=lambda r: r["merged_at"], reverse=True) if r["window"])
    return ("<h2>PRs counted</h2><table><tr><th>PR</th><th>Title</th><th>Window</th><th>Size</th>"
            f"<th>Time to merge</th></tr>{rows}</table>")


def render_html(res, pairs, version):
    meta = res["meta"]
    pair_html = ""
    for p in unique_pairs(pairs):
        notes = " ".join(f"{esc(g)}." for g in p["gaming"] if g)
        pair_html += (f"<div class='pair'>{CARDS[p['primary']](res, 'primary')}"
                      f"{CARDS[p['counter']](res, 'counter-metric')}</div>"
                      f"<p class='note'>Shown together so one cannot be gamed unseen: {notes}</p>")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>PR metrics: {esc(meta['repo'])}</title>
<style>{CSS}</style></head><body>
<h1>PR metrics: {esc(meta['repo'])}</h1>
<p class="muted">Branches: {esc(', '.join(meta['branches']))} &middot; Current window: {esc(meta['windows']['current']['display'])}
&middot; Previous window: {esc(meta['windows']['previous']['display'])} &middot; Data as of {esc(meta['data_as_of_display'])}
&middot; Clock: {esc(meta['clock'])}</p>
<h2>Speed and stability</h2>{pair_html}
{size_section(res)}
{cfr_section(res)}
{quality_section(res)}
{pr_section(res)}
<p class="muted">Generated by pr-metrics report.py {VERSION}, using METRICS.md version {esc(version)}.
Team-level report: no individual names are shown.</p>
</body></html>"""


# ---------- Excel ----------

def sheet(wb, title, header, rows, first=False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    for i, col in enumerate(header, start=1):
        width = max([len(str(col))] + [len(str(r[i - 1])) for r in rows if i - 1 < len(r)])
        ws.column_dimensions[ws.cell(1, i).column_letter].width = min(width + 2, 70)


def render_xlsx(res, pairs, path):
    wb = Workbook()
    meta, m = res["meta"], res["metrics"]
    ttm, cfr, d = m["time_to_merge"], m["cfr_proxy"], res["data_quality"]
    summary = [["Repo", meta["repo"]], ["Current window", meta["windows"]["current"]["display"]],
               ["Previous window", meta["windows"]["previous"]["display"]],
               ["Data as of", meta["data_as_of_display"]], ["", ""]]
    for w in ("current", "previous"):
        o = ttm[w]["overall"]
        summary.append([f"Time to merge, {w}: median", o["median_display"] or "no PRs"])
        summary.append([f"Time to merge, {w}: p85", o["p85_display"] or "no PRs"])
        summary.append([f"Time to merge, {w}: PRs", o["count"]])
    summary += [["Change failure rate (proxy)", cfr["rate_display"]],
                ["CFR evaluation window", cfr["evaluation_window"]["display"]], ["", ""]]
    summary += [[f"Pairing: {METRIC_TITLES[p]} shown with", METRIC_TITLES[c]] for p, c, _ in pairs]
    sheet(wb, "Summary", ["Item", "Value"], summary, first=True)

    sheet(wb, "By size", ["Size", "Current median", "Current PRs", "Previous median", "Previous PRs"],
          [[lab, ttm["current"]["by_size"][lab]["median_display"] or "no PRs", ttm["current"]["by_size"][lab]["count"],
            ttm["previous"]["by_size"][lab]["median_display"] or "no PRs", ttm["previous"]["by_size"][lab]["count"]]
           for lab in LABEL_ORDER])

    sheet(wb, "CFR", ["Type", "PR", "Link", "Detail"],
          [["Reverted", f["number"], f["url"], "reverted by " + ", ".join(map(str, f["reverted_by"]))]
           for f in cfr["failed_prs"]] +
          [["Fix-PR candidate (not counted)", f["number"], f["url"], f"{f['title']} (references #{f['references']})"]
           for f in cfr["fix_pr_candidates"]])

    dq = [["Reconciliation", d["reconciliation"]], ["PRs fetched", d["prs_in_input"]],
          ["Counted, current", d["prs_counted"]["current"]], ["Counted, previous", d["prs_counted"]["previous"]]]
    dq += [[f"Excluded: {k.replace('_', ' ')}", n] for k, n in d["prs_excluded"].items()]
    dq += [["Truncated (counted)", ", ".join(map(str, d["truncated_prs"])) or "none"],
           ["Truncated (excluded)", ", ".join(f"{t['number']} ({t['excluded']})"
                                              for t in d.get("truncated_prs_excluded", [])) or "none"]]
    dq += [["Too few PRs for p85", s] for s in d["small_samples"]]
    dq += [[f"Top changed file ({'ignored' if f['excluded_as_noise'] else 'counted'})", f"{f['path']}: {f['lines']}"]
           for f in d["top_changed_files"]]
    sheet(wb, "Data quality", ["Item", "Value"], dq)

    sheet(wb, "PRs", ["PR", "Link", "Title", "Window", "Excluded because", "Size label", "Size (lines)",
                      "Time to merge", "Time to merge (hours)", "Is revert", "Opened", "Merged"],
          [[r["number"], r["url"], r["title"], r["window"] or "", r["excluded"] or "", r["size_label"],
            r["size_lines"], r["time_to_merge_display"], r["time_to_merge_hours"], "yes" if r["is_revert"] else "",
            r["created_at"], r["merged_at"]] for r in res["prs"]])
    wb.save(path)


def report_basename(res):
    """report-<owner>-<repo>-<YYYY-MM-DD>-<HHMM>UTC, from the data-as-of time (Windows-safe, sorts by date)."""
    repo = re.sub(r"[^A-Za-z0-9._-]+", "-", res["meta"]["repo"].replace("/", "-"))
    stamp = res["meta"]["data_as_of"]  # e.g. 2026-11-14T12:20:31Z
    return f"report-{repo}-{stamp[:10]}-{stamp[11:13]}{stamp[14:16]}UTC"


def main():
    ap = argparse.ArgumentParser(description="Render pr-metrics reports.")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--metrics-doc", default=str(DEFAULT_METRICS_DOC))
    args = ap.parse_args()

    try:
        res = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        fail(2, f"cannot read input {args.inp}: {e}")
    pairs = read_pairings(args.metrics_doc)
    version = metrics_version(args.metrics_doc)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = report_basename(res)
    html_path, xlsx_path = out / f"{base}.html", out / f"{base}.xlsx"
    html_path.write_text(render_html(res, pairs, version), encoding="utf-8")
    render_xlsx(res, pairs, xlsx_path)
    print(f"Wrote {html_path}")
    print(f"Wrote {xlsx_path}")


if __name__ == "__main__":
    main()
