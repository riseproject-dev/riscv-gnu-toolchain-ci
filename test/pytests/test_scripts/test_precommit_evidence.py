"""Exercise the filtered comparison and the raw evidence together."""

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[3] / "scripts"))
from precommit_evidence import verify
from compare_testsuite_log import compare_logs


BASE = "a" * 40
PATCH = "b" * 40
BOARD = "riscv-sim/-march=rv64gcv/-mabi=lp64d/-mcmodel=medlow"
CASE = "gcc.dg/riscv.c   -O2  execution test"
ROW = {
    "mode": "newlib",
    "arch": "rv64gcv",
    "abi": "lp64d",
    "baseline": "gcc-newlib-rv64gcv-lp64d-{sha}-multilib-sum-files",
    "candidate": "gcc-newlib-rv64gcv-lp64d-{sha}-multilib-sum-files",
}


def raw(results, driver, board=BOARD, finish=True):
    passes = 1 + sum(line.startswith("PASS: ") for line in results)
    failures = sum(line.startswith("FAIL: ") for line in results)
    summary = f"\t\t=== gcc Summary ===\n# of expected passes\t{passes}\n# of unexpected failures\t{failures}\n"
    return (
        f"Target is riscv64-unknown-elf\nRunning target {board}\n"
        f"Running /worker/src/gcc/testsuite/{driver} ...\nPASS: anchor compile\n"
        + "\n".join(results)
        + "\n"
        + (summary if finish else "")
    )


def report(results):
    unexpected = [
        line for line in results if line.startswith(("ERROR:", "FAIL:", "XPASS:"))
    ]
    unique = len({item.split(" ", 2)[1] for item in unexpected})
    header = "\t\t=== gcc: Unexpected fails for rv64gcv lp64d medlow  ===\n"
    return (
        (header + "\n".join(unexpected) + "\n" if unexpected else "")
        + "\n               ========= Summary of gcc testsuite =========\n"
        "                            | # of unexpected case / # of unique unexpected case\n"
        "                            |          gcc |          g++ |     gfortran |\n"
        f" rv64gcv/ lp64d/ medlow | {len(unexpected)} / {unique} | 0 / 0 | - |\n"
    )


def prepare(
    root,
    before,
    after,
    old_driver="gcc.dg/dg.exp",
    new_driver="gcc.dg/dg.exp",
    finish=True,
):
    for phase, revision, records, driver in (
        ("baseline", BASE, before, old_driver),
        ("candidate", PATCH, after, new_driver),
    ):
        target = root / phase / ROW[phase].format(sha=revision)
        target.mkdir(parents=True)
        (target / "gcc.sum").write_text(
            raw(records, driver, finish=finish or phase == "baseline")
        )
        (target / "g++.sum").write_text(
            raw(["PASS: c++ case"], "g++.dg/dg.exp").replace(
                "=== gcc Summary", "=== g++ Summary"
            )
        )
        logdir = root / ("previous_logs" if phase == "baseline" else "current_logs")
        logdir.mkdir()
        (
            logdir / f"gcc-newlib-rv64gcv-lp64d-{revision}-multilib-report.log"
        ).write_text(report(records))
    (root / "summaries").mkdir()
    old, new = [next((root / d).glob("*")) for d in ("previous_logs", "current_logs")]
    compare_logs(
        BASE,
        str(old),
        PATCH,
        str(new),
        str(root / "summaries" / (new.stem + "-summary.md")),
        False,
        "",
    )


def verdict(root):
    return verify(root, [ROW], BASE, PATCH, root / "baseline", root / "candidate")


def test_green_board_to_timeout(tmp_path):
    prepare(
        tmp_path,
        ["PASS: " + CASE],
        [f"WARNING: {CASE} program timed out.", "FAIL: " + CASE],
    )
    assert verdict(tmp_path) == dict(confirmed=1, unverified=0, complete=True)
    text = (tmp_path / "evidence/evidence.md").read_text()
    assert CASE in text and "timed out" in text


def test_existing_failure_is_not_new(tmp_path):
    prepare(tmp_path, ["FAIL: " + CASE], ["FAIL: " + CASE])
    assert verdict(tmp_path) == dict(confirmed=0, unverified=0, complete=True)


def test_unsupported_to_fail_is_only_observed(tmp_path):
    prepare(tmp_path, ["UNSUPPORTED: " + CASE], ["FAIL: " + CASE])
    assert verdict(tmp_path) == dict(confirmed=0, unverified=1, complete=True)
    assert "UNSUPPORTED" in (tmp_path / "evidence/evidence.md").read_text()


def test_different_options_and_first_observations(tmp_path):
    prepare(
        tmp_path,
        ["PASS: " + CASE.replace("-O2", "-O0")],
        ["FAIL: " + CASE, "UNRESOLVED: new timeout", "ERROR: new error"],
    )
    assert verdict(tmp_path) == dict(confirmed=0, unverified=3, complete=True)


def test_different_drivers_cannot_confirm(tmp_path):
    prepare(tmp_path, ["PASS: " + CASE], ["FAIL: " + CASE], old_driver="other.exp")
    assert verdict(tmp_path) == dict(confirmed=0, unverified=1, complete=False)
    assert "other.exp" in (tmp_path / "evidence/evidence.md").read_text()


def test_no_candidates_still_requires_complete_coverage(tmp_path):
    prepare(tmp_path, [], [], finish=False)
    assert verdict(tmp_path) == dict(confirmed=0, unverified=0, complete=False)
    (tmp_path / "baseline" / ROW["baseline"].format(sha=BASE) / "g++.sum").unlink()
    assert not verdict(tmp_path)["complete"]
    text = (tmp_path / "evidence/evidence.md").read_text()
    assert (
        "missing complete DejaGnu summary" in text and "raw results unavailable" in text
    )


def test_missing_or_wrong_saved_summary(tmp_path):
    prepare(tmp_path, [], [])
    summary = next((tmp_path / "summaries").glob("*"))
    summary.write_text(summary.read_text().replace(BASE, PATCH))
    assert not verdict(tmp_path)["complete"]


def test_duplicate_outcomes_only_confirm_forced_changes(tmp_path):
    prepare(
        tmp_path,
        ["FAIL: " + CASE, "PASS: " + CASE, "PASS: " + CASE],
        ["FAIL: " + CASE, "FAIL: " + CASE, "PASS: " + CASE],
    )
    assert verdict(tmp_path) == dict(confirmed=1, unverified=0, complete=True)


def test_ambiguous_extra_execution(tmp_path):
    prepare(tmp_path, ["PASS: " + CASE], ["FAIL: " + CASE, "PASS: " + CASE])
    assert verdict(tmp_path) == dict(confirmed=0, unverified=1, complete=True)


def test_allowlisted_outcome_does_not_create_new_regression(tmp_path):
    prepare(tmp_path, ["PASS: " + CASE], [])
    sums = tmp_path / "candidate" / ROW["candidate"].format(sha=PATCH) / "gcc.sum"
    sums.write_text(raw(["FAIL: " + CASE], "gcc.dg/dg.exp"))
    assert verdict(tmp_path) == dict(confirmed=0, unverified=0, complete=True)


def test_repeated_board_is_incomplete_even_if_a_first_failure_was_hidden(tmp_path):
    prepare(tmp_path, ["PASS: " + CASE], [])
    sums = tmp_path / "candidate" / ROW["candidate"].format(sha=PATCH) / "gcc.sum"
    prior = raw(["FAIL: " + CASE], "gcc.dg/dg.exp", finish=False)
    repeated = sums.read_text().split("Running target ", 1)[1]
    sums.write_text(
        prior
        + "Running target "
        + repeated.replace("passes\t1", "passes\t2").replace(
            "failures\t0", "failures\t1"
        )
    )
    assert not verdict(tmp_path)["complete"]
    assert "repeated raw board" in (tmp_path / "evidence/evidence.md").read_text()


def test_corrupt_totals_cannot_look_green(tmp_path):
    prepare(tmp_path, [], [])
    sums = tmp_path / "candidate" / ROW["candidate"].format(sha=PATCH) / "gcc.sum"
    original = sums.read_text()
    for field in ("passes\t1", "failures\t0"):
        sums.write_text(original.replace(field, field[:-1] + "999"))
        assert not verdict(tmp_path)["complete"]


def test_proof_survives_unavailable_other_tool(tmp_path):
    prepare(tmp_path, ["PASS: " + CASE], ["FAIL: " + CASE])
    (tmp_path / "candidate" / ROW["candidate"].format(sha=PATCH) / "g++.sum").unlink()
    assert verdict(tmp_path) == dict(confirmed=1, unverified=0, complete=False)
