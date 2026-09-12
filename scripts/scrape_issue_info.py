import argparse
import json
import os

import requests


DEFAULT_POSTCOMMIT_REPOSITORY = os.environ.get(
    "POSTCOMMIT_REPOSITORY", "riseproject-dev/gcc-postcommit-ci"
)


def parse_arguments():
    """parse command line arguments"""
    parser = argparse.ArgumentParser(description="Get issue information")
    parser.add_argument(
        "-num",
        required=True,
        type=str,
        help="Issue number to get information for",
    )
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
        help="GitHub repository containing the post-commit issue",
    )
    return parser.parse_args()


def get_issue_hash(
    issue_num: str, token: str, repo: str = DEFAULT_POSTCOMMIT_REPOSITORY
):
    issue_url = f"https://api.github.com/repos/{repo}/issues/{issue_num}"
    params = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"token {token}",
        "X-Github-Api-Version": "2022-11-28",
    }
    r = requests.get(issue_url, headers=params)
    if r.status_code != 200:
        raise RuntimeError(
            f"Failed to read issue {issue_num} from {repo}: HTTP {r.status_code}"
        )
    response = json.loads(r.text)
    if "title" not in response:
        raise RuntimeError(f"Issue {issue_num} from {repo} did not include a title")
    print(response["title"].split(" ")[-1])


def main():
    args = parse_arguments()
    get_issue_hash(args.num, args.token, args.repo)


if __name__ == "__main__":
    main()
