from collections import defaultdict
from pathlib import Path
import sys

scripts_path = Path(__file__).parent.parent.parent.parent / "scripts"
sys.path.append(str(scripts_path))

import aggregate


def empty_failures():
    return defaultdict(list, {"Resolved": [], "Unresolved": [], "New": []})


def configure_output_paths(monkeypatch, tmp_path):
    failures_path = tmp_path / "current_logs"
    failures_path.mkdir()
    monkeypatch.setattr(aggregate, "FAILURES", str(failures_path))
    monkeypatch.chdir(tmp_path)


def valid_empty_summary():
    return """# Summary
|Resolved Failures|gcc|g++|gfortran|Previous Hash|
|---|---|---|---|---|

|Unresolved Failures|gcc|g++|gfortran|Previous Hash|
|---|---|---|---|---|

|New Failures|gcc|g++|gfortran|Previous Hash|
|---|---|---|---|---|

# Resolved Failures
# Unresolved Failures
# New Failures
"""


def test_summary_validation_rejects_missing_structure(tmp_path):
    empty_file = tmp_path / "empty.md"
    empty_file.write_text("")
    incomplete_file = tmp_path / "incomplete.md"
    incomplete_file.write_text("# Summary\n")

    assert not aggregate.is_valid_summary_file(str(empty_file))
    assert not aggregate.is_valid_summary_file(str(incomplete_file))


def test_summary_validation_accepts_valid_empty_result(tmp_path):
    summary_file = tmp_path / "summary.md"
    summary_file.write_text(valid_empty_summary())

    assert aggregate.is_valid_summary_file(str(summary_file))


def test_no_processed_summaries_is_invalid(monkeypatch, tmp_path):
    configure_output_paths(monkeypatch, tmp_path)

    markdown = aggregate.failures_to_markdown(
        empty_failures(), "a" * 40, "", "Testsuite Status", summaries_processed=0
    )

    assert "labels: invalid" in markdown
    assert (tmp_path / "labels.txt").read_text() == "invalid"


def test_processed_empty_summary_is_valid(monkeypatch, tmp_path):
    configure_output_paths(monkeypatch, tmp_path)

    markdown = aggregate.failures_to_markdown(
        empty_failures(), "a" * 40, "", "Testsuite Status", summaries_processed=1
    )

    assert "labels:" not in markdown
    assert (tmp_path / "labels.txt").read_text() == ""


def run_aggregate(monkeypatch, tmp_path, summary_contents, current_logs=()):
    summaries_path = tmp_path / "summaries"
    summaries_path.mkdir()
    failures_path = tmp_path / "current_logs"
    failures_path.mkdir()
    if isinstance(summary_contents, str):
        summary_contents = {"target-summary.md": summary_contents}
    for name, contents in (summary_contents or {}).items():
        (summaries_path / name).write_text(contents)
    for name in current_logs:
        (failures_path / name).write_text("testsuite report\n")
    output_path = tmp_path / "testsuite.md"

    monkeypatch.setattr(aggregate, "SUMMARIES", str(summaries_path))
    monkeypatch.setattr(aggregate, "FAILURES", str(failures_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["aggregate.py", "-chash", "a" * 40, "-o", str(output_path)],
    )

    aggregate.main()
    return output_path.read_text()


def test_main_marks_missing_or_damaged_summary_input_invalid(monkeypatch, tmp_path):
    markdown = run_aggregate(monkeypatch, tmp_path, "")

    assert "labels: invalid" in markdown


def test_main_accepts_valid_empty_summary_input(monkeypatch, tmp_path):
    markdown = run_aggregate(monkeypatch, tmp_path, valid_empty_summary())

    assert "labels:" not in markdown


def test_main_rejects_mixed_valid_and_damaged_summaries(monkeypatch, tmp_path):
    markdown = run_aggregate(
        monkeypatch,
        tmp_path,
        {"valid-summary.md": valid_empty_summary(), "broken-summary.md": "# Summary\n"},
    )

    assert "labels: invalid" in markdown
    assert (tmp_path / "labels.txt").read_text() == "invalid"


def test_main_rejects_missing_summary_for_a_current_log(monkeypatch, tmp_path):
    markdown = run_aggregate(
        monkeypatch,
        tmp_path,
        {"target-one-report-summary.md": valid_empty_summary()},
        current_logs=("target-one-report.log", "target-two-report.log"),
    )

    assert "labels: invalid" in markdown


def test_main_accepts_complete_summary_coverage(monkeypatch, tmp_path):
    markdown = run_aggregate(
        monkeypatch,
        tmp_path,
        {"target-one-report-summary.md": valid_empty_summary()},
        current_logs=("target-one-report.log",),
    )

    assert "labels:" not in markdown
