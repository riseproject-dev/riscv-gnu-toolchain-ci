from pathlib import Path
import sys

import pytest

scripts_path = Path(__file__).parent.parent.parent.parent / "scripts"
sys.path.append(str(scripts_path))

import post_check_to_patchworks


def test_create_data_uses_rise_context_and_issue_url():
    data = post_check_to_patchworks.create_data(
        "Testing passed",
        "123#issuecomment-456",
        None,
        "success",
        "test",
        "riseproject-dev/gcc-precommit-ci",
    )

    assert data == {
        "state": "success",
        "target_url": "https://github.com/riseproject-dev/gcc-precommit-ci/issues/123#issuecomment-456",
        "context": "toolchain-ci-rise-test",
        "description": "Testing passed",
    }


def test_main_skips_patchwork_post_when_reporting_disabled(monkeypatch, capsys):
    def fail_send(*_args, **_kwargs):
        raise AssertionError("Patchwork post should be skipped")

    monkeypatch.delenv("PATCHWORK_REPORTING_ENABLED", raising=False)
    monkeypatch.setattr(post_check_to_patchworks, "send", fail_send)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "post_check_to_patchworks.py",
            "-event",
            "schedule",
            "-repo",
            "riseproject-dev/gcc-precommit-ci",
            "-pid",
            "123",
            "-desc",
            "Testing passed",
            "-iid",
            "1#issuecomment-2",
            "-state",
            "success",
            "-context",
            "test",
        ],
    )

    post_check_to_patchworks.main()

    assert "skipping Patchwork check post" in capsys.readouterr().out


@pytest.mark.parametrize("token_args", [[], ["-token"], ["-token", "PLACEHOLDER"]])
def test_main_rejects_missing_token_when_reporting_enabled(monkeypatch, token_args):
    def fail_send(*_args, **_kwargs):
        raise AssertionError("Patchwork post should not be attempted")

    monkeypatch.setenv("PATCHWORK_REPORTING_ENABLED", "true")
    monkeypatch.setattr(post_check_to_patchworks, "send", fail_send)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "post_check_to_patchworks.py",
            "-event",
            "schedule",
            "-repo",
            "riseproject-dev/gcc-precommit-ci",
            "-pid",
            "123",
            "-desc",
            "Testing passed",
            "-iid",
            "1#issuecomment-2",
            "-state",
            "success",
            "-context",
            "test",
            *token_args,
        ],
    )

    with pytest.raises(RuntimeError, match="no usable Patchwork API token"):
        post_check_to_patchworks.main()


def test_send_raises_on_http_failure(monkeypatch):
    class FakeResponse:
        status_code = 403
        text = "forbidden"

    monkeypatch.setattr(
        post_check_to_patchworks.requests,
        "post",
        lambda url, data, headers: FakeResponse(),
    )

    with pytest.raises(RuntimeError, match="HTTP 403: forbidden"):
        post_check_to_patchworks.send(
            "123", {"state": "success"}, {"Authorization": "Token secret"}
        )


def test_send_accepts_successful_response(monkeypatch):
    class FakeResponse:
        status_code = 201
        text = "created"

    monkeypatch.setattr(
        post_check_to_patchworks.requests,
        "post",
        lambda url, data, headers: FakeResponse(),
    )

    post_check_to_patchworks.send(
        "123", {"state": "success"}, {"Authorization": "Token secret"}
    )
