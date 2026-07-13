from __future__ import annotations

import importlib.util
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "divapply_private_collision_tool",
    ROOT / "tools" / "check_private_collisions.py",
)
assert SPEC is not None and SPEC.loader is not None
collision_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collision_tool)


def _profile() -> dict:
    return {
        "personal": {
            "full_name": "Private Candidate",
            "email": "private.candidate@example.test",
            "address": "900 Private Lane",
            "city": "Privateville",
            "province_state": "PV",
        },
        "education_schools": [{"school": "North Star University", "city_state": "Privateville, PV"}],
        "references": [{"name": "Private Reference", "address": "Secretburg, PV"}],
    }


def test_collect_private_values_excludes_short_state_but_includes_school() -> None:
    values = collision_tool.collect_private_values(_profile())

    assert ("education_school", "north star university") in values
    assert all(value != "pv" for _category, value in values)


def test_scanner_checks_tracked_tree_and_wheel_without_disclosing_values(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    source = repo / "fixture.py"
    source.write_text('SCHOOL = "North Star University"\n', encoding="utf-8")
    subprocess.run(["git", "add", "fixture.py"], cwd=repo, check=True)

    dist = repo / "dist"
    dist.mkdir()
    wheel = dist / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("example/data.txt", "private.candidate@example.test")

    collisions = collision_tool.scan_repository(repo, _profile(), dist)
    report = collision_tool.render_collisions(collisions)

    assert {item[0] for item in collisions} >= {"candidate_email", "education_school"}
    assert "tree:fixture.py" in report
    assert wheel.name in report
    assert "North Star University" not in report
    assert "private.candidate@example.test" not in report
