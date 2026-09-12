import argparse
import os


DEFAULT_POSTCOMMIT_REPOSITORY = os.environ.get(
    "POSTCOMMIT_REPOSITORY", "riseproject-dev/gcc-postcommit-ci"
)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Apply patch report generator")
    parser.add_argument(
        "-patch",
        "--patch-name",
        required=True,
        metavar="<string>",
        type=str,
        help="Patch name",
    )
    parser.add_argument(
        "-bhash",
        "--base-hash",
        metavar="<string>",
        default="",
        type=str,
        help="Baseline hash",
    )
    parser.add_argument(
        "-thash",
        "--tree-hash",
        metavar="<string>",
        default="",
        type=str,
        help="Tip of tree hash",
    )
    parser.add_argument(
        "-bstatus",
        "--base-status",
        required=True,
        metavar="<string>",
        type=str,
        help="Baseline status",
    )
    parser.add_argument(
        "-tstatus",
        "--tree-status",
        required=True,
        metavar="<string>",
        type=str,
        help="Tip of tree status",
    )
    parser.add_argument(
        "-o",
        "--output-markdown",
        default="./issue.md",
        metavar="<filename>",
        type=str,
        help="Output file name",
    )
    parser.add_argument(
        "--postcommit-repo",
        default=DEFAULT_POSTCOMMIT_REPOSITORY,
        metavar="<owner/repo>",
        type=str,
        help="Post-commit repository used for baseline issue links",
    )
    return parser.parse_args()


def build_status(bhash: str, thash: str, bstatus: str, tstatus: str):
    result = "## Apply Status\n"
    result += "|Target|Status|\n"
    result += "|---|---|\n"
    result += (
        f"|Baseline hash: https://github.com/gcc-mirror/gcc/commit/{bhash}|{bstatus}|\n"
    )
    thash = (
        "pending"
        if thash == ""
        else f"https://github.com/gcc-mirror/gcc/commit/{thash}"
    )
    result += f"|Tip of tree hash: {thash}|{tstatus}|\n"
    return result


def git_log_wrapper(logfile: str, hash: str):
    result = "## Git log\n"
    result += "git log --oneline from the most recently applied patch to the baseline\n"
    result += "```\n"
    result += f"> git log --oneline {hash}^..HEAD\n"
    with open(logfile, "r") as f:
        result += f.read()
    result += "```\n\n"
    return result


def generate_report(
    patch_name: str,
    bhash: str,
    thash: str,
    bstatus: str,
    tstatus: str,
    postcommit_repo: str = DEFAULT_POSTCOMMIT_REPOSITORY,
):
    result = ""
    if bstatus != "pending":
        bstatus = "Applied" if bstatus == "true" else "Failed"
    if tstatus != "pending":
        tstatus = "Applied" if tstatus == "true" else "Failed"
    result += build_status(bhash, thash, bstatus, tstatus)
    result += "\n"
    if bstatus == "pending" and tstatus == "pending":
        return result
    if bstatus == "Failed" and tstatus == "Failed":
        result += "## Command\n"
        result += "```\n"
        result += (
            "> git am ../patches/*.patch --whitespace=fix -q --3way --empty=drop\n"
        )
        result += "```\n"
        result += "## Output\n"
        result += "```\n"
        with open("gcc/out_tot", "r") as f:
            result += f.read()
        result += "```"
    elif bstatus == "Failed" and tstatus == "Applied":
        result += git_log_wrapper("gcc/git_log_tot.txt", thash)
        result += "## Notes\n"
        baseline_url = (
            f"https://github.com/{postcommit_repo}/issues?q=is%3Aissue+{bhash}"
        )
        result += f"""Failed to apply to the [post-commit baseline]({baseline_url}). This can happen
if your commit requires a recently-commited patch in order to apply.
The pre-commit CI will only perform a build since it doesn't know what
dejagnu testsuite failures are expected on the tip-of-tree.

If you would like this patch re-run once the [baseline]({baseline_url}) reaches a
different hash, open an issue in the RISE pre-commit CI repository with a link
to your patch and the desired baseline.
"""
    elif bstatus == "Applied" and tstatus == "Failed":
        result += git_log_wrapper("gcc/git_log_bl.txt", bhash)
        result += "## Notes\n"
        result += """Failed to apply to tip-of-tree. The patch will still
be tested against the baseline hash. A rebase may be necessary
before merging.
"""
    else:
        result += git_log_wrapper("gcc/git_log_bl.txt", bhash)
        result += "## Notes\n"
        result += "Patch applied successfully"

    result += "\n"

    return result


def main():
    args = parse_arguments()
    issue = generate_report(
        args.patch_name,
        args.base_hash,
        args.tree_hash,
        args.base_status,
        args.tree_status,
        args.postcommit_repo,
    )
    with open(args.output_markdown, "w") as f:
        f.write(issue)


if __name__ == "__main__":
    main()
