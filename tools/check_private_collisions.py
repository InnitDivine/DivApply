from __future__ import annotations

import argparse
import io
import importlib.util
import json
import re
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Any


Needle = tuple[str, str]
Collision = tuple[str, str, int]

MAX_ARCHIVE_DEPTH = 3
MAX_OUTER_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_MEMBER_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_METADATA_BYTES = 16 * 1024 * 1024
MAX_TREE_FILE_BYTES = MAX_ARCHIVE_MEMBER_BYTES
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _load_archive_preflight() -> Any:
    module_path = Path(__file__).with_name("archive_preflight.py")
    spec = importlib.util.spec_from_file_location("divapply_archive_preflight", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("archive metadata preflight is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ARCHIVE_PREFLIGHT = _load_archive_preflight()


class _ArchiveBudget:
    __slots__ = ("members", "total_bytes")

    def __init__(self) -> None:
        self.members = 0
        self.total_bytes = 0

    def consume(self, size: int) -> None:
        if size < 0 or size > MAX_ARCHIVE_MEMBER_BYTES:
            raise ValueError("archive member exceeds private-scan size limit")
        self.members += 1
        self.total_bytes += size
        if self.members > MAX_ARCHIVE_MEMBERS:
            raise ValueError("archive exceeds private-scan member limit")
        if self.total_bytes > MAX_ARCHIVE_TOTAL_BYTES:
            raise ValueError("archive exceeds private-scan expansion limit")


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


def _redact_label(label: str, needles: list[Needle]) -> str:
    safe = label
    for _category, value in needles:
        safe = re.sub(re.escape(value), "[redacted]", safe, flags=re.IGNORECASE)
    return safe


def _scan_blob(label: str, payload: bytes, needles: list[Needle]) -> list[Collision]:
    text = payload.decode("utf-8", errors="ignore").casefold()
    safe_label = _redact_label(label, needles)
    return [(category, safe_label, count) for category, value in needles if (count := text.count(value))]


def _tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("git returned an unsafe publishable path")
        candidate = root / relative
        if not candidate.exists():
            continue
        current = root
        for part in relative.parts:
            current /= part
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or (
                getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
            ):
                raise ValueError("publishable path traverses a link or reparse point")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("publishable path is not an owned regular file")
        paths.append(resolved)
    return paths


def _archive_kind(name: str) -> str | None:
    lowered = name.casefold()
    if lowered.endswith((".whl", ".zip")):
        return "zip"
    if lowered.endswith((".tar.gz", ".tgz")):
        return "tar"
    return None


def _enforce_archive_preflight(kind: str | None, payload: bytes, budget: _ArchiveBudget) -> None:
    remaining_members = max(0, MAX_ARCHIVE_MEMBERS - budget.members)
    remaining_total = max(0, MAX_ARCHIVE_TOTAL_BYTES - budget.total_bytes)
    raw_stream = io.BytesIO(payload)
    if kind == "zip":
        issues = _ARCHIVE_PREFLIGHT.preflight_zip(
            raw_stream,
            max_members=remaining_members,
            max_member_bytes=MAX_ARCHIVE_MEMBER_BYTES,
            max_total_bytes=remaining_total,
            max_metadata_bytes=MAX_ARCHIVE_METADATA_BYTES,
        )
    elif kind == "tar":
        issues = _ARCHIVE_PREFLIGHT.preflight_tar_gzip(
            raw_stream,
            max_members=remaining_members,
            max_member_bytes=MAX_ARCHIVE_MEMBER_BYTES,
            max_total_bytes=remaining_total,
            max_metadata_bytes=MAX_ARCHIVE_METADATA_BYTES,
        )
    else:
        issues = []
    if not issues:
        return
    messages = {
        "archive_metadata_extension": "archive uses unsupported extended metadata",
        "archive_metadata_limit": "archive exceeds private-scan metadata limit",
        "expanded_size_limit": "archive exceeds private-scan expansion limit",
        "member_count_limit": "archive exceeds private-scan member limit",
        "member_size_limit": "archive member exceeds private-scan size limit",
    }
    raise ValueError(messages.get(issues[0][0], "archive metadata preflight failed"))


def _scan_zip_payload(
    *,
    label: str,
    payload: bytes,
    needles: list[Needle],
    depth: int,
    budget: _ArchiveBudget,
) -> list[Collision]:
    collisions: list[Collision] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        for info in members:
            budget.consume(0 if info.is_dir() else int(info.file_size))
        for info in members:
            if info.is_dir():
                continue
            with archive.open(info) as stream:
                member_payload = stream.read(MAX_ARCHIVE_MEMBER_BYTES + 1)
            if len(member_payload) != info.file_size:
                raise ValueError("archive member size changed during private scan")
            member_label = f"{label}:{info.filename}"
            collisions.extend(_scan_blob(member_label, member_payload, needles))
            if _archive_kind(info.filename):
                collisions.extend(
                    _scan_archive_payload(
                        label=member_label,
                        archive_name=info.filename,
                        payload=member_payload,
                        needles=needles,
                        depth=depth + 1,
                        budget=budget,
                    )
                )
    return collisions


def _scan_tar_payload(
    *,
    label: str,
    payload: bytes,
    needles: list[Needle],
    depth: int,
    budget: _ArchiveBudget,
) -> list[Collision]:
    collisions: list[Collision] = []
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members: list[tarfile.TarInfo] = []
        for member in archive:
            budget.consume(int(member.size) if member.isfile() else 0)
            members.append(member)
        for member in members:
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            if stream is None:  # pragma: no cover - tarfile contract guard
                continue
            member_payload = stream.read(MAX_ARCHIVE_MEMBER_BYTES + 1)
            if len(member_payload) != member.size:
                raise ValueError("archive member size changed during private scan")
            member_label = f"{label}:{member.name}"
            collisions.extend(_scan_blob(member_label, member_payload, needles))
            if _archive_kind(member.name):
                collisions.extend(
                    _scan_archive_payload(
                        label=member_label,
                        archive_name=member.name,
                        payload=member_payload,
                        needles=needles,
                        depth=depth + 1,
                        budget=budget,
                    )
                )
    return collisions


def _scan_archive_payload(
    *,
    label: str,
    archive_name: str,
    payload: bytes,
    needles: list[Needle],
    depth: int,
    budget: _ArchiveBudget,
) -> list[Collision]:
    if depth > MAX_ARCHIVE_DEPTH:
        raise ValueError("archive exceeds private-scan nesting limit")

    kind = _archive_kind(archive_name)
    _enforce_archive_preflight(kind, payload, budget)
    if kind == "zip":
        return _scan_zip_payload(
            label=label,
            payload=payload,
            needles=needles,
            depth=depth,
            budget=budget,
        )
    if kind == "tar":
        return _scan_tar_payload(
            label=label,
            payload=payload,
            needles=needles,
            depth=depth,
            budget=budget,
        )
    return []


def _scan_archive(path: Path, needles: list[Needle], *, label: str | None = None) -> list[Collision]:
    collisions: list[Collision] = []
    kind = _archive_kind(path.name)
    if kind:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
        ):
            raise ValueError("outer archive is a link or reparse point")
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("outer archive is not a regular file")
        if metadata.st_size > MAX_OUTER_ARCHIVE_BYTES:
            raise ValueError("outer archive exceeds private-scan size limit")
        with path.open("rb") as stream:
            payload = stream.read(MAX_OUTER_ARCHIVE_BYTES + 1)
        if len(payload) != metadata.st_size:
            raise ValueError("outer archive size changed during private scan")
        collisions.extend(
            _scan_archive_payload(
                label=label or path.name,
                archive_name=path.name,
                payload=payload,
                needles=needles,
                depth=0,
                budget=_ArchiveBudget(),
            )
        )
    return collisions


def scan_repository(root: Path, profile: dict[str, Any], dist_dir: Path | None = None) -> list[Collision]:
    root = root.resolve()
    needles = collect_private_values(profile)
    collisions: list[Collision] = []
    for path in _tracked_files(root):
        label = f"tree:{path.relative_to(root).as_posix()}"
        if _archive_kind(path.name):
            collisions.extend(_scan_archive(path, needles, label=label))
            continue
        metadata = path.stat()
        if metadata.st_size > MAX_TREE_FILE_BYTES:
            raise ValueError("publishable file exceeds private-scan size limit")
        with path.open("rb") as stream:
            payload = stream.read(MAX_TREE_FILE_BYTES + 1)
        if len(payload) != metadata.st_size:
            raise ValueError("publishable file size changed during private scan")
        collisions.extend(_scan_blob(label, payload, needles))

    if dist_dir is not None and dist_dir.is_dir():
        for archive in sorted(dist_dir.iterdir()):
            if _archive_kind(archive.name):
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
