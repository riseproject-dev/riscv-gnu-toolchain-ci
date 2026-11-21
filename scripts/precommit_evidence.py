"""Verify the pre-commit comparison against the original, paired DejaGnu results."""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html import escape
import json
from pathlib import Path
import re

from compare_testsuite_log import parse_testsuite_failures
from separate_multilib_results import Board, read_report, split_report_name


RESULTS = {
    "PASS",
    "FAIL",
    "XFAIL",
    "XPASS",
    "ERROR",
    "UNRESOLVED",
    "UNSUPPORTED",
    "UNTESTED",
    "KFAIL",
    "KPASS",
}


def board_config(variation):
    flags = {}
    options = []
    for component in variation.split("/"):
        flag, _, value = component.partition("=")
        if flag in ("-march", "-mabi", "-mcmodel"):
            flags[flag] = value
        elif component != "riscv-sim":
            options.append(component)
    return Board(
        flags.get("-march", ""),
        flags.get("-mabi", ""),
        flags.get("-mcmodel", ""),
        tuple(options),
    )


@dataclass
class Run:
    # Use the raw triple, full board and testsuite-relative .exp path as the
    # execution scope. GCC's build directory differs between the two workers.
    drivers: dict = field(default_factory=lambda: defaultdict(set))
    repeated_boards: set = field(default_factory=set)
    outcomes: dict = field(default_factory=lambda: defaultdict(Counter))
    timeouts: Counter = field(default_factory=Counter)
    complete: bool = False


def read_sum(path, tool, arch, abi, wanted):
    result = Run()
    triple = board = driver = None
    final_summary = False
    timed_out_case = None
    passes = failures = 0
    totals = {}
    with path.open(encoding="utf-8", errors="surrogateescape") as source:
        for line in source:
            line = line.rstrip("\r\n")
            if line.startswith("PASS: "):
                passes += 1
            elif line.startswith("FAIL: "):
                failures += 1
            if line.startswith("Test run by "):
                if triple is not None:
                    raise ValueError("multiple test runs in one language summary")
            elif line.startswith("Target is "):
                triple = line[len("Target is ") :].strip()
            elif line.startswith("Running target "):
                variation = line[len("Running target ") :].strip()
                config = board_config(variation)
                board = (triple, variation) if config[:2] == (arch, abi) else None
                driver = None
                if board:
                    if board in result.drivers:
                        result.repeated_boards.add(board)
                    result.drivers.setdefault(board, set())
            elif line.startswith("Running "):
                match = re.search(r"/testsuite/(.+\.exp) \.\.\.$", line)
                driver = match[1] if match else None
            elif line.startswith("\t\t==="):
                if line.strip() == f"=== {tool} Summary ===":
                    final_summary = True
                driver = board = None
            elif final_summary:
                tally = re.fullmatch(
                    r"# of (expected passes|unexpected failures)\s+(\d+)", line
                )
                if tally:
                    totals[tally[1]] = int(tally[2])
            elif board:
                status, sep, case = line.partition(": ")
                if sep and status in RESULTS:
                    if driver and status not in {
                        "UNSUPPORTED",
                        "UNTESTED",
                        "UNRESOLVED",
                        "ERROR",
                    }:
                        result.drivers[board].add(driver)
                    if case in wanted or status == "UNRESOLVED":
                        key = (board, driver, case)
                        result.outcomes[key][status] += 1
                        if status == "FAIL" and timed_out_case == case:
                            result.timeouts[key] += 1
            if line.startswith("WARNING: ") and line.endswith(" program timed out."):
                timed_out_case = line[len("WARNING: ") : -len(" program timed out.")]
            else:
                timed_out_case = None
    result.complete = (
        bool(totals)
        and totals.get("expected passes", 0) == passes
        and totals.get("unexpected failures", 0) == failures
    )
    return result


def code(value):
    # Some compiler diagnostics are not UTF-8. Keep reports valid UTF-8
    # without coalescing distinct raw byte strings when matching outcomes.
    return (
        "<code>"
        + escape(value.encode("utf-8", "backslashreplace").decode())
        + "</code>"
    )


@dataclass
class Evidence:
    confirmed: int = 0
    unverified: int = 0
    gaps: list = field(default_factory=list)
    details: list = field(default_factory=list)


def report_url(directory):
    source = directory / "source.json"
    if source.is_file():
        metadata = json.loads(source.read_text())
        repository = metadata["repository"]
        if re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            return f"https://github.com/{repository}/actions/runs/{int(metadata['run_id'])}/artifacts/{int(metadata['id'])}"


def compare_tool(before, after, allowed, tool, target, result):
    """Only counts forced transitions when a repeated test has no unique run ID."""
    if not before.complete or not after.complete:
        result.gaps.append(f"{target}, {tool}: missing complete DejaGnu summary")
    if not after.drivers:
        result.gaps.append(f"{target}, {tool}: no candidate board results")
    # Post-commit can have additional optional configurations. The default
    # configuration is the one requested by the pre-commit multilib generator.
    for board in before.drivers.keys() - after.drivers.keys():
        config = board_config(board[1])
        if not config.options and config.model == "medlow":
            result.gaps.append(
                f"{target}, {tool}: missing candidate board {code(board[1])}"
            )
    heading = f"{target}, {tool}"
    seen = Counter()
    ambiguous = before.repeated_boards | after.repeated_boards
    for _, variation in ambiguous:
        result.gaps.append(f"{heading}: repeated raw board {code(variation)}")
    for board, current_drivers in after.drivers.items():
        previous_drivers = before.drivers.get(board, set())
        if not board[0] or not current_drivers or not previous_drivers:
            result.gaps.append(
                f"{heading}: missing comparable test drivers for {code(board[1])}"
            )
        else:
            for missing in sorted(previous_drivers - current_drivers):
                result.gaps.append(
                    f"{heading}: no candidate results for {code(missing)} on {code(board[1])}"
                )
    for key, now in after.outcomes.items():
        board, driver, case = key
        group = board_config(board[1])
        old = before.outcomes.get(key, Counter())
        for status in ("FAIL", "XPASS", "ERROR", "UNRESOLVED"):
            if status != "UNRESOLVED" and (group, status, case) not in allowed:
                continue
            seen[group, status, case] += now[status]
            new_count = max(0, now[status] - old[status])
            if not new_count:
                continue
            proven = 0
            # A count increase can be an extra execution, an unsupported test
            # becoming runnable, or a genuine regression. Only the last has
            # a matching PASS. Keep ambiguous duplicates for review.
            if (
                status == "FAIL"
                and driver
                and board[0]
                and board not in ambiguous
                and sum(old.values()) == sum(now.values())
            ):
                proven = max(0, now["FAIL"] - (sum(old.values()) - old["PASS"]))
            context = f"{heading} {code(board[1])} {code(driver or 'unknown driver')} {code(case)}"
            if proven:
                timed_out = max(0, proven - (now["FAIL"] - after.timeouts[key]))
                note = f" ({timed_out} timed out)" if timed_out else ""
                result.confirmed += proven
                result.details.append(f"- PASS → FAIL × {proven}{note}: {context}")
            if new_count > proven:
                previous = (
                    ", ".join(f"{s} × {n}" for s, n in sorted(old.items()))
                    or "no matching baseline outcome"
                )
                result.unverified += new_count - proven
                result.details.append(
                    f"- For review, {status} × {new_count - proven} ({previous}): {context}"
                )
    if any(seen[key] != count for key, count in allowed.items()):
        result.gaps.append(
            f"{heading}: filtered result counts disagree with the candidate .sum"
        )


def observed_cases(root, row, baseline, candidate, result):
    mode, arch, abi = row["mode"], row["arch"], row["abi"]
    prefix = f"gcc-{mode}-{arch}-{abi}-{candidate}-"
    allowed = defaultdict(Counter)
    boards = {}
    for report in sorted((root / "current_logs").glob(prefix + "*-report.log")):
        [(board, filtered)] = read_report(report).items()
        if report.name != split_report_name(mode, candidate, board) or board[:2] != (
            arch,
            abi,
        ):
            raise ValueError("normalized report does not identify the expected board")
        boards[board] = filtered.tools
        summary = root / "summaries" / (report.stem + "-summary.md")
        title = f"title: {baseline}->{candidate}"
        if summary.is_file():
            with summary.open() as stream:
                matched = (
                    stream.readline().strip() == "---"
                    and stream.readline().strip() == title
                )
        else:
            matched = False
        if not matched:
            result.gaps.append(
                f"{mode} {arch} {abi}: missing comparison for {code(report.name)}"
            )
        for desc, lines in parse_testsuite_failures(str(report)).items():
            for line in lines:
                status, _, case = line.rstrip("\r\n").partition(": ")
                allowed[desc.tool][board, status, case] += 1
    return boards, allowed


def check_row(root, row, baseline, candidate, baseline_sums, candidate_sums, result):
    mode, arch, abi = row["mode"], row["arch"], row["abi"]
    target = f"{mode} {arch} {abi}"
    old_dir = baseline_sums / row["baseline"].format(sha=baseline)
    new_dir = candidate_sums / row["candidate"].format(sha=candidate)
    missing = [
        role
        for role, directory in (("baseline", old_dir), ("candidate", new_dir))
        if not directory.is_dir()
    ]
    if missing:
        result.gaps.append(f"{target}: missing {' and '.join(missing)} raw archive")
        return
    try:
        boards, allowed = observed_cases(root, row, baseline, candidate, result)
    except (ValueError, OSError) as err:
        result.gaps.append(f"{target}: invalid filtered report ({escape(str(err))})")
        return
    if not boards:
        result.gaps.append(f"{target}: missing filtered candidate report")
    expected_tools = {"gcc", "g++", "gfortran"} if mode == "linux" else {"gcc", "g++"}
    for reported in boards.values():
        expected_tools.update(reported)
    for tool in sorted(expected_tools):
        wanted = {case for _, _, case in allowed[tool]}
        try:
            new = read_sum(new_dir / (tool + ".sum"), tool, arch, abi, wanted)
            # UNRESOLVED is reported by DejaGnu but not by testsuite-filter.
            # Look up its previous result so a harness problem remains visible
            # and cannot be mistaken for a confirmed compiler regression.
            wanted.update(
                case
                for (_, _, case), counts in new.outcomes.items()
                if counts["UNRESOLVED"]
            )
            old = read_sum(old_dir / (tool + ".sum"), tool, arch, abi, wanted)
        except OSError as err:
            phase = (
                "baseline"
                if Path(err.filename or "").parent == old_dir
                else "candidate"
            )
            result.gaps.append(f"{target}, {tool}: {phase} raw results unavailable")
            continue
        except ValueError as err:
            result.gaps.append(f"{target}, {tool}: {escape(str(err))}")
            continue
        raw_boards = {board_config(variation) for _, variation in new.drivers}
        if raw_boards != {board for board, tools in boards.items() if tool in tools}:
            result.gaps.append(
                f"{target}, {tool}: raw and filtered board coverage differ"
            )
        compare_tool(old, new, allowed[tool], tool, target, result)
    baseline_url, candidate_url = report_url(old_dir), report_url(new_dir)
    if baseline_url and candidate_url:
        result.details.append(
            f"- {target}: [baseline sums]({baseline_url}) · [candidate sums]({candidate_url})"
        )


def verify(root, matrix, baseline, candidate, baseline_sums, candidate_sums):
    if (
        not re.fullmatch(r"[a-f0-9]{40}", baseline)
        or not re.fullmatch(r"[a-f0-9]{40}", candidate)
        or baseline == candidate
    ):
        raise ValueError("two distinct full GCC revisions are required")
    if not matrix:
        raise ValueError("the expected testsuite matrix is empty")
    result = Evidence()
    for row in matrix:
        check_row(root, row, baseline, candidate, baseline_sums, candidate_sums, result)
    out = root / "evidence"
    out.mkdir(exist_ok=True)
    verdict = {
        "confirmed": result.confirmed,
        "unverified": result.unverified,
        "complete": not result.gaps,
    }
    (out / "verdict.json").write_text(json.dumps(verdict) + "\n")
    lines = [
        "## Verified testsuite comparison",
        "",
        f"Baseline {code(baseline)} · patched GCC {code(candidate)}",
        "",
        f"Confirmed PASS → FAIL: {result.confirmed}. Newly observed results needing review: {result.unverified}.",
    ]
    if result.gaps:
        lines.extend(
            ["", "### Incomplete test coverage", "", *("- " + s for s in result.gaps)]
        )
    if result.details:
        lines.extend(["", *result.details])
    (out / "evidence.md").write_text("\n".join(lines) + "\n")
    return verdict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--baseline-sums", type=Path, required=True)
    parser.add_argument("--candidate-sums", type=Path, required=True)
    args = parser.parse_args()
    verify(
        Path.cwd(),
        json.loads(args.matrix.read_text()),
        args.baseline,
        args.candidate,
        args.baseline_sums,
        args.candidate_sums,
    )


if __name__ == "__main__":
    main()
