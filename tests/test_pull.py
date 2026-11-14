"""Offline tests for pull.py. Run from the repo root: pytest"""

import copy
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
SCRIPT = ROOT / ".github/skills/pr-metrics/scripts/pull.py"
TOKEN = "test-token-must-never-print"

spec = importlib.util.spec_from_file_location("pull", SCRIPT)
pull = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pull)


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.text = json.dumps(self._body)
        self.headers = headers or {}

    def json(self):
        return self._body


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Run pull.main() with fake GitHub responses. Returns (exit_code, raw_or_None, output)."""

    def _run(responses, config="repo: prometheus/prometheus\n", token=TOKEN, capsys=None):
        monkeypatch.chdir(tmp_path)  # no stray .env from the project folder
        cfg = tmp_path / "config.yaml"
        cfg.write_text(config)
        out = tmp_path / "raw.json"
        queue = list(responses)
        monkeypatch.setattr(pull.requests.Session, "post", lambda self, *a, **k: queue.pop(0))
        monkeypatch.setattr(pull.time, "sleep", lambda s: None)
        if token is None:
            monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        else:
            monkeypatch.setenv("GITHUB_TOKEN", token)
        monkeypatch.setattr("sys.argv", ["pull.py", "--config", str(cfg), "--out", str(out)])
        code = 0
        try:
            pull.main()
        except SystemExit as e:
            code = e.code
        raw = json.loads(out.read_text()) if out.exists() else None
        return code, raw

    return _run


def happy_responses():
    return [FakeResponse(body=fixture("repo.json")),
            FakeResponse(body=fixture("search_page1.json")),
            FakeResponse(body=fixture("search_page2.json"))]


# 1. Windows
def test_windows_with_defaults():
    now = datetime(2026, 11, 14, 5, 0, tzinfo=timezone.utc)
    win, (start, end) = pull.windows(now, 14, 14)
    assert win["current"] == (datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc), now)
    assert win["previous"][0] == datetime(2026, 10, 17, 5, 0, tzinfo=timezone.utc)
    assert win["cfr_eval"] == win["previous"]
    assert (start, end) == (win["previous"][0], now)


def test_windows_short_window_long_revert():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    win, (start, _) = pull.windows(now, 7, 14)
    assert win["cfr_eval"] == (datetime(2026, 10, 24, tzinfo=timezone.utc),
                               datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert start == win["cfr_eval"][0]  # fetch range must cover the CFR window


# 2. Config
@pytest.mark.parametrize("config", ["repo: owner/name\n", "branches: []\n", "repo: noslash\n",
                                    "repo: a/b\nwindow_days: two\n", "repo: a/b\nwindow_days: 0\n"])
def test_bad_config_exits_2(run, config):
    code, raw = run([], config=config)
    assert code == 2 and raw is None


# 3. Token
def test_missing_token_exits_2(run):
    code, _ = run([], token=None)
    assert code == 2


def test_rejected_token_exits_2_and_never_prints_token(run, capsys):
    code, _ = run([FakeResponse(status=401)])
    captured = capsys.readouterr()
    assert code == 2
    assert TOKEN not in captured.out + captured.err


def test_token_never_written_to_output(run, capsys):
    code, raw = run(happy_responses())
    captured = capsys.readouterr()
    assert code == 0
    assert TOKEN not in json.dumps(raw) + captured.out + captured.err


# 4. Pagination
def test_pages_combined_and_empty_nodes_skipped(run):
    code, raw = run(happy_responses())
    assert code == 0
    assert [p["number"] for p in raw["prs"]] == [1, 2, 3]


# 5. Flags
def test_truncation_and_deleted_author(run):
    _, raw = run(happy_responses())
    prs = {p["number"]: p for p in raw["prs"]}
    assert prs[2]["files_truncated"] is True
    assert prs[1]["files_truncated"] is False
    assert prs[3]["author"] == {"login": None, "type": "Unknown"}


# 6. Reconciliation
def test_reconciliation_ok(run):
    _, raw = run(happy_responses())
    assert raw["reconciliation"]["status"] == "ok"
    assert raw["reconciliation"]["slices"][0]["reported"] == 3


def test_reconciliation_mismatch_exits_3(run):
    short = fixture("search_page2.json")
    short["data"]["search"]["nodes"] = [{}]
    code, raw = run([FakeResponse(body=fixture("repo.json")),
                     FakeResponse(body=fixture("search_page1.json")),
                     FakeResponse(body=short)])
    assert code == 3
    assert raw["reconciliation"]["status"] == "mismatch"


# 7. Limits
def test_over_search_cap_exits_4(run):
    big = copy.deepcopy(fixture("search_page1.json"))
    big["data"]["search"]["issueCount"] = 1001
    code, _ = run([FakeResponse(body=fixture("repo.json")), FakeResponse(body=big)])
    assert code == 4


def test_slow_down_once_then_success(run):
    slow = FakeResponse(status=403, body={"message": "You have exceeded a secondary rate limit"},
                        headers={"Retry-After": "1"})
    responses = happy_responses()
    responses.insert(1, slow)
    code, raw = run(responses)
    assert code == 0 and len(raw["prs"]) == 3


def test_slow_down_twice_exits_4_with_reset_time(run, capsys):
    slow = FakeResponse(status=429, body={"message": "rate limit"},
                        headers={"Retry-After": "1", "X-RateLimit-Reset": "1794632400"})
    code, _ = run([FakeResponse(body=fixture("repo.json")), slow, slow])
    assert code == 4
    assert "Resets at" in capsys.readouterr().err


# 8. Token from .env
def test_read_token_prefers_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GITHUB_TOKEN=from-file\n")
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    assert pull.read_token() == "from-env"


@pytest.mark.parametrize("content", ['GITHUB_TOKEN=abc\n', 'GITHUB_TOKEN="abc"\n',
                                     "# comment\nOTHER=1\nexport GITHUB_TOKEN='abc'\n"])
def test_read_token_from_env_file(tmp_path, monkeypatch, content):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    (tmp_path / ".env").write_text(content)
    assert pull.read_token() == "abc"


def test_read_token_missing_or_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert pull.read_token() is None
    (tmp_path / ".env").write_text("GITHUB_TOKEN=\n")
    assert pull.read_token() is None


def test_gitignore_excludes_env():
    assert ".env" in (ROOT / ".gitignore").read_text().splitlines()
