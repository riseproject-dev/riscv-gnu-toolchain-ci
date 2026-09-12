from pathlib import Path
import sys

scripts_path = Path(__file__).parent.parent.parent.parent / "scripts"
sys.path.append(str(scripts_path))

import create_timestamp_files


def run_timestamp_script(monkeypatch, tmp_path, runs):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_timestamp_files, "get_workflow_runs", lambda *_args: runs
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_timestamp_files.py",
            "-rid",
            "123",
            "-repo",
            "riseproject-dev/gcc-precommit-ci",
            "-workflow",
            "Patchworks",
        ],
    )
    create_timestamp_files.main()


def test_first_scheduled_run_bootstraps_without_a_previous_run(monkeypatch, tmp_path):
    run_timestamp_script(
        monkeypatch, tmp_path, [{"id": 123, "created_at": "2026-09-12T12:07:00Z"}]
    )

    assert (tmp_path / "current_time_rounded.txt").read_text() == "2026-09-12T12:00:00"
    assert (
        tmp_path / "prior_run_time_rounded.txt"
    ).read_text() == "2026-09-12T11:45:00"
    assert (
        tmp_path / "prior_run_time_minus_15_min_rounded.txt"
    ).read_text() == "2026-09-12T11:30:00"
    assert not (tmp_path / "run_id.txt").exists()


def test_scheduled_run_preserves_gap_since_previous_run(monkeypatch, tmp_path):
    run_timestamp_script(
        monkeypatch,
        tmp_path,
        [
            {"id": 123, "created_at": "2026-09-12T12:07:00Z"},
            {"id": 122, "created_at": "2026-09-12T10:22:00Z"},
        ],
    )

    assert (tmp_path / "run_id.txt").read_text() == "122"
    assert (
        tmp_path / "prior_run_time_rounded.txt"
    ).read_text() == "2026-09-12T10:15:00"
    assert (
        tmp_path / "prior_run_time_minus_15_min_rounded.txt"
    ).read_text() == "2026-09-12T10:00:00"
