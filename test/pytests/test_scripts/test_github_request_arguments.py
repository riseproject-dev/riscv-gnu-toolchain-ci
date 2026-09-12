import json
from pathlib import Path
import sys

scripts_path = Path(__file__).parent.parent.parent.parent / "scripts"
sys.path.append(str(scripts_path))

from close_old_issues import close_issue, get_issues
from create_timestamp_files import get_workflow_runs
from update_issue_status import get_comment


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self.text = json.dumps(payload)


def test_get_workflow_runs_separates_headers_and_query(monkeypatch):
    captured = {}

    def fake_get(url, *, headers, params):
        captured.update(url=url, headers=headers, params=params)
        return FakeResponse({"workflow_runs": [{"name": "nightly"}]})

    monkeypatch.setattr("create_timestamp_files.requests.get", fake_get)

    assert get_workflow_runs("secret-token", "rise/toolchain", "nightly") == [
        {"name": "nightly"}
    ]
    assert captured["url"] == (
        "https://api.github.com/repos/rise/toolchain/actions/runs"
    )
    assert captured["headers"]["Authorization"] == "token secret-token"
    assert captured["params"] == {
        "branch": "main",
        "event": "schedule",
        "per_page": 100,
    }
    assert "secret-token" not in captured["url"]
    assert "Authorization" not in captured["params"]


def test_get_comment_sends_token_only_as_header(monkeypatch):
    captured = {}

    def fake_get(url, *, headers):
        captured.update(url=url, headers=headers)
        return FakeResponse({"body": "comment"})

    monkeypatch.setattr("update_issue_status.requests.get", fake_get)

    assert get_comment("secret-token", "42", "Build GCC", "rise/toolchain") == {
        "body": "comment"
    }
    assert captured["url"] == (
        "https://api.github.com/repos/rise/toolchain/issues/comments/42"
    )
    assert captured["headers"]["Authorization"] == "token secret-token"
    assert "secret-token" not in captured["url"]


def test_get_issues_separates_headers_and_query(monkeypatch):
    captured = {}

    def fake_get(url, *, headers, params):
        captured.update(url=url, headers=headers, params=params)
        return FakeResponse([{"number": 1}, {"number": 2, "pull_request": {}}])

    monkeypatch.setattr("close_old_issues.requests.get", fake_get)

    assert get_issues("secret-token", "rise/toolchain") == [{"number": 1}]
    assert captured["url"] == "https://api.github.com/repos/rise/toolchain/issues"
    assert captured["headers"]["Authorization"] == "token secret-token"
    assert captured["params"] == {"per_page": 100, "state": "open"}
    assert "secret-token" not in captured["url"]
    assert "Authorization" not in captured["params"]


def test_close_issue_sends_token_only_as_header(monkeypatch):
    captured = {}

    def fake_patch(*, url, data, headers):
        captured.update(url=url, data=data, headers=headers)
        return FakeResponse({"state": "closed"})

    monkeypatch.setattr("close_old_issues.requests.patch", fake_patch)

    close_issue(42, "secret-token", "rise/toolchain")

    assert captured["url"] == "https://api.github.com/repos/rise/toolchain/issues/42"
    assert json.loads(captured["data"]) == {"state": "closed"}
    assert captured["headers"]["Authorization"] == "token secret-token"
    assert "secret-token" not in captured["url"]
