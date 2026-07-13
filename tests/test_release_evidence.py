from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import tarfile
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "divapply_release_evidence_tool",
    ROOT / "tools" / "build_release_evidence.py",
)
assert SPEC is not None and SPEC.loader is not None
release_evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_evidence)
assemble_release_bundle = release_evidence.assemble_release_bundle
verify_release_bundle = release_evidence.verify_release_bundle


def _write_fake_sbom(path: Path) -> None:
    root_ref = "divapply-1@1.2.3"
    path.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "version": 1,
                "metadata": {
                    "component": {
                        "bom-ref": root_ref,
                        "name": "divapply",
                        "type": "library",
                        "version": "1.2.3",
                    }
                },
                "components": [],
                "dependencies": [{"ref": root_ref, "dependsOn": []}],
            }
        ),
        encoding="utf-8",
    )


def _write_valid_dist(dist: Path, version: str = "1.2.3") -> tuple[Path, Path]:
    dist.mkdir(exist_ok=True)
    (dist.parent / "pyproject.toml").write_text(
        f'[project]\nname = "divapply"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    wheel = dist / f"divapply-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("divapply/__init__.py", "")
        archive.writestr(f"divapply-{version}.dist-info/METADATA", "Name: divapply")
    sdist = dist / f"divapply-{version}.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        payload = b""
        info = tarfile.TarInfo(f"divapply-{version}/src/divapply/__init__.py")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return wheel, sdist


def test_release_bundle_contains_packages_sbom_and_verified_checksums(tmp_path) -> None:
    dist = tmp_path / "dist"
    wheel, sdist = _write_valid_dist(dist)
    bundle = tmp_path / "release"

    result = assemble_release_bundle(
        dist,
        bundle,
        version="1.2.3",
        export_sbom=_write_fake_sbom,
    )

    assert result == bundle.resolve()
    assert (bundle / "packages" / wheel.name).read_bytes() == wheel.read_bytes()
    assert (bundle / "packages" / sdist.name).read_bytes() == sdist.read_bytes()
    sbom = json.loads((bundle / "divapply-1.2.3.cdx.json").read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX"
    jobspy = next(component for component in sbom["components"] if component["name"] == "python-jobspy")
    assert jobspy["version"] == "1.1.82"
    assert jobspy["bom-ref"] == "pkg:pypi/python-jobspy@1.1.82"
    assert jobspy["purl"] == "pkg:pypi/python-jobspy@1.1.82"
    assert jobspy["hashes"] == [
        {
            "alg": "SHA-256",
            "content": "93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9",
        }
    ]
    dependencies = {dependency["ref"]: dependency for dependency in sbom["dependencies"]}
    root_ref = sbom["metadata"]["component"]["bom-ref"]
    assert "pkg:pypi/python-jobspy@1.1.82" in dependencies[root_ref]["dependsOn"]
    assert "pkg:pypi/python-jobspy@1.1.82" in dependencies
    checksum_lines = (bundle / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    checksum_names = [line.split("  ", 1)[1] for line in checksum_lines]
    assert checksum_names == sorted(checksum_names)
    assert len(checksum_lines) == 3
    assert all("SHA256SUMS" not in line for line in checksum_lines)
    verify_release_bundle(bundle)

    assemble_release_bundle(
        dist,
        bundle,
        version="1.2.3",
        export_sbom=_write_fake_sbom,
    )
    verify_release_bundle(bundle)


def test_release_bundle_verification_rejects_tampering(tmp_path) -> None:
    dist = tmp_path / "dist"
    wheel, _sdist = _write_valid_dist(dist)
    bundle = tmp_path / "release"
    assemble_release_bundle(
        dist,
        bundle,
        version="1.2.3",
        export_sbom=_write_fake_sbom,
    )
    (bundle / "packages" / wheel.name).write_bytes(b"tampered")

    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_release_bundle(bundle)


def test_release_bundle_rejects_stale_duplicate_distributions(tmp_path) -> None:
    dist = tmp_path / "dist"
    _write_valid_dist(dist)
    with zipfile.ZipFile(dist / "divapply-1.2.2-py3-none-any.whl", mode="w") as archive:
        archive.writestr("divapply/__init__.py", "")
        archive.writestr("divapply-1.2.2.dist-info/METADATA", "Name: divapply")

    with pytest.raises(ValueError, match="exactly one wheel and one source distribution"):
        assemble_release_bundle(
            dist,
            tmp_path / "release",
            version="1.2.3",
            export_sbom=_write_fake_sbom,
        )


def test_release_bundle_rejects_invalid_archive_contents(tmp_path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "divapply-1.2.3-py3-none-any.whl").write_bytes(b"not a wheel")
    (dist / "divapply-1.2.3.tar.gz").write_bytes(b"not an sdist")

    with pytest.raises(ValueError, match="distribution content validation failed"):
        assemble_release_bundle(
            dist,
            tmp_path / "release",
            version="1.2.3",
            export_sbom=_write_fake_sbom,
        )


def test_reparse_attribute_is_detected_without_path_is_symlink() -> None:
    class FakeStat:
        st_file_attributes = 0x400

    class FakePath:
        def is_symlink(self) -> bool:
            return False

        def lstat(self) -> FakeStat:
            return FakeStat()

    assert release_evidence._is_link_or_reparse(FakePath()) is True


def test_release_bundle_rejects_reparse_output_before_cleanup(tmp_path, monkeypatch) -> None:
    dist = tmp_path / "dist"
    _write_valid_dist(dist)
    bundle = tmp_path / "release"
    bundle.mkdir()
    sentinel = bundle / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    original = release_evidence._is_link_or_reparse
    monkeypatch.setattr(
        release_evidence,
        "_is_link_or_reparse",
        lambda path: Path(path) == bundle or original(path),
    )

    with pytest.raises(ValueError, match="release bundle must not"):
        assemble_release_bundle(dist, bundle, version="1.2.3", export_sbom=_write_fake_sbom)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_release_bundle_rejects_reparse_packages_before_cleanup(tmp_path, monkeypatch) -> None:
    dist = tmp_path / "dist"
    _write_valid_dist(dist)
    bundle = tmp_path / "release"
    packages = bundle / "packages"
    packages.mkdir(parents=True)
    sentinel = packages / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    original = release_evidence._is_link_or_reparse
    monkeypatch.setattr(
        release_evidence,
        "_is_link_or_reparse",
        lambda path: Path(path) == packages or original(path),
    )

    with pytest.raises(ValueError, match="release package directory"):
        assemble_release_bundle(dist, bundle, version="1.2.3", export_sbom=_write_fake_sbom)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_release_bundle_verifier_rejects_reparse_root(tmp_path, monkeypatch) -> None:
    bundle = tmp_path / "release"
    bundle.mkdir()
    monkeypatch.setattr(
        release_evidence,
        "_is_link_or_reparse",
        lambda path: Path(path) == bundle,
    )

    with pytest.raises(ValueError, match="release bundle must not"):
        verify_release_bundle(bundle)


def test_release_bundle_rejects_reparse_dist_input(tmp_path, monkeypatch) -> None:
    dist = tmp_path / "dist"
    _write_valid_dist(dist)
    original = release_evidence._is_link_or_reparse
    monkeypatch.setattr(
        release_evidence,
        "_is_link_or_reparse",
        lambda path: Path(path) == dist or original(path),
    )

    with pytest.raises(ValueError, match="distribution directory must not"):
        assemble_release_bundle(
            dist,
            tmp_path / "release",
            version="1.2.3",
            export_sbom=_write_fake_sbom,
        )


def test_release_sbom_normalizes_preexisting_jobspy_component_and_root_edge(tmp_path) -> None:
    dist = tmp_path / "dist"
    _write_valid_dist(dist)

    def export_with_jobspy(path: Path) -> None:
        _write_fake_sbom(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["components"].append(
            {
                "type": "library",
                "name": "python-jobspy",
                "version": "1.1.82",
                "hashes": [
                    {
                        "alg": "SHA-256",
                        "content": "93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9",
                    }
                ],
            }
        )
        path.write_text(json.dumps(payload), encoding="utf-8")

    bundle = assemble_release_bundle(
        dist,
        tmp_path / "release",
        version="1.2.3",
        export_sbom=export_with_jobspy,
    )

    payload = json.loads((bundle / "divapply-1.2.3.cdx.json").read_text(encoding="utf-8"))
    jobspy = next(component for component in payload["components"] if component["name"] == "python-jobspy")
    assert jobspy["bom-ref"] == "pkg:pypi/python-jobspy@1.1.82"
    root_ref = payload["metadata"]["component"]["bom-ref"]
    root_node = next(dependency for dependency in payload["dependencies"] if dependency["ref"] == root_ref)
    assert "pkg:pypi/python-jobspy@1.1.82" in root_node["dependsOn"]


def test_release_sbom_fails_closed_without_root_metadata(tmp_path) -> None:
    dist = tmp_path / "dist"
    _write_valid_dist(dist)

    def export_without_root(path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "bomFormat": "CycloneDX",
                    "specVersion": "1.5",
                    "components": [],
                    "dependencies": [],
                }
            ),
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="root component"):
        assemble_release_bundle(
            dist,
            tmp_path / "release",
            version="1.2.3",
            export_sbom=export_without_root,
        )


def test_release_bundle_verifier_rejects_semantically_invalid_sbom_graph(tmp_path) -> None:
    dist = tmp_path / "dist"
    _write_valid_dist(dist)
    bundle = assemble_release_bundle(
        dist,
        tmp_path / "release",
        version="1.2.3",
        export_sbom=_write_fake_sbom,
    )
    sbom_path = bundle / "divapply-1.2.3.cdx.json"
    payload = json.loads(sbom_path.read_text(encoding="utf-8"))
    root_ref = payload["metadata"]["component"]["bom-ref"]
    root_node = next(dependency for dependency in payload["dependencies"] if dependency["ref"] == root_ref)
    root_node["dependsOn"].remove("pkg:pypi/python-jobspy@1.1.82")
    sbom_path.write_text(json.dumps(payload), encoding="utf-8")
    release_evidence._write_checksums(bundle)

    with pytest.raises(ValueError, match="JobSpy dependency edge"):
        verify_release_bundle(bundle)


def test_release_bundle_verifier_rejects_duplicate_manifest_subjects(tmp_path) -> None:
    dist = tmp_path / "dist"
    _write_valid_dist(dist)
    bundle = assemble_release_bundle(
        dist,
        tmp_path / "release",
        version="1.2.3",
        export_sbom=_write_fake_sbom,
    )
    manifest = bundle / "SHA256SUMS"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    manifest.write_text("\n".join([*lines, lines[0]]) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate checksum subject"):
        verify_release_bundle(bundle)
