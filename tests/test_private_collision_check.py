from __future__ import annotations

import importlib.util
import io
import pytest
import subprocess
import tarfile
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


def test_scanner_recurses_into_nested_source_distribution_without_disclosure(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    dist = repo / "dist"
    dist.mkdir()

    inner_bytes = io.BytesIO()
    private_payload = b'CITY = "Privateville"\n'
    with tarfile.open(fileobj=inner_bytes, mode="w:gz") as inner:
        info = tarfile.TarInfo("inner/tests/private_fixture.py")
        info.size = len(private_payload)
        inner.addfile(info, io.BytesIO(private_payload))

    outer = dist / "outer-1.0.tar.gz"
    nested_payload = inner_bytes.getvalue()
    with tarfile.open(outer, mode="w:gz") as archive:
        info = tarfile.TarInfo("outer/release/packages/inner-1.0.tar.gz")
        info.size = len(nested_payload)
        archive.addfile(info, io.BytesIO(nested_payload))

    collisions = collision_tool.scan_repository(repo, _profile(), dist)
    report = collision_tool.render_collisions(collisions)

    assert any(category == "candidate_city" for category, _label, _count in collisions)
    assert outer.name in report
    assert "inner-1.0.tar.gz" in report
    assert "privateville" not in report.casefold()


def test_scanner_includes_nonignored_untracked_publishable_files(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    (repo / "untracked.py").write_text('SCHOOL = "North Star University"\n', encoding="utf-8")

    collisions = collision_tool.scan_repository(repo, _profile())

    assert any(category == "education_school" for category, _label, _count in collisions)
    assert any("tree:untracked.py" in label for _category, label, _count in collisions)


def test_scanner_includes_extensionless_publishable_files_but_not_ignored_files(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    (repo / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (repo / "LICENSE").write_text("North Star University\n", encoding="utf-8")
    (repo / "ignored.py").write_text('SCHOOL = "North Star University"\n', encoding="utf-8")

    collisions = collision_tool.scan_repository(repo, _profile())

    labels = {label for _category, label, _count in collisions}
    assert any(label == "tree:LICENSE" for label in labels)
    assert all("ignored.py" not in label for label in labels)


def test_private_scanner_rejects_oversized_outer_archive_before_read(tmp_path, monkeypatch) -> None:
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("example/data.txt", "safe")
    monkeypatch.setattr(collision_tool, "MAX_OUTER_ARCHIVE_BYTES", 1)

    with pytest.raises(ValueError, match="outer archive"):
        collision_tool._scan_archive(wheel, collision_tool.collect_private_values(_profile()))


def test_private_tar_scanner_iterates_without_materializing_member_list(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "example-1.0.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        payload = b"safe"
        info = tarfile.TarInfo("example/data.txt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    monkeypatch.setattr(
        tarfile.TarFile,
        "getmembers",
        lambda _self: (_ for _ in ()).throw(AssertionError("member list materialized")),
    )

    assert collision_tool._scan_archive(archive_path, collision_tool.collect_private_values(_profile())) == []


def test_private_zip_budget_fails_before_any_member_payload_read(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(archive_path, mode="w") as archive:
        archive.writestr("example/one.txt", "12")
        archive.writestr("example/two.txt", "34")

    monkeypatch.setattr(collision_tool, "MAX_ARCHIVE_TOTAL_BYTES", 3)
    monkeypatch.setattr(
        zipfile.ZipFile,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("payload read before preflight")),
    )

    with pytest.raises(ValueError, match="expansion"):
        collision_tool._scan_archive(archive_path, collision_tool.collect_private_values(_profile()))


def test_private_tar_budget_fails_before_any_member_payload_read(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "example-1.0.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        for name in ("one.txt", "two.txt"):
            payload = b"12"
            info = tarfile.TarInfo(f"example/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    monkeypatch.setattr(collision_tool, "MAX_ARCHIVE_TOTAL_BYTES", 3)
    monkeypatch.setattr(
        tarfile.TarFile,
        "extractfile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("payload read before preflight")),
    )

    with pytest.raises(ValueError, match="expansion"):
        collision_tool._scan_archive(archive_path, collision_tool.collect_private_values(_profile()))


def test_private_archive_budget_counts_directory_members(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(archive_path, mode="w") as archive:
        archive.writestr("example/one/", "")
        archive.writestr("example/two/", "")

    monkeypatch.setattr(collision_tool, "MAX_ARCHIVE_MEMBERS", 1)

    with pytest.raises(ValueError, match="member limit"):
        collision_tool._scan_archive(archive_path, collision_tool.collect_private_values(_profile()))


def test_private_zip_count_fails_before_zipfile_constructor(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(archive_path, mode="w") as archive:
        archive.writestr("example/one.txt", "1")
        archive.writestr("example/two.txt", "2")

    monkeypatch.setattr(collision_tool, "MAX_ARCHIVE_MEMBERS", 1)
    monkeypatch.setattr(
        zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ZipFile constructed before preflight")),
    )

    with pytest.raises(ValueError, match="member limit"):
        collision_tool._scan_archive(archive_path, collision_tool.collect_private_values(_profile()))


def test_private_zip_metadata_fails_before_zipfile_constructor(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(archive_path, mode="w") as archive:
        archive.writestr("example/data.txt", "safe")

    monkeypatch.setattr(collision_tool, "MAX_ARCHIVE_METADATA_BYTES", 1)
    monkeypatch.setattr(
        zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ZipFile constructed before preflight")),
    )

    with pytest.raises(ValueError, match="metadata limit"):
        collision_tool._scan_archive(archive_path, collision_tool.collect_private_values(_profile()))


def test_private_tar_expansion_fails_before_tarfile_constructor(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "example-1.0.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        payload = b"12"
        info = tarfile.TarInfo("example/data.txt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    monkeypatch.setattr(collision_tool, "MAX_ARCHIVE_TOTAL_BYTES", 1)
    monkeypatch.setattr(
        tarfile,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("TarFile constructed before preflight")),
    )

    with pytest.raises(ValueError, match="expansion"):
        collision_tool._scan_archive(archive_path, collision_tool.collect_private_values(_profile()))


def test_private_tar_rejects_pax_metadata_before_tarfile_constructor(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "example-1.0.tar.gz"
    with tarfile.open(archive_path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        payload = b"safe"
        info = tarfile.TarInfo(f"example/{'x' * 180}.txt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    monkeypatch.setattr(
        tarfile,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("TarFile constructed before preflight")),
    )

    with pytest.raises(ValueError, match="extended metadata"):
        collision_tool._scan_archive(archive_path, collision_tool.collect_private_values(_profile()))
