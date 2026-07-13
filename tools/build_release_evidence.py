"""Assemble and verify release packages, CycloneDX SBOM, and SHA256 manifest."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tomllib


ROOT = Path(__file__).resolve().parents[1]
CHECKSUM_NAME = "SHA256SUMS"
CHECKSUM_LINE_RE = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<name>[^\r\n]+)$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(project["project"]["version"])


def _clear_known_bundle_files(bundle: Path) -> Path:
    if bundle.is_symlink() or (bundle.exists() and not bundle.is_dir()):
        raise ValueError("release bundle must be a regular directory")
    bundle.mkdir(parents=True, exist_ok=True)
    packages = bundle / "packages"
    if packages.is_symlink() or (packages.exists() and not packages.is_dir()):
        raise ValueError("release package directory must not be a link or file")
    packages.mkdir(exist_ok=True)

    for child in bundle.iterdir():
        if child == packages:
            continue
        if child.is_symlink() or child.is_dir():
            raise ValueError(f"unexpected release bundle entry: {child.name}")
        if child.name == CHECKSUM_NAME or child.name.endswith(".cdx.json"):
            child.unlink()
        else:
            raise ValueError(f"unexpected release bundle entry: {child.name}")
    for child in packages.iterdir():
        if child.is_symlink() or not child.is_file():
            raise ValueError(f"unexpected release package entry: {child.name}")
        if child.suffix == ".whl" or child.name.endswith(".tar.gz"):
            child.unlink()
        else:
            raise ValueError(f"unexpected release package entry: {child.name}")
    return packages


def _default_export_sbom(destination: Path) -> None:
    subprocess.run(
        [
            "uv",
            "export",
            "--preview-features",
            "sbom-export",
            "--quiet",
            "--locked",
            "--no-dev",
            "--extra",
            "full",
            "--format",
            "cyclonedx1.5",
            "--output-file",
            str(destination),
        ],
        cwd=ROOT,
        check=True,
    )


def _validate_sbom(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("release SBOM is not valid JSON") from exc
    if payload.get("bomFormat") != "CycloneDX" or payload.get("specVersion") != "1.5":
        raise ValueError("release SBOM must be CycloneDX 1.5")
    if not isinstance(payload.get("components"), list):
        raise ValueError("release SBOM components must be a list")


def _bundle_subjects(bundle: Path) -> list[Path]:
    packages = bundle / "packages"
    package_files = [
        path
        for path in packages.iterdir()
        if path.is_file() and not path.is_symlink() and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
    ]
    sboms = [path for path in bundle.glob("*.cdx.json") if path.is_file() and not path.is_symlink()]
    return sorted([*package_files, *sboms], key=lambda path: path.relative_to(bundle).as_posix())


def _write_checksums(bundle: Path) -> None:
    lines = [
        f"{_sha256(path)}  {path.relative_to(bundle).as_posix()}"
        for path in _bundle_subjects(bundle)
    ]
    (bundle / CHECKSUM_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def assemble_release_bundle(
    dist_dir: Path,
    bundle_dir: Path,
    *,
    version: str | None = None,
    export_sbom: Callable[[Path], None] | None = None,
) -> Path:
    """Copy built packages, export a locked SBOM, and write verified checksums."""
    dist = dist_dir.expanduser().resolve()
    bundle = bundle_dir.expanduser().resolve()
    if not dist.is_dir():
        raise ValueError("distribution directory does not exist")
    release_version = version or _project_version()
    wheel_files = sorted(path for path in dist.glob("*.whl") if path.is_file() and not path.is_symlink())
    sdist_files = sorted(path for path in dist.glob("*.tar.gz") if path.is_file() and not path.is_symlink())
    if len(wheel_files) != 1 or len(sdist_files) != 1:
        raise ValueError("release requires exactly one wheel and one source distribution")
    expected_prefix = f"divapply-{release_version}"
    if not wheel_files[0].name.startswith(f"{expected_prefix}-") or sdist_files[0].name != f"{expected_prefix}.tar.gz":
        raise ValueError("release package filenames do not match project version")

    packages = _clear_known_bundle_files(bundle)
    for source in [*wheel_files, *sdist_files]:
        shutil.copyfile(source, packages / source.name)

    sbom = bundle / f"divapply-{release_version}.cdx.json"
    (export_sbom or _default_export_sbom)(sbom)
    _validate_sbom(sbom)
    _write_checksums(bundle)
    verify_release_bundle(bundle)
    return bundle


def verify_release_bundle(bundle_dir: Path) -> None:
    """Validate manifest shape, containment, subject set, and every SHA256 digest."""
    bundle = bundle_dir.expanduser().resolve()
    manifest = bundle / CHECKSUM_NAME
    if not manifest.is_file() or manifest.is_symlink():
        raise ValueError("release checksum manifest is missing or unsafe")
    entries: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = CHECKSUM_LINE_RE.fullmatch(line)
        if match is None:
            raise ValueError("release checksum manifest has an invalid line")
        name = match.group("name")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ValueError("release checksum path is unsafe")
        candidate = bundle / relative
        try:
            candidate.resolve().relative_to(bundle)
        except (OSError, ValueError) as exc:
            raise ValueError("release checksum path escapes bundle") from exc
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"release checksum subject is missing or unsafe: {name}")
        entries[name] = match.group("digest")

    expected_names = {path.relative_to(bundle).as_posix() for path in _bundle_subjects(bundle)}
    if set(entries) != expected_names or not entries:
        raise ValueError("release checksum subjects do not match bundle")
    for name, expected in entries.items():
        if _sha256(bundle / Path(name)) != expected:
            raise ValueError(f"release checksum mismatch: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "release")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify_release_bundle(args.out_dir)
        print(f"Verified release evidence: {args.out_dir}")
    else:
        bundle = assemble_release_bundle(args.dist_dir, args.out_dir)
        print(f"Release evidence written: {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
