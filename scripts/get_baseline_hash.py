import argparse
import json
import os
import re
from typing import Iterable, List

import requests


DEFAULT_POSTCOMMIT_REPOSITORY = os.environ.get(
    "POSTCOMMIT_REPOSITORY", "riseproject-dev/gcc-postcommit-ci"
)
BASELINE_TITLE_PATTERN = re.compile(r"Testsuite Status ([0-9a-f]{40})")
REQUIRED_BASELINE_LABEL = "valid-baseline"
BLOCKED_BASELINE_LABELS = {
    "build-failure",
    "testsuite-failure",
    "bisect",
    "invalid",
    "staging",
}


class BaselineLookupError(RuntimeError):
    pass


def parse_arguments():
    """parse command line arguments"""
    parser = argparse.ArgumentParser(description="Download valid log artifacts")
    parser.add_argument(
        "-token",
        required=True,
        type=str,
        help="Github access token",
    )
    parser.add_argument(
        "-repo",
        default=DEFAULT_POSTCOMMIT_REPOSITORY,
        type=str,
        help="GitHub repository to search for post-commit baseline issues",
    )
    parser.add_argument(
        "-output",
        default="./baseline.txt",
        type=str,
        help="File to write the selected baseline hash to",
    )
    return parser.parse_args()


def filter_results(issue):
    issue_labels = {label["name"] for label in issue.get("labels", [])}
    return (
        "pull_request" not in issue
        and REQUIRED_BASELINE_LABEL in issue_labels
        and issue_labels.isdisjoint(BLOCKED_BASELINE_LABELS)
        and BASELINE_TITLE_PATTERN.fullmatch(issue.get("title", "")) is not None
    )


def _github_headers(token: str):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"token {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _load_issues_response(response, repo: str):
    if response.status_code != 200:
        raise BaselineLookupError(
            f"GitHub issues request for {repo} failed with HTTP "
            f"{response.status_code}: {response.text[:500]}"
        )
    try:
        issues = response.json()
    except ValueError as exc:
        raise BaselineLookupError(
            f"GitHub issues request for {repo} returned invalid JSON"
        ) from exc
    if not isinstance(issues, list):
        raise BaselineLookupError(
            f"GitHub issues request for {repo} returned {type(issues).__name__}, "
            "expected a list of issues"
        )
    return issues


def fetch_issues(repo: str, token: str, per_page: int = 100) -> List[dict]:
    url = f"https://api.github.com/repos/{repo}/issues"
    params = {"state": "all", "per_page": per_page}
    issues: List[dict] = []

    while url:
        response = requests.get(
            url,
            headers=_github_headers(token),
            params=params,
            timeout=15 * 60,
        )
        params = None
        issues.extend(_load_issues_response(response, repo))
        url = response.links.get("next", {}).get("url")

    if not issues:
        raise BaselineLookupError(f"No issues were returned from {repo}")
    return issues


def select_baseline_hash(issues: Iterable[dict]) -> str:
    filtered = [issue for issue in issues if filter_results(issue)]
    if not filtered:
        raise BaselineLookupError(
            "No valid post-commit baseline issue was found. Expected an open or "
            "closed issue titled exactly 'Testsuite Status <40-hex-gcc-hash>' "
            "with the valid-baseline label and without build-failure, "
            "testsuite-failure, bisect, invalid, or staging labels."
        )
    issue = filtered[0]
    print(f"Baseline from {issue['title']}")
    match = BASELINE_TITLE_PATTERN.fullmatch(issue["title"])
    assert match is not None
    return match.group(1)


def parse_baseline_hash(repo: str, token: str, output: str = "./baseline.txt") -> str:
    baseline_hash = select_baseline_hash(fetch_issues(repo, token))
    with open(output, "w") as f:
        f.write(baseline_hash)
    return baseline_hash


def main():
    args = parse_arguments()
    parse_baseline_hash(args.repo, args.token, args.output)


if __name__ == "__main__":
    main()
