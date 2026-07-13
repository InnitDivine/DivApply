from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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
    path.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "version": 1,
                "components": [],
            }
        ),
        encoding="utf-8",
    )


def test_release_bundle_contains_packages_sbom_and_verified_checksums(tmp_path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "divapply-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "divapply-1.2.3.tar.gz").write_bytes(b"sdist")
    bundle = tmp_path / "release"

    result = assemble_release_bundle(
        dist,
        bundle,
        version="1.2.3",
        export_sbom=_write_fake_sbom,
    )

    assert result == bundle.resolve()
    assert (bundle / "packages" / "divapply-1.2.3-py3-none-any.whl").read_bytes() == b"wheel"
    assert (bundle / "packages" / "divapply-1.2.3.tar.gz").read_bytes() == b"sdist"
    assert json.loads((bundle / "divapply-1.2.3.cdx.json").read_text(encoding="utf-8"))["bomFormat"] == "CycloneDX"
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
    dist.mkdir()
    wheel = dist / "divapply-1.2.3-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    (dist / "divapply-1.2.3.tar.gz").write_bytes(b"sdist")
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
    dist.mkdir()
    (dist / "divapply-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "divapply-1.2.2-py3-none-any.whl").write_bytes(b"stale-wheel")
    (dist / "divapply-1.2.3.tar.gz").write_bytes(b"sdist")

    with pytest.raises(ValueError, match="exactly one wheel and one source distribution"):
        assemble_release_bundle(
            dist,
            tmp_path / "release",
            version="1.2.3",
            export_sbom=_write_fake_sbom,
        )
