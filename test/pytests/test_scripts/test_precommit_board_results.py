from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from compare_all_artifacts import compare_all_artifacts
from separate_multilib_results import (
    Board,
    read_report,
    split_report_name,
    split_reports,
)


OLD = "a" * 40
NEW = "b" * 40
BOARD = Board("rv64gcv", "lp64d", "medlow", ())
HEADER = (
    "\n               ========= Summary of gcc testsuite =========\n"
    "                            | # of unexpected case / # of unique unexpected case\n"
    "                            |          gcc |          g++ |     gfortran |\n"
)
ROW = "    rv64gcv/  lp64d/ medlow |   0 /     0 |     0 /     0 |      - |\n"
DETAIL = "\t\t=== gcc: Unexpected fails for rv64gcv lp64d medlow  ===\nFAIL: gcc.dg/example.c  -O2 execution test\n"
FAIL = DETAIL + HEADER + ROW.replace("0 /     0", "1 /     1", 1)


def test_clean_boards_and_option_rows(tmp_path):
    first = ROW.replace("rv64gcv", "rv32gcv").replace("lp64d", "ilp32d")
    option = "--param=riscv-autovec-preference=scalable"
    source = tmp_path / "mixed.log"
    source.write_text(
        DETAIL
        + HEADER
        + first
        + f" {option}\n"
        + ROW.replace("0 /     0", "1 /     1", 1)
    )
    results = read_report(source)
    flagged = Board("rv32gcv", "ilp32d", "medlow", (option,))
    assert results[flagged].tools == {"gcc", "g++"}
    assert results[flagged].text == HEADER + first + f" {option}\n"
    assert results[BOARD].text == FAIL
    assert "-autovec-scalable-multilib-" in split_report_name("linux", OLD, flagged)


def test_inplace_split_preserves_variations_and_code_models(tmp_path):
    original = tmp_path / split_report_name("linux", OLD, BOARD)
    original.write_text(HEADER + ROW + ROW.replace("medlow", "medany"))
    split_reports([original], tmp_path)
    other = tmp_path / split_report_name("linux", OLD, BOARD._replace(model="medany"))
    assert original.read_text() == HEADER + ROW
    assert other.read_text() == HEADER + ROW.replace("medlow", "medany")


def test_filter_keeps_earlier_failures_when_a_board_reappears(tmp_path):
    sums = tmp_path / "gcc.sum"
    target = "Running target riscv-sim/-march=rv64gcv/-mabi=lp64d/-mcmodel=medlow\n"
    sums.write_text(
        target + "FAIL: earlier.c execution test\n" + target + "PASS: later.c\n"
    )
    filtered = subprocess.run(
        [
            sys.executable,
            Path(__file__).resolve().parents[3] / "scripts/testsuite-filter",
            "gcc",
            "newlib",
            tmp_path,
            sums,
        ],
        capture_output=True,
        text=True,
    )
    assert filtered.returncode == 1 and not filtered.stderr
    report = tmp_path / "report.log"
    report.write_text(filtered.stdout)
    assert "FAIL: earlier.c execution test" in read_report(report)[BOARD].text


def test_input_collision_does_not_remove_or_overwrite_sources(tmp_path):
    first = tmp_path / split_report_name("linux", OLD, BOARD)
    second = tmp_path / first.name.replace("rv64gcv", "rv32gcv")
    for path in (first, second):
        path.write_text(HEADER + ROW)
    with pytest.raises(ValueError, match="Ambiguous"):
        split_reports([first, second], tmp_path)
    assert first.read_text() == second.read_text() == HEADER + ROW


@pytest.mark.parametrize(
    "data",
    [
        "",
        HEADER,
        DETAIL,
        HEADER + ROW.replace("0 /     0", "1 /     1", 1),
        HEADER + ROW.replace("rv64gcv", "../../out"),
        HEADER + ROW.replace("0 /     0", "-"),
    ],
)
def test_malformed_report_keeps_source(tmp_path, data):
    path = tmp_path / split_report_name("linux", OLD, BOARD)
    path.write_text(data)
    with pytest.raises(ValueError):
        split_reports([path], tmp_path)
    assert path.read_text() == data


def test_options_do_not_become_paths(tmp_path):
    path = tmp_path / split_report_name("linux", OLD, BOARD)
    text = HEADER + ROW + " --sysroot=../../elsewhere\n"
    path.write_text(text)
    split_reports([path], tmp_path)
    [split] = tmp_path.iterdir()
    assert split.is_file() and split.read_text() == text


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for folder in ["previous_logs", "current_logs", "summaries"]:
        Path(folder).mkdir()
    old = Path("previous_logs") / split_report_name("linux", OLD, BOARD)
    new = Path("current_logs") / split_report_name("linux", NEW, BOARD)
    return old, new


def test_green_baseline_then_fail_has_real_comparison(dirs):
    old, new = dirs
    old.write_text(HEADER + ROW)
    new.write_text(FAIL)
    compare_all_artifacts(NEW, False, "", OLD)
    [summary] = Path("summaries").glob("*.md")
    assert f"title: {OLD}->{NEW}" in summary.read_text()
    assert DETAIL.splitlines()[1] in summary.read_text().split("# New Failures\n")[1]
    assert not Path("current_logs/failed_testsuite.txt").exists()


@pytest.mark.parametrize("missing", ["previous", "current", "wrong_sha"])
def test_strict_mode_reports_missing_counterpart(dirs, missing):
    old, new = dirs
    if missing == "wrong_sha":
        old = old.with_name(old.name.replace(OLD, "c" * 40))
    if missing != "previous":
        old.write_text(HEADER + ROW)
    if missing != "current":
        new.write_text(FAIL)
    compare_all_artifacts(NEW, False, "", OLD)
    assert "Missing" in Path("current_logs/failed_testsuite.txt").read_text()
    assert not list(Path("summaries").glob("*.md"))


def test_missing_language_reports_gap_and_preserves_other_comparisons(dirs):
    old, new = dirs
    old.write_text(HEADER + ROW.replace("     0 /     0 |      -", "     - |      -"))
    new.write_text(FAIL)
    compare_all_artifacts(NEW, False, "", OLD)
    assert (
        "Unpaired language coverage for g++"
        in Path("current_logs/failed_testsuite.txt").read_text()
    )
    [summary] = Path("summaries").glob("*.md")
    assert DETAIL.splitlines()[1] in summary.read_text().split("# New Failures\n")[1]


def test_without_requested_baseline_legacy_snapshot_is_preserved(dirs):
    _, new = dirs
    new.write_text(FAIL)
    compare_all_artifacts(NEW, False, "")
    [summary] = Path("summaries").glob("*.md")
    assert f"{NEW}-no-baseline" in summary.read_text()
