from pathlib import Path
import sys

import pytest

scripts_path = Path(__file__).parent.parent.parent.parent / "scripts"
sys.path.append(str(scripts_path))

import check_migration_guards


@pytest.mark.parametrize(
    "legacy_reference",
    [
        "rivos" + "cibot",
        "toolchain-ci-" + "rivos" + "-test",
        "patchworks-ci@" + "rivosinc.com",
    ],
)
def test_guard_rejects_legacy_patchwork_ownership(
    monkeypatch, tmp_path, legacy_reference
):
    active_file = tmp_path / "active.py"
    active_file.write_text(legacy_reference)
    monkeypatch.setattr(check_migration_guards, "active_files", lambda: [active_file])

    assert check_migration_guards.main() == 1


def test_guard_accepts_rise_owned_references(monkeypatch, tmp_path):
    active_file = tmp_path / "active.py"
    active_file.write_text("rise-ci-bot toolchain-ci-rise-test ci@riseproject.dev")
    monkeypatch.setattr(check_migration_guards, "active_files", lambda: [active_file])

    assert check_migration_guards.main() == 0
