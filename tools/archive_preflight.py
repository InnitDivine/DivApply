"""Bounded raw archive metadata checks that run before stdlib archive parsers."""

from __future__ import annotations

import gzip
import io
import struct
import tarfile
from typing import BinaryIO


PreflightIssue = tuple[str, int]

_ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP_CENTRAL_SIGNATURE = b"PK\x01\x02"
_ZIP_EOCD = struct.Struct("<4s4H2LH")
_ZIP_CENTRAL = struct.Struct("<4s4B4HL2L5H2L")
_ZIP_MAX_COMMENT = (1 << 16) - 1
_ZIP_SENTINEL_16 = (1 << 16) - 1
_ZIP_SENTINEL_32 = (1 << 32) - 1
_TAR_BLOCK = 512
_READ_CHUNK = 64 * 1024
_TAR_EXTENSION_TYPES = {
    tarfile.GNUTYPE_LONGLINK,
    tarfile.GNUTYPE_LONGNAME,
    tarfile.GNUTYPE_SPARSE,
    tarfile.SOLARIS_XHDTYPE,
    tarfile.XGLTYPE,
    tarfile.XHDTYPE,
}


def _add_issue(issues: list[PreflightIssue], code: str, index: int) -> None:
    item = (code, index)
    if item not in issues:
        issues.append(item)


def _read_exact(stream: BinaryIO, size: int, *, label: str) -> bytes:
    payload = stream.read(size)
    if len(payload) != size:
        raise ValueError(f"truncated {label}")
    return payload


def _discard_exact(stream: BinaryIO, size: int, *, label: str) -> None:
    remaining = size
    while remaining:
        chunk = stream.read(min(remaining, _READ_CHUNK))
        if not chunk:
            raise ValueError(f"truncated {label}")
        remaining -= len(chunk)


def _read_zip_end_record(stream: BinaryIO) -> tuple[int, int, int, int]:
    stream.seek(0, io.SEEK_END)
    archive_size = stream.tell()
    if archive_size < _ZIP_EOCD.size:
        raise ValueError("ZIP end record is missing")
    tail_size = min(archive_size, _ZIP_MAX_COMMENT + _ZIP_EOCD.size)
    stream.seek(archive_size - tail_size)
    tail = _read_exact(stream, tail_size, label="ZIP tail")
    relative_eocd = tail.rfind(_ZIP_EOCD_SIGNATURE)
    if relative_eocd < 0 or relative_eocd + _ZIP_EOCD.size > len(tail):
        raise ValueError("ZIP end record is missing")
    eocd_offset = archive_size - tail_size + relative_eocd
    (
        _signature,
        disk_number,
        directory_disk,
        entries_on_disk,
        declared_entries,
        directory_size,
        directory_offset,
        comment_size,
    ) = _ZIP_EOCD.unpack_from(tail, relative_eocd)
    if eocd_offset + _ZIP_EOCD.size + comment_size != archive_size:
        raise ValueError("ZIP end record has an invalid comment length")
    if disk_number != 0 or directory_disk != 0 or entries_on_disk != declared_entries:
        raise ValueError("multi-disk ZIP archives are unsupported")
    if (
        declared_entries == _ZIP_SENTINEL_16
        or directory_size == _ZIP_SENTINEL_32
        or directory_offset == _ZIP_SENTINEL_32
    ):
        raise ValueError("ZIP64 metadata is unsupported by the bounded scanner")
    return eocd_offset, declared_entries, directory_size, directory_offset


def _scan_zip_central_directory(
    stream: BinaryIO,
    *,
    eocd_offset: int,
    directory_size: int,
    directory_offset: int,
    declared_entries: int,
    max_members: int,
    max_member_bytes: int,
    max_total_bytes: int,
) -> list[PreflightIssue]:
    central_start = eocd_offset - directory_size
    if central_start < 0 or directory_offset > central_start:
        raise ValueError("ZIP central directory has an invalid offset")
    stream.seek(central_start)
    issues: list[PreflightIssue] = []
    actual_entries = 0
    expanded_total = 0
    while stream.tell() < eocd_offset:
        header_offset = stream.tell()
        header = _read_exact(stream, _ZIP_CENTRAL.size, label="ZIP central-directory header")
        record = _ZIP_CENTRAL.unpack(header)
        if record[0] != _ZIP_CENTRAL_SIGNATURE:
            raise ValueError("ZIP central-directory signature is invalid")
        actual_entries += 1
        if actual_entries > max_members:
            _add_issue(issues, "member_count_limit", actual_entries)
            break

        uncompressed_size = int(record[11])
        if uncompressed_size == _ZIP_SENTINEL_32:
            _add_issue(issues, "member_size_limit", actual_entries)
        else:
            if uncompressed_size > max_member_bytes:
                _add_issue(issues, "member_size_limit", actual_entries)
            expanded_total += uncompressed_size
            if expanded_total > max_total_bytes:
                _add_issue(issues, "expanded_size_limit", actual_entries)

        variable_size = int(record[12]) + int(record[13]) + int(record[14])
        next_offset = header_offset + _ZIP_CENTRAL.size + variable_size
        if next_offset > eocd_offset:
            raise ValueError("ZIP central-directory entry exceeds declared bounds")
        stream.seek(next_offset)

    if stream.tell() == eocd_offset and actual_entries != declared_entries:
        raise ValueError("ZIP central-directory count does not match end record")
    return issues


def preflight_zip(
    stream: BinaryIO,
    *,
    max_members: int,
    max_member_bytes: int,
    max_total_bytes: int,
    max_metadata_bytes: int,
) -> list[PreflightIssue]:
    """Inspect EOCD and fixed central-directory records without constructing ZipFile."""
    eocd_offset, declared_entries, directory_size, directory_offset = _read_zip_end_record(stream)

    issues: list[PreflightIssue] = []
    if declared_entries > max_members:
        _add_issue(issues, "member_count_limit", max_members + 1)
    if directory_size > max_metadata_bytes:
        _add_issue(issues, "archive_metadata_limit", 1)
        return issues

    for code, index in _scan_zip_central_directory(
        stream,
        eocd_offset=eocd_offset,
        directory_size=directory_size,
        directory_offset=directory_offset,
        declared_entries=declared_entries,
        max_members=max_members,
        max_member_bytes=max_member_bytes,
        max_total_bytes=max_total_bytes,
    ):
        _add_issue(issues, code, index)
    return sorted(issues)


def _preflight_gzip_header(stream: BinaryIO, max_metadata_bytes: int) -> list[PreflightIssue]:
    start = stream.tell()
    try:
        header = _read_exact(stream, 10, label="gzip header")
        if header[:2] != b"\x1f\x8b" or header[2] != 8 or header[3] & 0xE0:
            raise ValueError("invalid gzip header")
        flags = header[3]
        consumed = len(header)
        if flags & 4:
            extra_length = int.from_bytes(_read_exact(stream, 2, label="gzip extra length"), "little")
            consumed += 2 + extra_length
            if consumed > max_metadata_bytes:
                return [("archive_metadata_limit", 1)]
            _discard_exact(stream, extra_length, label="gzip extra data")
        for flag in (8, 16):
            if not flags & flag:
                continue
            while True:
                chunk = _read_exact(stream, 1, label="gzip text header")
                consumed += 1
                if consumed > max_metadata_bytes:
                    return [("archive_metadata_limit", 1)]
                if chunk == b"\x00":
                    break
        if flags & 2:
            consumed += 2
            if consumed > max_metadata_bytes:
                return [("archive_metadata_limit", 1)]
            _read_exact(stream, 2, label="gzip header checksum")
        return []
    finally:
        stream.seek(start)


def _finish_tar_stream(
    archive: BinaryIO,
    *,
    metadata_total: int,
    index: int,
    max_metadata_bytes: int,
    issues: list[PreflightIssue],
) -> list[PreflightIssue]:
    second_end = _read_exact(archive, _TAR_BLOCK, label="TAR second end marker")
    metadata_total += _TAR_BLOCK
    if second_end != b"\x00" * _TAR_BLOCK:
        raise ValueError("TAR archive has an invalid end marker")
    while chunk := archive.read(_READ_CHUNK):
        metadata_total += len(chunk)
        if metadata_total > max_metadata_bytes:
            return [("archive_metadata_limit", max(index, 1))]
        if chunk.strip(b"\x00"):
            raise ValueError("TAR archive has nonzero trailing data")
    return sorted(issues)


def _inspect_tar_member(
    header: bytes,
    *,
    index: int,
    expanded_total: int,
    metadata_total: int,
    max_member_bytes: int,
    max_total_bytes: int,
    max_metadata_bytes: int,
) -> tuple[int, int, int, list[PreflightIssue]]:
    try:
        member = tarfile.TarInfo.frombuf(header, "utf-8", "surrogateescape")
    except tarfile.HeaderError as exc:
        raise ValueError("TAR header is invalid") from exc
    issues: list[PreflightIssue] = []
    size = int(member.size)
    if size < 0 or size > max_member_bytes:
        _add_issue(issues, "member_size_limit", index)
    expanded_total += max(size, 0)
    if expanded_total > max_total_bytes:
        _add_issue(issues, "expanded_size_limit", index)
    padding = (-size) % _TAR_BLOCK if size >= 0 else 0
    metadata_total += padding
    if metadata_total > max_metadata_bytes:
        _add_issue(issues, "archive_metadata_limit", index)
    if member.type in _TAR_EXTENSION_TYPES:
        _add_issue(issues, "archive_metadata_extension", index)
    return size + padding, expanded_total, metadata_total, sorted(issues)


def preflight_tar_gzip(
    stream: BinaryIO,
    *,
    max_members: int,
    max_member_bytes: int,
    max_total_bytes: int,
    max_metadata_bytes: int,
) -> list[PreflightIssue]:
    """Stream raw gzip/TAR headers and data bounds before constructing TarFile."""
    gzip_issues = _preflight_gzip_header(stream, max_metadata_bytes)
    if gzip_issues:
        return gzip_issues

    issues: list[PreflightIssue] = []
    expanded_total = 0
    metadata_total = 0
    with gzip.GzipFile(fileobj=stream, mode="rb") as archive:
        index = 0
        while True:
            header = archive.read(_TAR_BLOCK)
            if len(header) != _TAR_BLOCK:
                raise ValueError("TAR archive is missing its end markers")
            metadata_total += _TAR_BLOCK
            if metadata_total > max_metadata_bytes:
                return [("archive_metadata_limit", max(index, 1))]
            if header == b"\x00" * _TAR_BLOCK:
                return _finish_tar_stream(
                    archive,
                    metadata_total=metadata_total,
                    index=index,
                    max_metadata_bytes=max_metadata_bytes,
                    issues=issues,
                )

            index += 1
            if index > max_members:
                return [("member_count_limit", index)]
            discard_bytes, expanded_total, metadata_total, member_issues = _inspect_tar_member(
                header,
                index=index,
                expanded_total=expanded_total,
                metadata_total=metadata_total,
                max_member_bytes=max_member_bytes,
                max_total_bytes=max_total_bytes,
                max_metadata_bytes=max_metadata_bytes,
            )
            if member_issues:
                return member_issues
            _discard_exact(archive, discard_bytes, label="TAR member data")
