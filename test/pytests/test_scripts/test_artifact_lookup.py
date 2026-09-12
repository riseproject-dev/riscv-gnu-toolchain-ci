from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

scripts_path = Path(__file__).parent.parent.parent.parent / "scripts"
sys.path.append(str(scripts_path))

from download_artifact import download_artifact, search_for_artifact


@pytest.mark.parametrize(
    "artifacts, expected",
    [
        ([], None),
        ([SimpleNamespace(id=1, expired=True)], None),
        (
            [SimpleNamespace(id=1, expired=True), SimpleNamespace(id=2, expired=False)],
            "2",
        ),
    ],
)
def test_artifact_lookup_ignores_expired_results(artifacts, expected):
    github = Mock()
    github.get_repo.return_value.get_artifacts.return_value = iter(artifacts)

    assert search_for_artifact("summary", "rise/toolchain", "token", github) == expected
    github.get_repo.return_value.get_artifacts.assert_called_once_with("summary")


@pytest.mark.parametrize("status_code", [403, 404, 410, 500])
def test_artifact_download_rejects_http_errors_before_writing(
    monkeypatch, tmp_path, status_code
):
    response = SimpleNamespace(status_code=status_code, content=b'{"message":"error"}')
    monkeypatch.setattr(
        "download_artifact.requests.get", lambda *_args, **_kwargs: response
    )
    output = tmp_path / "downloads"

    with pytest.raises(requests.HTTPError, match=f"HTTP {status_code}") as error:
        download_artifact("summary", "42", "token", "rise/toolchain", str(output))

    assert error.value.response is response
    assert not output.exists()


def test_artifact_download_writes_successful_response(monkeypatch, tmp_path):
    response = SimpleNamespace(status_code=200, content=b"zip contents")
    monkeypatch.setattr(
        "download_artifact.requests.get", lambda *_args, **_kwargs: response
    )

    result = download_artifact(
        "summary.log", "42", "token", "rise/toolchain", str(tmp_path)
    )

    assert Path(result).name == "summary.zip"
    assert Path(result).read_bytes() == b"zip contents"
