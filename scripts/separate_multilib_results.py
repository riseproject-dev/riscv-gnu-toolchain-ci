"""Split the per-tool failure blocks and coverage table produced by testsuite-filter."""

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import NamedTuple
from urllib.parse import quote


TOOLS = ("gcc", "g++", "gfortran")
SUMMARY = "========= Summary of gcc testsuite ========="
HEADER = re.compile(
    r"\t\t=== (gcc|g\+\+|gfortran): Unexpected fails for (\w+) (\w+) (\w*) (.*?) ===",
    re.ASCII,
)
NICKNAMES = {
    "--param=riscv-autovec-preference=": "autovec-",
    "--param=riscv-autovec-lmul=": "lmul-",
}


class Board(NamedTuple):
    arch: str
    abi: str
    model: str
    options: tuple[str, ...]


class BoardReport(NamedTuple):
    tools: frozenset[str]
    text: str


def read_report(path):
    """Return one report per board in the coverage table, including clean boards."""
    path = Path(path)
    lines = path.read_text().splitlines()
    if "" not in lines:
        raise ValueError(f"{path.name}: missing testsuite summary")
    split = lines.index("")
    header = lines[split : split + 4]
    if (
        len(header) != 4
        or header[1].strip() != SUMMARY
        or not header[2].strip().startswith("| # of unexpected case")
        or tuple(part.strip() for part in header[3].strip().strip("|").split("|"))
        != TOOLS
    ):
        raise ValueError(f"{path.name}: malformed GCC summary header")

    details = defaultdict(list)
    cases = {}
    board = None
    for line in lines[:split]:
        match = HEADER.fullmatch(line)
        if match:
            tool, arch, abi, model, options = match.groups()
            board = Board(arch, abi, model, tuple(options.split()))
            if (board, tool) in cases:
                raise ValueError(
                    f"{path.name}: duplicate {tool} failure block for {board}"
                )
            cases[board, tool] = Counter()
        elif board is None or not line.startswith(("FAIL: ", "ERROR: ", "XPASS: ")):
            raise ValueError(f"{path.name}: malformed testsuite failure block")
        else:
            cases[board, tool][line.split(" ", 2)[1]] += 1
        details[board].append(line)

    reports = {}
    index = split + 4
    while index < len(lines):
        row = lines[index]
        fields = [part.strip() for part in row.split("|")]
        if len(fields) != 5 or fields[-1]:
            raise ValueError(f"{path.name}: malformed GCC summary row")
        identity = [part.strip() for part in fields[0].split("/")]
        if (
            len(identity) != 3
            or not all(re.fullmatch(r"[A-Za-z0-9_]+", part) for part in identity[:2])
            or not re.fullmatch(r"[A-Za-z0-9_]*", identity[2])
        ):
            raise ValueError(f"{path.name}: invalid board in GCC summary")
        index += 1
        row_lines = [row]
        options = ()
        if index < len(lines) and "|" not in lines[index]:
            options = tuple(lines[index].split())
            if not options:
                raise ValueError(f"{path.name}: empty board options")
            row_lines.append(lines[index])
            index += 1
        board = Board(*identity, options)
        if board in reports:
            raise ValueError(f"{path.name}: duplicate summary for {board}")

        tools = set()
        for tool, cell in zip(TOOLS, fields[1:4]):
            failures = cases.get((board, tool), {})
            if cell == "-" and not failures:
                continue
            matches = re.fullmatch(r"(\d+)\s*/\s*(\d+)", cell)
            if not matches or (int(matches[1]), int(matches[2])) != (
                sum(failures.values()),
                len(failures),
            ):
                raise ValueError(
                    f"{path.name}: inconsistent {tool} summary for {board}"
                )
            tools.add(tool)
        if not tools:
            raise ValueError(f"{path.name}: no tool results for {board}")
        contents = [*details.pop(board, ()), *header, *row_lines]
        reports[board] = BoardReport(frozenset(tools), "\n".join(contents) + "\n")
    if not reports or details:
        raise ValueError(f"{path.name}: missing board coverage in summary")
    return reports


def split_report_name(libc, revision, board):
    if libc not in {"linux", "newlib"} or not re.fullmatch("[0-9a-fA-F]+", revision):
        raise ValueError("Invalid report identity")
    if not all(
        re.fullmatch(r"[A-Za-z0-9_]+", field) for field in (board.arch, board.abi)
    ) or not re.fullmatch(r"[A-Za-z0-9_]*", board.model):
        raise ValueError("Invalid board identity")
    options = list(board.options)
    for i, option in enumerate(options):
        for prefix, nickname in NICKNAMES.items():
            if option.startswith(prefix):
                options[i] = nickname + option[len(prefix) :]
                break
    if board.model != "medlow":
        options.insert(0, "mcmodel-" + (board.model or "default"))
    # Board options are data from the testsuite. They must remain inside one
    # filename, including when they contain paths or dot-separated values.
    suffix = "_".join(quote(opt, safe="=-").replace(".", "%2E") for opt in options)
    return (
        f"gcc-{libc}-{board.arch}-{board.abi}-{revision}-"
        + (suffix + "-" if suffix else "")
        + "multilib-report.log"
    )


def split_reports(paths, outdir):
    outdir = Path(outdir)
    if not paths:
        raise ValueError("no testsuite reports to split")
    sources = {Path(path).absolute() for path in paths}
    with TemporaryDirectory(dir=outdir) as tmp:
        staged = Path(tmp)
        outputs = set()
        for path in sorted(sources):
            name = re.fullmatch(
                r"gcc-(linux|newlib)-[\w]+-[\w]+-([0-9a-fA-F]+)-.+-report\.log",
                path.name,
            )
            if not name:
                raise ValueError(f"Invalid report filename: {path.name}")
            for board, report in read_report(path).items():
                filename = split_report_name(name[1], name[2], board)
                output = (outdir / filename).absolute()
                if output in outputs or (output.exists() and output not in sources):
                    raise ValueError(f"Ambiguous output for board: {filename}")
                outputs.add(output)
                (staged / filename).write_text(report.text)
        # Parse every input before replacing any original, as a normalized
        # board filename may also be an input filename for a multilib run.
        for output in sorted(outputs):
            (staged / output.name).replace(output)
        for source in sources - outputs:
            if source.parent == outdir.absolute():
                source.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("-file", "--file-name", type=Path)
    inputs.add_argument("-indir", "--directory-name", type=Path)
    parser.add_argument("-outdir", default=Path("."), type=Path)
    args = parser.parse_args()
    paths = (
        [args.file_name]
        if args.file_name
        else list(args.directory_name.glob("*-report.log"))
    )
    split_reports(paths, args.outdir)


if __name__ == "__main__":
    main()
