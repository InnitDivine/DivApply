from __future__ import annotations

import argparse
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Any


TEXT_SUFFIXES = {
    ".cmd",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}

Needle = tuple[str, str]
Collision = tuple[str, str, int]


def _add(needles: set[Needle], category: str, value: Any) -> None:
    if value is None or isinstance(value, (dict, list)):
        return
    normalized = str(value).strip().casefold()
    if len(normalized) >= 5:
        needles.add((category, normalized))


def collect_private_values(profile: dict[str, Any]) -> list[Needle]:
    """Return high-confidence private scalars; never return state/country alone."""
    needles: set[Needle] = set()
    personal = profile.get("personal") or {}
    for field in ("full_name", "first_name", "middle_name", "last_name", "email", "phone", "address", "city", "postal_code"):
        _add(needles, f"candidate_{field}", personal.get(field))

    for address in (profile.get("application_addresses") or {}).values():
        if not isinstance(address, dict):
            continue
        for field in ("address", "city", "postal_code"):
            _add(needles, f"alternate_{field}", address.get(field))

    for reference in profile.get("references") or []:
        if not isinstance(reference, dict):
            continue
        for field in ("name", "email", "phone", "address"):
            _add(needles, f"reference_{field}", reference.get(field))
        for part in str(reference.get("address") or "").split(","):
            _add(needles, "reference_locality", part)

    for work in profile.get("work_history") or []:
        if isinstance(work, dict):
            _add(needles, "work_company", work.get("company"))
            _add(needles, "work_location", work.get("location"))

    for school in profile.get("education_schools") or []:
        if isinstance(school, dict):
            _add(needles, "education_school", school.get("school"))
            _add(needles, "education_location", school.get("city_state"))

    for company, address in (profile.get("employer_addresses") or {}).items():
        _add(needles, "employer_name", company)
        if isinstance(address, dict):
            for field in ("address", "city", "postal_code"):
                _add(needles, f"employer_{field}", address.get(field))
        else:
            _add(needles, "employer_address", address)

    return sorted(needles)


def _scan_blob(label: str, payload: bytes, needles: list[Needle]) -> list[Collision]:
    text = payload.decode("utf-8", errors="ignore").casefold()
    return [(category, label, count) for category, value in needles if (count := text.count(value))]


def _tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        candidate = (root / raw.decode("utf-8")).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            continue
        if candidate.suffix.casefold() in TEXT_SUFFIXES:
            paths.append(candidate)
    return paths


def _scan_archive(path: Path, needles: list[Needle]) -> list[Collision]:
    collisions: list[Collision] = []
    if path.suffix.casefold() == ".whl":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith("/"):
                    collisions.extend(_scan_blob(f"{path.name}:{name}", archive.read(name), needles))
    elif path.name.casefold().endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                stream = archive.extractfile(member)
                if stream is not None:
                    collisions.extend(_scan_blob(f"{path.name}:{member.name}", stream.read(), needles))
    return collisions


def scan_repository(root: Path, profile: dict[str, Any], dist_dir: Path | None = None) -> list[Collision]:
    root = root.resolve()
    needles = collect_private_values(profile)
    collisions: list[Collision] = []
    for path in _tracked_files(root):
        collisions.extend(_scan_blob(f"tree:{path.relative_to(root).as_posix()}", path.read_bytes(), needles))

    if dist_dir is not None and dist_dir.is_dir():
        for archive in sorted(dist_dir.iterdir()):
            if archive.suffix.casefold() == ".whl" or archive.name.casefold().endswith(".tar.gz"):
                collisions.extend(_scan_archive(archive, needles))
    return sorted(collisions)


def render_collisions(collisions: list[Collision]) -> str:
    lines = [
        f"PRIVATE_VALUE_COLLISIONS groups={len(collisions)} occurrences={sum(item[2] for item in collisions)}"
    ]
    lines.extend(f"{category}\t{location}\t{count}" for category, location, count in collisions)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect private profile values in publishable repository artifacts.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--dist-dir", type=Path)
    args = parser.parse_args()

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    collisions = scan_repository(args.root, profile, args.dist_dir)
    if collisions:
        print(render_collisions(collisions))
        return 1
    print("Private-value collision scan passed (tree + distributions).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
