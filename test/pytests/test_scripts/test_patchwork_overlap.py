from pathlib import Path
import sys

import pytest

scripts_path = Path(__file__).parent.parent.parent.parent / "scripts"
sys.path.append(str(scripts_path))

import create_patches_files


def check(username="rise-ci", context="toolchain-ci-rise-lint", state="pending"):
    return {"user": {"username": username}, "context": context, "state": state}


@pytest.mark.parametrize(
    "checks",
    [
        [],
        [check(username="other-ci")],
        [check(context="toolchain-ci-" + "rivos-lint")],
        [check(context="unrelated-check")],
    ],
)
def test_overlap_recovers_patches_without_this_services_check(monkeypatch, checks):
    monkeypatch.setenv("PATCHWORK_CHECK_USERNAME", "rise-ci")
    monkeypatch.setattr(create_patches_files, "make_api_request", lambda _url: checks)
    early = {1: [["patch-one\n"]]}

    result = create_patches_files.get_overlap_dict({}, early, {1: [["checks-one\n"]]})

    assert result == early


@pytest.mark.parametrize("state", ["pending", "success", "fail", "warning"])
def test_overlap_does_not_requeue_our_started_patch(monkeypatch, state):
    monkeypatch.setenv("PATCHWORK_CHECK_USERNAME", "rise-ci")
    monkeypatch.setattr(
        create_patches_files, "make_api_request", lambda _url: [check(state=state)]
    )

    assert (
        create_patches_files.get_overlap_dict(
            {}, {1: [["patch-one\n"]]}, {1: [["checks-one\n"]]}
        )
        == {}
    )


def test_shadow_overlap_runs_without_an_account(monkeypatch):
    monkeypatch.delenv("PATCHWORK_CHECK_USERNAME", raising=False)
    monkeypatch.setattr(
        create_patches_files, "make_api_request", lambda _url: [check()]
    )
    early = {1: [["patch-one\n"]]}

    assert (
        create_patches_files.get_overlap_dict({}, early, {1: [["checks-one\n"]]})
        == early
    )


def test_overlap_still_recovers_a_different_earlier_series(monkeypatch):
    monkeypatch.setenv("PATCHWORK_CHECK_USERNAME", "rise-ci")
    monkeypatch.setattr(create_patches_files, "make_api_request", lambda _url: [])

    result = create_patches_files.get_overlap_dict(
        {1: [["patch-one-b\n"]]},
        {1: [["patch-one-a\n"]], 2: [["patch-two\n"]]},
        {1: [["checks-one\n"]], 2: [["checks-two\n"]]},
    )

    assert result == {
        1: [["patch-one-a\n", "patch-one-b\n"]],
        2: [["patch-two\n"]],
    }


def test_overlap_checks_the_interesting_patch_after_its_prerequisites(monkeypatch):
    monkeypatch.setenv("PATCHWORK_CHECK_USERNAME", "rise-ci")
    requested = []

    def fake_checks(url):
        requested.append(url)
        return []

    monkeypatch.setattr(create_patches_files, "make_api_request", fake_checks)
    early = {1: [["unrelated-prerequisite\n", "riscv-patch\n"]]}

    result = create_patches_files.get_overlap_dict(
        {}, early, {1: [["prerequisite-checks\n", "riscv-checks\n"]]}
    )

    assert result == early
    assert requested == ["riscv-checks"]


def test_recovered_series_metadata_is_available_with_current_patches(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PATCHWORK_CHECK_USERNAME", raising=False)
    monkeypatch.setattr(create_patches_files, "make_api_request", lambda _url: [])

    def fake_patch_info(url, _all_patches):
        series_id = 1 if "since=start" in url else 2
        return (
            {series_id: f"series_{series_id}"},
            {series_id: f"https://patchwork.example/series/{series_id}"},
            {series_id: [[f"mbox-{series_id}\n"]]},
            {
                series_id: [
                    [f"patch\thttps://patchwork.example/{series_id}\t{series_id}\n"]
                ]
            },
            {series_id: [[f"checks-{series_id}\n"]]},
        )

    monkeypatch.setattr(create_patches_files, "get_patch_info", fake_patch_info)

    create_patches_files.get_multiple_patches("start", "end", "backup", 6, False)

    assert sorted(path.name for path in (tmp_path / "patch_urls").iterdir()) == [
        "1-series_1-1",
        "2-series_2-1",
    ]
    assert sorted(
        path.name for path in (tmp_path / "patchworks_metadata").iterdir()
    ) == ["1-series_1-1", "2-series_2-1"]


def test_patch_discovery_accepts_empty_page_without_link(monkeypatch):
    monkeypatch.setattr(
        create_patches_files, "make_api_request_and_get_headers", lambda _url: ({}, [])
    )

    assert create_patches_files.get_patch_info(
        "https://patchwork.example/?q=riscv", False
    ) == ({}, {}, {}, {}, {})
