import argparse
import re
import os
from pathlib import Path

from compare_testsuite_log import compare_logs
from separate_multilib_results import read_report, split_report_name


def parse_arguments():
    """parse command line arguments"""
    parser = argparse.ArgumentParser(description="Download valid log artifacts")
    parser.add_argument(
        "-hash",
        required=True,
        type=str,
        help="Current gcc hash",
    )
    parser.add_argument(
        "--baseline-hash",
        help="Compare the selected pre-commit board reports against this exact baseline",
    )
    parser.add_argument(
        "-prefix",
        "--prefix",
        required=False,
        default="",
        type=str,
        help="Prefix to test",
    )
    parser.add_argument(
        "-ccommitted",
        "--current-hash-committed",
        help="The current hash is an existing GCC hash",
        action="store_true",
    )
    return parser.parse_args()


def find_previous_log(directory_path: str, file_regex: str):
    dir_contents = " ".join(os.listdir(directory_path))
    logs = re.findall(file_regex, dir_contents)
    if logs != []:
        return logs[0]
    return ""


def get_file_name_regex(file_name: str):
    new_name = file_name.split("-")
    new_name[4] = "[^-]*"
    return "-".join(new_name)


def get_hash_from_file_name(file_name: str):
    return file_name.split("-")[4]


def compare_selected_boards(
    current_hash, baseline_hash, current_hash_committed, prefix
):
    """Compare normalized pre-commit reports already selected for the patch matrix."""
    current_dir = Path("current_logs")
    previous_dir = Path("previous_logs")
    problems = []

    def index_reports(directory, sha):
        reports = {}
        for path in sorted(directory.glob("*-report.log")):
            parts = path.name.split("-", 5)
            if len(parts) != 6 or parts[4] != sha:
                problems.append((path.name, f"Expected revision {sha} in {directory}"))
                continue
            reports[(*parts[:4], parts[5])] = path
        return reports

    current = index_reports(current_dir, current_hash)
    previous = index_reports(previous_dir, baseline_hash)
    for identity in sorted(current.keys() | previous.keys()):
        new = current.get(identity)
        old = previous.get(identity)
        name = new.name if new else "-".join([*identity[:4], current_hash, identity[4]])
        summary = Path("summaries") / (Path(name).stem + "-summary.md")
        try:
            if old is None or new is None:
                raise ValueError(
                    "Missing baseline report" if old is None else "Missing patch report"
                )
            if baseline_hash == current_hash:
                raise ValueError("Patch and baseline revisions are identical")
            new_boards, old_boards = read_report(new), read_report(old)
            if len(new_boards) != 1 or new_boards.keys() != old_boards.keys():
                raise ValueError(
                    "Board configuration differs between patch and baseline"
                )
            board = next(iter(new_boards))
            if split_report_name(identity[1], current_hash, board) != name:
                raise ValueError(
                    "Board configuration differs from its normalized filename"
                )
            new_tools, old_tools = new_boards[board].tools, old_boards[board].tools
            covered = new_tools & old_tools
            if not covered:
                raise ValueError("Patch and baseline have no language in common")
            if new_tools != old_tools:
                missing = ", ".join(sorted(new_tools ^ old_tools))
                problems.append((name, f"Unpaired language coverage for {missing}"))
            compare_logs(
                baseline_hash,
                str(old),
                current_hash,
                str(new),
                str(summary),
                current_hash_committed,
                prefix,
                covered,
            )
        except (OSError, ValueError, RuntimeError) as err:
            summary.unlink(missing_ok=True)
            problems.append((name, str(err)))
    if not current and not previous:
        problems.append(("testsuite", "No board reports for patch or baseline"))
    if problems:
        with (current_dir / "failed_testsuite.txt").open("a") as out:
            for name, reason in problems:
                # The aggregate script uses a single pipe as its field separator.
                safe_name = re.sub(r"[|\r\n]", " ", name)
                safe_reason = re.sub(r"[|\r\n]", " ", reason)
                out.write(f"{safe_name}|{safe_reason}\n")


def compare_all_artifacts(
    current_hash: str, current_hash_committed: bool, prefix: str, baseline_hash=None
):
    if baseline_hash is not None:
        compare_selected_boards(
            current_hash, baseline_hash, current_hash_committed, prefix
        )
        return
    current_logs_dir = "./current_logs"
    previous_logs_dir = "./previous_logs"
    output_dir = "./summaries"
    for file in os.listdir(current_logs_dir):
        if "-" not in file:  # failed_testsuite and failed_build check
            continue
        output_file_name = f"{file.split('.')[0]}-summary.md"
        previous_log_regex = get_file_name_regex(file)
        previous_log_name = find_previous_log(previous_logs_dir, previous_log_regex)
        print(
            "current log:",
            file,
            "previous log:",
            previous_log_name,
            "output name:",
            output_file_name,
        )
        if previous_log_name != "":
            try:
                print(
                    f"found previous log. comparing {os.path.join(previous_logs_dir, previous_log_name)} with {os.path.join(current_logs_dir, file)}"
                )
                compare_logs(
                    get_hash_from_file_name(previous_log_name),
                    os.path.join(previous_logs_dir, previous_log_name),
                    current_hash,
                    os.path.join(current_logs_dir, file),
                    os.path.join(output_dir, output_file_name),
                    current_hash_committed,
                    prefix,
                )
            except (RuntimeError, ValueError) as err:
                with open(
                    os.path.join(current_logs_dir, "failed_testsuite.txt"), "a+"
                ) as f:
                    f.write(f"{file}|{err}\n")
        else:
            try:
                no_baseline_hash = current_hash + "-no-baseline"
                compare_logs(
                    no_baseline_hash,
                    os.path.join(current_logs_dir, file),
                    no_baseline_hash,
                    os.path.join(current_logs_dir, file),
                    os.path.join(output_dir, output_file_name),
                    current_hash_committed,
                    prefix,
                )
            except (RuntimeError, ValueError) as err:
                with open(
                    os.path.join(current_logs_dir, "failed_testsuite.txt"), "a+"
                ) as f:
                    f.write(f"{file}|{err}\n")


def main():
    args = parse_arguments()
    compare_all_artifacts(
        args.hash, args.current_hash_committed, args.prefix, args.baseline_hash
    )


if __name__ == "__main__":
    main()
