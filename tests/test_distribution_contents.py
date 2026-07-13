from __future__ import annotations

import importlib.util
import io
import os
import stat
import tarfile
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "divapply_distribution_contents_tool",
    ROOT / "tools" / "check_distribution_contents.py",
)
assert SPEC is not None and SPEC.loader is not None
distribution_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(distribution_tool)


def _add_tar_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


class _SwapOnClose:
    def __init__(self, stream: Any, swap) -> None:
        self._stream = stream
        self._swap = swap

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)

    def __enter__(self) -> _SwapOnClose:
        self._stream.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        try:
            return self._stream.__exit__(*args)
        finally:
            self._swap()


def test_distribution_manifest_rejects_runtime_outputs_and_nested_archives(tmp_path) -> None:
    sdist = tmp_path / "example-1.0.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(archive, "example-1.0/src/example/__init__.py", b"")
        _add_tar_bytes(archive, "example-1.0/.coverage", b"coverage data")
        _add_tar_bytes(archive, "example-1.0/release/SHA256SUMS", b"hash")
        _add_tar_bytes(archive, "example-1.0/release/packages/old-0.9.tar.gz", b"nested")

    issues = distribution_tool.validate_archive(sdist)
    codes = {code for code, _location in issues}

    assert "runtime_artifact" in codes
    assert "release_output" in codes
    assert "nested_archive" in codes


def test_distribution_manifest_accepts_expected_source_and_wheel_files(tmp_path) -> None:
    sdist = tmp_path / "example-1.0.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(archive, "example-1.0/src/example/__init__.py", b"")
        _add_tar_bytes(archive, "example-1.0/.env.example", b"SAFE_EXAMPLE=")
        _add_tar_bytes(archive, "example-1.0/README.md", b"Example")

    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("example/__init__.py", "")
        archive.writestr("example-1.0.dist-info/METADATA", "Name: example")

    assert distribution_tool.validate_archive(sdist) == []
    assert distribution_tool.validate_archive(wheel) == []


def test_distribution_manifest_rejects_links(tmp_path) -> None:
    sdist = tmp_path / "example-1.0.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        link = tarfile.TarInfo("example-1.0/src/example/escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../profile.json"
        archive.addfile(link)

    assert any(code == "non_regular_member" for code, _location in distribution_tool.validate_archive(sdist))


def test_divapply_distribution_manifest_rejects_files_outside_runtime_roots(tmp_path) -> None:
    sdist = tmp_path / "divapply-1.2.3.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(archive, "divapply-1.2.3/src/divapply/__init__.py", b"")
        _add_tar_bytes(archive, "divapply-1.2.3/private-notes.txt", b"not allowed")

    wheel = tmp_path / "divapply-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("divapply/__init__.py", "")
        archive.writestr("unrelated/private_notes.py", "")

    assert any(code == "unexpected_member" for code, _location in distribution_tool.validate_archive(sdist))
    assert any(code == "unexpected_member" for code, _location in distribution_tool.validate_archive(wheel))


def test_distribution_set_requires_one_matching_wheel_and_sdist(tmp_path) -> None:
    assert any(code == "missing_distribution" for code, _location in distribution_tool.scan_dist(tmp_path))

    sdist = tmp_path / "divapply-1.2.3.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(archive, "divapply-1.2.3/src/divapply/__init__.py", b"")
    wheel = tmp_path / "divapply-1.2.4-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("divapply/__init__.py", "")
        archive.writestr("divapply-1.2.4.dist-info/METADATA", "Name: divapply")

    assert any(code == "version_mismatch" for code, _location in distribution_tool.scan_dist(tmp_path))

    extra = tmp_path / "stale-0.9-py3-none-any.whl"
    with zipfile.ZipFile(extra, mode="w") as archive:
        archive.writestr("stale/__init__.py", "")

    assert any(code == "unexpected_archive" for code, _location in distribution_tool.scan_dist(tmp_path))


def test_archive_rejects_noncanonical_duplicate_case_collision_and_redacts_names(tmp_path) -> None:
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("example/./private-profile.py", "secret")
        archive.writestr("example/Case.py", "one")
        archive.writestr("example/case.py", "two")
        archive.writestr("example/C:/payload.py", "drive")
        archive.writestr("example/control\x01.py", "control")

    issues = distribution_tool.validate_archive(wheel)
    codes = {code for code, _location in issues}
    rendered = "\n".join(f"{code}\t{location}" for code, location in issues)

    assert "unsafe_member_path" in codes
    assert "case_collision" in codes
    assert "private-profile.py" not in rendered
    assert all("member#" in location for _code, location in issues)


def test_distribution_rejects_zip_special_types_and_out_of_root_directory(tmp_path) -> None:
    wheel = tmp_path / "divapply-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("divapply/__init__.py", "")
        archive.writestr("divapply-1.2.3.dist-info/METADATA", "Name: divapply")
        archive.writestr("outside/", "")
        fifo = zipfile.ZipInfo("divapply/fifo")
        fifo.create_system = 3
        fifo.external_attr = (stat.S_IFIFO | 0o600) << 16
        archive.writestr(fifo, "")

    codes = {code for code, _location in distribution_tool.validate_archive(wheel)}

    assert "unexpected_member" in codes
    assert "non_regular_member" in codes


def test_archive_budgets_fail_closed(tmp_path, monkeypatch) -> None:
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("example/one.py", "1234")
        archive.writestr("example/two.py", "5678")
        archive.writestr("example/three.py", "9")

    monkeypatch.setattr(distribution_tool, "MAX_ARCHIVE_MEMBERS", 2)
    monkeypatch.setattr(distribution_tool, "MAX_MEMBER_BYTES", 3)
    monkeypatch.setattr(distribution_tool, "MAX_TOTAL_EXPANDED_BYTES", 6)

    codes = {code for code, _location in distribution_tool.validate_archive(wheel)}

    assert "member_count_limit" in codes
    assert "member_size_limit" in codes
    assert "expanded_size_limit" in codes


def test_distribution_set_binds_to_project_version_and_rejects_extra_entries(tmp_path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "divapply"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    sdist = dist / "divapply-1.2.2.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(archive, "divapply-1.2.2/src/divapply/__init__.py", b"")
    wheel = dist / "divapply-1.2.2-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("divapply/__init__.py", "")
        archive.writestr("divapply-1.2.2.dist-info/METADATA", "Name: divapply")
    (dist / "notes.txt").write_text("unexpected", encoding="utf-8")

    codes = {code for code, _location in distribution_tool.scan_dist(dist)}

    assert "version_mismatch" in codes
    assert "unexpected_distribution_entry" in codes


def test_distribution_manifest_binds_internal_roots_to_archive_version(tmp_path) -> None:
    sdist = tmp_path / "divapply-1.2.3.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(archive, "divapply-1.2.2/src/divapply/__init__.py", b"")
    wheel = tmp_path / "divapply-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("divapply/__init__.py", "")
        archive.writestr("divapply-1.2.2.dist-info/METADATA", "Name: divapply")

    assert any(code == "unexpected_member" for code, _ in distribution_tool.validate_archive(sdist))
    assert any(code == "unexpected_member" for code, _ in distribution_tool.validate_archive(wheel))


def test_distribution_rejects_extended_or_magic_nested_archives(tmp_path) -> None:
    wheel = tmp_path / "divapply-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("divapply/__init__.py", "")
        archive.writestr("divapply/payload.tar.xz", "not really an archive")
        archive.writestr("divapply/renamed_payload.dat", b"PK\x03\x04nested")
        archive.writestr("divapply-1.2.3.dist-info/METADATA", "Name: divapply")

    codes = {code for code, _location in distribution_tool.validate_archive(wheel)}

    assert "nested_archive" in codes
    assert "nested_archive_magic" in codes


def test_distribution_rejects_c1_control_character_in_member_name(tmp_path) -> None:
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("example/control\x85.py", "unsafe")

    codes = {code for code, _location in distribution_tool.validate_archive(wheel)}

    assert "unsafe_member_path" in codes


def test_distribution_rejects_file_ancestor_conflicts(tmp_path) -> None:
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("example/node", "file")
        archive.writestr("example/node/child.py", "child")

    codes = {code for code, _location in distribution_tool.validate_archive(wheel)}

    assert "path_type_conflict" in codes


def test_distribution_rejects_reverse_order_casefolded_file_ancestor_conflicts(tmp_path) -> None:
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("example/Node/child.py", "child")
        archive.writestr("example/node", "file")

    codes = {code for code, _location in distribution_tool.validate_archive(wheel)}

    assert "path_type_conflict" in codes


def test_distribution_budget_failure_does_not_open_zip_payloads(tmp_path, monkeypatch) -> None:
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("example/one.py", "12")
        archive.writestr("example/two.py", "34")

    monkeypatch.setattr(distribution_tool, "MAX_TOTAL_EXPANDED_BYTES", 3)
    monkeypatch.setattr(
        zipfile.ZipFile,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("payload read after budget failure")),
    )

    codes = {code for code, _location in distribution_tool.validate_archive(wheel)}

    assert "expanded_size_limit" in codes


def test_distribution_budget_failure_does_not_open_tar_payloads(tmp_path, monkeypatch) -> None:
    sdist = tmp_path / "example-1.0.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(archive, "example-1.0/one.py", b"12")
        _add_tar_bytes(archive, "example-1.0/two.py", b"34")

    monkeypatch.setattr(distribution_tool, "MAX_TOTAL_EXPANDED_BYTES", 3)
    monkeypatch.setattr(
        tarfile.TarFile,
        "extractfile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("payload read after budget failure")),
    )

    codes = {code for code, _location in distribution_tool.validate_archive(sdist)}

    assert "expanded_size_limit" in codes


def test_distribution_zip_count_fails_before_zipfile_constructor(tmp_path, monkeypatch) -> None:
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("example/one.py", "1")
        archive.writestr("example/two.py", "2")

    monkeypatch.setattr(distribution_tool, "MAX_ARCHIVE_MEMBERS", 1)
    monkeypatch.setattr(
        zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ZipFile constructed before preflight")),
    )

    codes = {code for code, _location in distribution_tool.validate_archive(wheel)}

    assert "member_count_limit" in codes


def test_distribution_zip_metadata_fails_before_zipfile_constructor(tmp_path, monkeypatch) -> None:
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("example/data.py", "safe")

    monkeypatch.setattr(distribution_tool, "MAX_ARCHIVE_METADATA_BYTES", 1)
    monkeypatch.setattr(
        zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ZipFile constructed before preflight")),
    )

    codes = {code for code, _location in distribution_tool.validate_archive(wheel)}

    assert "archive_metadata_limit" in codes


def test_distribution_tar_expansion_fails_before_tarfile_constructor(tmp_path, monkeypatch) -> None:
    sdist = tmp_path / "example-1.0.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(archive, "example-1.0/data.py", b"12")

    monkeypatch.setattr(distribution_tool, "MAX_TOTAL_EXPANDED_BYTES", 1)
    monkeypatch.setattr(
        tarfile,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("TarFile constructed before preflight")),
    )

    codes = {code for code, _location in distribution_tool.validate_archive(sdist)}

    assert "expanded_size_limit" in codes


def test_distribution_rejects_pax_metadata_before_tarfile_constructor(tmp_path, monkeypatch) -> None:
    sdist = tmp_path / "example-1.0.tar.gz"
    with tarfile.open(sdist, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        _add_tar_bytes(archive, f"example-1.0/{'x' * 180}.py", b"safe")

    monkeypatch.setattr(
        tarfile,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("TarFile constructed before preflight")),
    )

    codes = {code for code, _location in distribution_tool.validate_archive(sdist)}

    assert "archive_metadata_extension" in codes


def test_distribution_zip_parser_uses_same_handle_as_preflight(tmp_path, monkeypatch) -> None:
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    replacement = tmp_path / "replacement.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("example/__init__.py", "safe")
    with zipfile.ZipFile(replacement, mode="w") as archive:
        archive.writestr("example/.coverage", "unchecked replacement")

    original_open = Path.open
    swapped = False

    def swap() -> None:
        nonlocal swapped
        if not swapped:
            replacement.replace(wheel)
            swapped = True

    def swapping_open(candidate, *args, **kwargs):
        stream = original_open(candidate, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        if candidate == wheel and mode == "rb":
            return _SwapOnClose(stream, swap)
        return stream

    monkeypatch.setattr(Path, "open", swapping_open)

    assert distribution_tool.validate_archive(wheel) == []
    assert swapped


def test_distribution_tar_parser_uses_same_handle_as_preflight(tmp_path, monkeypatch) -> None:
    sdist = tmp_path / "example-1.0.tar.gz"
    replacement = tmp_path / "replacement.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(archive, "example-1.0/src/example/__init__.py", b"safe")
    with tarfile.open(replacement, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        _add_tar_bytes(archive, f"example-1.0/{'x' * 180}/.coverage", b"unchecked replacement")

    original_open = Path.open
    swapped = False

    def swap() -> None:
        nonlocal swapped
        if not swapped:
            replacement.replace(sdist)
            swapped = True

    def swapping_open(candidate, *args, **kwargs):
        stream = original_open(candidate, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        if candidate == sdist and mode == "rb":
            return _SwapOnClose(stream, swap)
        return stream

    monkeypatch.setattr(Path, "open", swapping_open)

    assert distribution_tool.validate_archive(sdist) == []
    assert swapped


def test_distribution_zip_rechecks_outer_size_on_live_handle(tmp_path, monkeypatch) -> None:
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    replacement = tmp_path / "replacement.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("example/__init__.py", "safe")
    with zipfile.ZipFile(replacement, mode="w") as archive:
        archive.writestr("example/data.bin", os.urandom(4096))
    assert wheel.stat().st_size < 500 < replacement.stat().st_size

    original_lstat = Path.lstat
    swapped = False

    def swapping_lstat(candidate, *args, **kwargs):
        nonlocal swapped
        metadata = original_lstat(candidate, *args, **kwargs)
        if candidate == wheel and not swapped:
            replacement.replace(wheel)
            swapped = True
        return metadata

    monkeypatch.setattr(distribution_tool, "MAX_OUTER_ARCHIVE_BYTES", 500)
    monkeypatch.setattr(Path, "lstat", swapping_lstat)

    codes = {code for code, _location in distribution_tool.validate_archive(wheel)}

    assert swapped
    assert "outer_size_limit" in codes


def test_distribution_tar_rechecks_outer_size_on_live_handle(tmp_path, monkeypatch) -> None:
    sdist = tmp_path / "example-1.0.tar.gz"
    replacement = tmp_path / "replacement.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        _add_tar_bytes(archive, "example-1.0/src/example/__init__.py", b"safe")
    with tarfile.open(replacement, mode="w:gz") as archive:
        _add_tar_bytes(archive, "example-1.0/data.bin", os.urandom(4096))
    assert sdist.stat().st_size < 500 < replacement.stat().st_size

    original_lstat = Path.lstat
    swapped = False

    def swapping_lstat(candidate, *args, **kwargs):
        nonlocal swapped
        metadata = original_lstat(candidate, *args, **kwargs)
        if candidate == sdist and not swapped:
            replacement.replace(sdist)
            swapped = True
        return metadata

    monkeypatch.setattr(distribution_tool, "MAX_OUTER_ARCHIVE_BYTES", 500)
    monkeypatch.setattr(Path, "lstat", swapping_lstat)

    codes = {code for code, _location in distribution_tool.validate_archive(sdist)}

    assert swapped
    assert "outer_size_limit" in codes


def test_distribution_set_fails_closed_without_project_metadata(tmp_path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / "divapply-1.2.3-py3-none-any.whl", mode="w") as archive:
        archive.writestr("divapply/__init__.py", "")
        archive.writestr("divapply-1.2.3.dist-info/METADATA", "Name: divapply")
    with tarfile.open(dist / "divapply-1.2.3.tar.gz", mode="w:gz") as archive:
        _add_tar_bytes(archive, "divapply-1.2.3/src/divapply/__init__.py", b"")

    codes = {code for code, _location in distribution_tool.scan_dist(dist)}

    assert "project_version_unavailable" in codes


def test_distribution_set_rejects_non_string_project_version(tmp_path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "divapply"\nversion = 123\n',
        encoding="utf-8",
    )

    codes = {code for code, _location in distribution_tool.scan_dist(dist)}

    assert "project_version_unavailable" in codes


def test_distribution_set_rejects_non_regular_project_metadata(tmp_path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (tmp_path / "pyproject.toml").mkdir()

    codes = {code for code, _location in distribution_tool.scan_dist(dist)}

    assert "project_version_unavailable" in codes
