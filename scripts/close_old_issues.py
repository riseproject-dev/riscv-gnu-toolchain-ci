import argparse
import json
import os

from datetime import datetime

import requests


DEFAULT_PRECOMMIT_REPOSITORY = os.environ.get(
    "PRECOMMIT_REPOSITORY", "riseproject-dev/gcc-precommit-ci"
)


def parse_arguments():
    """parse command line arguments"""
    parser = argparse.ArgumentParser(description="Auto close issues")
    parser.add_argument(
        "-token",
        required=True,
        type=str,
        help="Github access token",
    )
    parser.add_argument(
        "-repo",
        default=DEFAULT_PRECOMMIT_REPOSITORY,
        type=str,
        help="GitHub repository containing pre-commit issues to close",
    )
    return parser.parse_args()


def get_issues(token: str, repo: str = DEFAULT_PRECOMMIT_REPOSITORY):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"token {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params = {"per_page": 100, "state": "open"}
    url = f"https://api.github.com/repos/{repo}/issues"
    r = requests.get(url, headers=headers, params=params)
    if r.status_code != 200:
        raise RuntimeError(
            f"Failed to list open issues from {repo}: HTTP {r.status_code}"
        )
    issues = json.loads(r.text)
    filtered = [issue for issue in issues if "pull_request" not in issue.keys()]
    return filtered


def get_patch_id(issue):
    body = issue["body"].split("\n")
    for line in body:
        if line == "":
            continue
        if "Patch id:" in line:
            patch_id = line.split(":")[-1].strip()
            return patch_id
    return None


def get_patch_state(patch_id: str):
    url = f"https://patchwork.sourceware.org/api/1.3/patches/{patch_id}"
    r = requests.get(url)
    details = json.loads(r.text)
    return details["state"]


def check_issue_is_closable(issue):
    patch_id = get_patch_id(issue)
    if patch_id is None:
        return False
    patch_state = get_patch_state(patch_id)
    print(f"patch {patch_id} state: {patch_state}")
    if patch_state != "committed" and patch_state != "superseded":
        return False
    created_time = datetime.strptime(issue["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    now = datetime.now()
    diff = now - created_time
    print(f"patch {patch_id} has an issue that has been open for {diff} days")
    if diff.days < 7:
        return False
    print(f"patch {patch_id} can be closed")
    return True


def close_issue(
    issue_number: int, token: str, repo: str = DEFAULT_PRECOMMIT_REPOSITORY
):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"token {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    data = {"state": "closed"}
    r = requests.patch(url=url, data=json.dumps(data), headers=headers)
    print(f"closing issue: {issue_number}")
    print(r.status_code)
    print(r.text)


def main():
    args = parse_arguments()
    issues = get_issues(args.token, args.repo)
    for issue in issues:
        if check_issue_is_closable(issue):
            close_issue(issue["number"], args.token, args.repo)


if __name__ == "__main__":
    main()
