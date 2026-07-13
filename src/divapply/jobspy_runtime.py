"""Validate the intentionally overridden JobSpy runtime dependency contract."""

from __future__ import annotations

from importlib import metadata
import re
import sys


JOBSPY_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/d5/2b/18863fcd3c544a69d81e351381a50036a33c21b61cc1c6de2a8f25931237/"
    "python_jobspy-1.1.82-py3-none-any.whl"
    "#sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9"
)

# Every upstream python-jobspy 1.1.82 bound is preserved except Markdownify's
# vulnerable <0.14.0 cap, which DivApply intentionally replaces with >=0.14.1.
_BOUNDS: dict[str, tuple[tuple[int, ...] | None, tuple[int, ...] | None, str | None]] = {
    "python-jobspy": (None, None, "1.1.82"),
    "numpy": (None, None, "1.26.3"),
    "beautifulsoup4": ((4, 12, 2), (5, 0, 0), None),
    "markdownify": ((0, 14, 1), None, None),
    "pandas": ((2, 1, 0), (3, 0, 0), None),
    "pydantic": ((2, 3, 0), (3, 0, 0), None),
    "regex": ((2024, 4, 28), (2025, 0, 0), None),
    "requests": ((2, 31, 0), (3, 0, 0), None),
    "tls-client": ((1, 0, 1), (2, 0, 0), None),
}


def _release_tuple(value: str) -> tuple[int, ...]:
    match = re.match(r"\s*(\d+(?:\.\d+)*)", value)
    if match is None:
        raise ValueError(f"version has no numeric release: {value!r}")
    parts = tuple(int(part) for part in match.group(1).split("."))
    return parts + (0,) * max(0, 3 - len(parts))


def validate_installed_jobspy() -> list[str]:
    """Return contract violations for the installed supported JobSpy runtime."""
    issues: list[str] = []
    for distribution, (minimum, maximum, exact) in _BOUNDS.items():
        try:
            installed = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            issues.append(f"{distribution} is not installed")
            continue

        if exact is not None:
            if installed != exact:
                issues.append(f"{distribution} {installed} != required {exact}")
            continue

        try:
            release = _release_tuple(installed)
        except ValueError as exc:
            issues.append(f"{distribution}: {exc}")
            continue
        if minimum is not None and release < minimum:
            issues.append(f"{distribution} {installed} is below {'.'.join(map(str, minimum))}")
        if maximum is not None and release >= maximum:
            issues.append(f"{distribution} {installed} must be below {'.'.join(map(str, maximum))}")
    return issues


def main() -> int:
    issues = validate_installed_jobspy()
    if issues:
        for issue in issues:
            print(f"JobSpy runtime error: {issue}", file=sys.stderr)
        return 1
    print("JobSpy runtime contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
