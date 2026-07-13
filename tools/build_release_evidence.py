"""Assemble and verify release packages, CycloneDX SBOM, and SHA256 manifest."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tomllib


ROOT = Path(__file__).resolve().parents[1]
CHECKSUM_NAME = "SHA256SUMS"
CHECKSUM_LINE_RE = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<name>[^\r\n]+)$")
JOBSPY_VERSION = "1.1.82"
JOBSPY_SHA256 = "93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9"
JOBSPY_BOM_REF = f"pkg:pypi/python-jobspy@{JOBSPY_VERSION}"
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_link_or_reparse(path: Path) -> bool:
    """Return whether a path is a symlink or Windows reparse point."""
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & _REPARSE_POINT)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(project["project"]["version"])


def _validate_distribution_contents(dist: Path) -> None:
    checker_path = ROOT / "tools" / "check_distribution_contents.py"
    spec = importlib.util.spec_from_file_location("divapply_distribution_contents_gate", checker_path)
    if spec is None or spec.loader is None:
        raise ValueError("distribution content validation failed")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    if checker.scan_dist(dist):
        raise ValueError("distribution content validation failed")


def _clear_known_bundle_files(bundle: Path) -> Path:
    if _is_link_or_reparse(bundle) or (bundle.exists() and not bundle.is_dir()):
        raise ValueError("release bundle must be a regular directory")
    bundle.mkdir(parents=True, exist_ok=True)
    packages = bundle / "packages"
    if _is_link_or_reparse(packages) or (packages.exists() and not packages.is_dir()):
        raise ValueError("release package directory must not be a link or file")
    packages.mkdir(exist_ok=True)

    for child in bundle.iterdir():
        if child == packages:
            continue
        if _is_link_or_reparse(child) or child.is_dir():
            raise ValueError(f"unexpected release bundle entry: {child.name}")
        if child.name == CHECKSUM_NAME or child.name.endswith(".cdx.json"):
            child.unlink()
        else:
            raise ValueError(f"unexpected release bundle entry: {child.name}")
    for child in packages.iterdir():
        if _is_link_or_reparse(child) or not child.is_file():
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


def _require_root_ref(payload: dict) -> str:
    metadata = payload.get("metadata")
    root_component = metadata.get("component") if isinstance(metadata, dict) else None
    root_ref = root_component.get("bom-ref") if isinstance(root_component, dict) else None
    if not isinstance(root_ref, str) or not root_ref.strip():
        raise ValueError("release SBOM root component is missing a stable bom-ref")
    return root_ref


def _validate_jobspy_component(components: list) -> None:
    matches = [
        component
        for component in components
        if isinstance(component, dict)
        and str(component.get("name") or "").casefold() in {"python-jobspy", "python_jobspy"}
    ]
    expected_hashes = [{"alg": "SHA-256", "content": JOBSPY_SHA256}]
    if len(matches) != 1:
        raise ValueError("release SBOM must contain exactly one JobSpy component")
    jobspy = matches[0]
    if (
        jobspy.get("version") != JOBSPY_VERSION
        or jobspy.get("hashes") != expected_hashes
        or jobspy.get("purl") != JOBSPY_BOM_REF
        or jobspy.get("bom-ref") != JOBSPY_BOM_REF
    ):
        raise ValueError("release SBOM JobSpy component conflicts with runtime contract")


def _validated_dependency_nodes(dependencies: object) -> dict[str, set[str]]:
    if not isinstance(dependencies, list):
        raise ValueError("release SBOM dependencies must be a list")
    dependency_nodes: dict[str, set[str]] = {}
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise ValueError("release SBOM dependency graph is malformed")
        ref = dependency.get("ref")
        depends_on = dependency.get("dependsOn", [])
        if (
            not isinstance(ref, str)
            or not ref
            or ref in dependency_nodes
            or not isinstance(depends_on, list)
            or any(not isinstance(item, str) or not item for item in depends_on)
        ):
            raise ValueError("release SBOM dependency graph is malformed")
        dependency_nodes[ref] = set(depends_on)
    return dependency_nodes


def _validate_sbom(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("release SBOM is not valid JSON") from exc
    if payload.get("bomFormat") != "CycloneDX" or payload.get("specVersion") != "1.5":
        raise ValueError("release SBOM must be CycloneDX 1.5")
    components = payload.get("components")
    if not isinstance(components, list):
        raise ValueError("release SBOM components must be a list")

    root_ref = _require_root_ref(payload)
    _validate_jobspy_component(components)
    dependency_nodes = _validated_dependency_nodes(payload.get("dependencies"))
    if root_ref not in dependency_nodes or JOBSPY_BOM_REF not in dependency_nodes:
        raise ValueError("release SBOM dependency graph omits a required node")
    if JOBSPY_BOM_REF not in dependency_nodes[root_ref]:
        raise ValueError("release SBOM is missing the JobSpy dependency edge")


def _upsert_jobspy_component(components: list) -> dict:
    matches = [
        component
        for component in components
        if isinstance(component, dict)
        and str(component.get("name") or "").casefold() in {"python-jobspy", "python_jobspy"}
    ]
    expected_hashes = [{"alg": "SHA-256", "content": JOBSPY_SHA256}]
    if matches:
        if len(matches) != 1 or matches[0].get("version") != JOBSPY_VERSION or matches[0].get("hashes") != expected_hashes:
            raise ValueError("release SBOM JobSpy component conflicts with runtime contract")
        jobspy = matches[0]
        for field in ("bom-ref", "purl"):
            if jobspy.get(field) not in {None, "", JOBSPY_BOM_REF}:
                raise ValueError("release SBOM JobSpy component conflicts with runtime contract")
    else:
        jobspy = {
            "type": "library",
            "name": "python-jobspy",
            "version": JOBSPY_VERSION,
            "hashes": expected_hashes,
        }
        components.append(jobspy)

    jobspy.update(
        {
            "type": "library",
            "name": "python-jobspy",
            "version": JOBSPY_VERSION,
            "bom-ref": JOBSPY_BOM_REF,
            "purl": JOBSPY_BOM_REF,
            "hashes": expected_hashes,
        }
    )
    return jobspy


def _normalize_jobspy_properties(jobspy: dict) -> None:
    properties = jobspy.get("properties", [])
    if not isinstance(properties, list) or any(not isinstance(item, dict) for item in properties):
        raise ValueError("release SBOM JobSpy component conflicts with runtime contract")
    properties = [item for item in properties if item.get("name") != "divapply:runtime-install"]
    properties.append(
        {
            "name": "divapply:runtime-install",
            "value": "manual --no-deps hash-verified wheel",
        }
    )
    jobspy["properties"] = properties


def _normalize_dependency_nodes(dependencies: list) -> dict[str, dict[str, object]]:
    dependency_by_ref: dict[str, dict[str, object]] = {}
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise ValueError("release SBOM dependency graph is malformed")
        ref = dependency.get("ref")
        if not isinstance(ref, str) or not ref or ref in dependency_by_ref:
            raise ValueError("release SBOM dependency graph is malformed")
        depends_on = dependency.get("dependsOn", [])
        if not isinstance(depends_on, list) or any(not isinstance(item, str) or not item for item in depends_on):
            raise ValueError("release SBOM dependency graph is malformed")
        dependency["dependsOn"] = sorted(set(depends_on))
        dependency_by_ref[ref] = dependency
    return dependency_by_ref


def _ensure_jobspy_dependency_edge(
    dependencies: list,
    dependency_by_ref: dict[str, dict[str, object]],
    root_ref: str,
) -> None:
    root_node = dependency_by_ref.get(root_ref)
    if root_node is None:
        root_node = {"ref": root_ref, "dependsOn": []}
        dependencies.append(root_node)
        dependency_by_ref[root_ref] = root_node
    root_dependencies = root_node.get("dependsOn", [])
    if not isinstance(root_dependencies, list):  # pragma: no cover - normalized above
        raise ValueError("release SBOM dependency graph is malformed")
    root_node["dependsOn"] = sorted({*root_dependencies, JOBSPY_BOM_REF})

    if JOBSPY_BOM_REF not in dependency_by_ref:
        dependencies.append({"ref": JOBSPY_BOM_REF, "dependsOn": []})
    dependencies.sort(key=lambda dependency: str(dependency["ref"]))


def _supplement_jobspy_runtime(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        components = payload["components"]
        dependencies = payload["dependencies"]
    except (KeyError, OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("release SBOM cannot be supplemented") from exc
    if not isinstance(components, list) or not isinstance(dependencies, list):
        raise ValueError("release SBOM cannot be supplemented")

    root_ref = _require_root_ref(payload)
    jobspy = _upsert_jobspy_component(components)
    _normalize_jobspy_properties(jobspy)
    dependency_by_ref = _normalize_dependency_nodes(dependencies)
    _ensure_jobspy_dependency_edge(dependencies, dependency_by_ref, root_ref)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _bundle_subjects(bundle: Path) -> list[Path]:
    if _is_link_or_reparse(bundle) or not bundle.is_dir():
        raise ValueError("release bundle must be a regular directory")
    packages = bundle / "packages"
    if _is_link_or_reparse(packages) or not packages.is_dir():
        raise ValueError("release package directory must be a regular directory")
    package_files: list[Path] = []
    for path in packages.iterdir():
        if (
            _is_link_or_reparse(path)
            or not path.is_file()
            or not (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
        ):
            raise ValueError(f"unexpected release package entry: {path.name}")
        package_files.append(path)
    sboms: list[Path] = []
    for path in bundle.iterdir():
        if path == packages or path.name == CHECKSUM_NAME:
            continue
        if _is_link_or_reparse(path) or not path.is_file() or not path.name.endswith(".cdx.json"):
            raise ValueError(f"unexpected release bundle entry: {path.name}")
        sboms.append(path)
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
    dist_input = dist_dir.expanduser()
    bundle_input = bundle_dir.expanduser()
    if _is_link_or_reparse(dist_input):
        raise ValueError("distribution directory must not be a link or reparse point")
    if _is_link_or_reparse(bundle_input):
        raise ValueError("release bundle must not be a link or reparse point")
    dist = dist_input.resolve()
    bundle = bundle_input.resolve()
    if not dist.is_dir():
        raise ValueError("distribution directory does not exist")
    release_version = version or _project_version()
    wheel_files = sorted(
        path for path in dist.glob("*.whl") if path.is_file() and not _is_link_or_reparse(path)
    )
    sdist_files = sorted(
        path for path in dist.glob("*.tar.gz") if path.is_file() and not _is_link_or_reparse(path)
    )
    if len(wheel_files) != 1 or len(sdist_files) != 1:
        raise ValueError("release requires exactly one wheel and one source distribution")
    expected_prefix = f"divapply-{release_version}"
    if not wheel_files[0].name.startswith(f"{expected_prefix}-") or sdist_files[0].name != f"{expected_prefix}.tar.gz":
        raise ValueError("release package filenames do not match project version")

    _validate_distribution_contents(dist)

    packages = _clear_known_bundle_files(bundle)
    for source in [*wheel_files, *sdist_files]:
        shutil.copyfile(source, packages / source.name)

    sbom = bundle / f"divapply-{release_version}.cdx.json"
    (export_sbom or _default_export_sbom)(sbom)
    _supplement_jobspy_runtime(sbom)
    _validate_sbom(sbom)
    _write_checksums(bundle)
    verify_release_bundle(bundle)
    return bundle


def _read_checksum_entries(bundle: Path, manifest: Path) -> dict[str, str]:
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
        if _is_link_or_reparse(candidate) or not candidate.is_file():
            raise ValueError(f"release checksum subject is missing or unsafe: {name}")
        if name in entries:
            raise ValueError(f"release checksum manifest has a duplicate checksum subject: {name}")
        entries[name] = match.group("digest")
    return entries


def verify_release_bundle(bundle_dir: Path) -> None:
    """Validate manifest shape, containment, subject set, and every SHA256 digest."""
    bundle_input = bundle_dir.expanduser()
    if _is_link_or_reparse(bundle_input):
        raise ValueError("release bundle must not be a link or reparse point")
    bundle = bundle_input.resolve()
    manifest = bundle / CHECKSUM_NAME
    if not manifest.is_file() or _is_link_or_reparse(manifest):
        raise ValueError("release checksum manifest is missing or unsafe")
    entries = _read_checksum_entries(bundle, manifest)

    expected_names = {path.relative_to(bundle).as_posix() for path in _bundle_subjects(bundle)}
    if set(entries) != expected_names or not entries:
        raise ValueError("release checksum subjects do not match bundle")
    for name, expected in entries.items():
        if _sha256(bundle / Path(name)) != expected:
            raise ValueError(f"release checksum mismatch: {name}")
    for name in entries:
        if name.endswith(".cdx.json"):
            _validate_sbom(bundle / Path(name))


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
