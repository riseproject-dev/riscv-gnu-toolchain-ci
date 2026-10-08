import configparser
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
UPDATE_SCRIPT = REPO_ROOT / "scripts" / "update_ci_submodules.sh"


@pytest.fixture
def run_update(tmp_path):
    """Run the actual shell script with local, non-networking Git/sleep fakes."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_program = (
        f"#!{sys.executable}\n"
        + """
import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
with open(os.environ["TEST_COMMAND_LOG"], "a") as log:
    log.write(json.dumps({
        "command": command,
        "args": sys.argv[1:],
        "terminal_prompt": os.environ.get("GIT_TERMINAL_PROMPT"),
    }) + "\\n")

if command == "sleep":
    sys.exit(0)
if sys.argv[1:3] == ["submodule", "sync"]:
    sys.exit(int(os.environ["TEST_SYNC_STATUS"]))
if sys.argv[1:3] == ["submodule", "update"]:
    counter = Path(os.environ["TEST_UPDATE_COUNTER"])
    attempt = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(attempt))
    sys.exit(1 if attempt <= int(os.environ["TEST_UPDATE_FAILURES"]) else 0)
sys.exit(99)
"""
    )
    for command in ("git", "sleep"):
        program = fake_bin / command
        program.write_text(fake_program)
        program.chmod(0o755)

    def run(submodules=("binutils", "gdb"), failures=0, sync_status=0):
        command_log = tmp_path / "commands.jsonl"
        environment = os.environ.copy()
        environment.update(
            PATH=str(fake_bin) + os.pathsep + environment.get("PATH", ""),
            TEST_COMMAND_LOG=str(command_log),
            TEST_UPDATE_COUNTER=str(tmp_path / "update-count"),
            TEST_UPDATE_FAILURES=str(failures),
            TEST_SYNC_STATUS=str(sync_status),
            # The helper must override even an explicitly interactive caller.
            GIT_TERMINAL_PROMPT="1",
        )
        result = subprocess.run(
            ["bash", str(UPDATE_SCRIPT), *submodules],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        records = (
            [json.loads(line) for line in command_log.read_text().splitlines()]
            if command_log.exists()
            else []
        )
        return result, records

    return run


def command_arguments(records):
    return [(record["command"], record["args"]) for record in records]


def test_update_succeeds_without_retry(run_update):
    result, records = run_update()

    assert result.returncode == 0, result.stderr
    assert command_arguments(records) == [
        ("git", ["submodule", "sync", "--recursive", "--", "binutils", "gdb"]),
        (
            "git",
            ["submodule", "update", "--init", "--recursive", "--", "binutils", "gdb"],
        ),
    ]
    assert all(record["terminal_prompt"] == "0" for record in records)


@pytest.mark.parametrize("failures", [1, 3])
def test_update_retries_transient_failure_then_stops(run_update, failures):
    result, records = run_update(failures=failures)

    assert result.returncode == 0, result.stderr
    expected = [("git", ["submodule", "sync", "--recursive", "--", "binutils", "gdb"])]
    for attempt in range(1, failures + 2):
        expected.append(
            (
                "git",
                [
                    "submodule",
                    "update",
                    "--init",
                    "--recursive",
                    "--",
                    "binutils",
                    "gdb",
                ],
            )
        )
        if attempt <= failures:
            expected.append(("sleep", [str(attempt * 30)]))
    assert command_arguments(records) == expected


def test_update_stops_after_five_failed_attempts(run_update):
    result, records = run_update(failures=5)

    assert result.returncode != 0
    git_calls = [record["args"] for record in records if record["command"] == "git"]
    assert (
        git_calls
        == [
            ["submodule", "sync", "--recursive", "--", "binutils", "gdb"],
        ]
        + [["submodule", "update", "--init", "--recursive", "--", "binutils", "gdb"]]
        * 5
    )
    sleeps = [record["args"] for record in records if record["command"] == "sleep"]
    assert sleeps == [["30"], ["60"], ["90"], ["120"]]
    assert records[-1]["command"] == "git"


def test_update_aborts_when_sync_fails(run_update):
    result, records = run_update(sync_status=2)

    assert result.returncode != 0
    assert command_arguments(records) == [
        ("git", ["submodule", "sync", "--recursive", "--", "binutils", "gdb"])
    ]


def test_update_requires_explicit_submodules(run_update):
    result, records = run_update(submodules=())

    assert result.returncode != 0
    assert records == []


def test_update_preserves_selected_paths_and_pinned_full_history(run_update):
    selected = ("binutils", "glibc", "newlib", "module with spaces")
    result, records = run_update(submodules=selected)

    assert result.returncode == 0, result.stderr
    assert command_arguments(records) == [
        ("git", ["submodule", "sync", "--recursive", "--", *selected]),
        ("git", ["submodule", "update", "--init", "--recursive", "--", *selected]),
    ]
    for record in records:
        assert not any(
            argument == "--remote"
            or argument == "--depth"
            or argument.startswith("--depth=")
            for argument in record["args"]
        )


@pytest.mark.parametrize(
    "submodule, url",
    [
        ("binutils", "https://github.com/gnutools/binutils-gdb.git"),
        ("gdb", "https://github.com/gnutools/binutils-gdb.git"),
        ("glibc", "https://github.com/gnutools/glibc.git"),
        ("newlib", "https://github.com/cygwin/cygwin.git"),
        ("musl", "https://github.com/kraj/musl.git"),
        ("dejagnu", "https://git.savannah.gnu.org/git/dejagnu.git"),
    ],
)
def test_submodule_mirrors_match_the_reviewed_upstream_mapping(submodule, url):
    config = configparser.ConfigParser()
    config.read(REPO_ROOT / ".gitmodules")

    section = config[f'submodule "{submodule}"']
    assert section["path"] == submodule
    assert section["url"] == url
