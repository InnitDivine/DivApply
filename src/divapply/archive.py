"""Archive-related generated artifact cleanup."""

from __future__ import annotations

import logging
from pathlib import Path

from divapply import config
from divapply.artifacts import artifact_family_key

log = logging.getLogger(__name__)


def is_safe_generated_path(path: Path, allowed_roots: list[Path]) -> bool:
    """Return True when a generated artifact path is inside an output directory."""
    try:
        candidate = path.parent.resolve() / path.name if path.is_symlink() else path.resolve()
    except OSError:
        return False
    for root in allowed_roots:
        try:
            candidate.relative_to(root.resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


def artifact_siblings(path: Path) -> set[Path]:
    """Return known generated files associated with a tailored/cover text file."""
    siblings = {path}
    siblings.add(path.with_suffix(".pdf"))
    siblings.add(path.with_suffix(".txt"))
    siblings.add(path.with_suffix(".html"))
    name = path.name
    if name.endswith("_CL.txt") or name.endswith("_CL.pdf"):
        return siblings
    if path.suffix in {".txt", ".pdf"} and not name.endswith(("_JOB.txt", "_REPORT.txt")):
        siblings.add(path.with_name(f"{path.stem}_JOB.txt"))
        siblings.add(path.with_name(f"{path.stem}_REPORT.json"))
    return siblings


def delete_job_artifacts(job: dict, *, protected_paths: set[str] | None = None) -> list[Path]:
    """Best-effort cleanup of generated resume/cover files for an archived job."""
    allowed_roots = [config.TAILORED_DIR, config.COVER_LETTER_DIR]
    deleted: list[Path] = []
    candidates: set[Path] = set()
    protected_families = {artifact_family_key(path) for path in (protected_paths or set())}
    for key in ("tailored_resume_path", "cover_letter_path"):
        raw_path = job.get(key)
        if raw_path and artifact_family_key(raw_path) not in protected_families:
            candidates.update(artifact_siblings(Path(raw_path)))

    for candidate in sorted(candidates):
        if not is_safe_generated_path(candidate, allowed_roots):
            continue
        try:
            if candidate.exists() or candidate.is_symlink():
                candidate.unlink()
                deleted.append(candidate)
        except OSError:
            log.warning("Could not delete archived job artifact: %s", candidate)
            try:
                from divapply.database import record_reliability_event

                record_reliability_event(
                    "archive_artifact_delete_failed",
                    "Could not delete archived job artifact",
                    severity="warning",
                    context={"path": str(candidate)},
                )
            except Exception:
                log.debug("Could not record archive artifact cleanup failure", exc_info=True)
    return deleted
