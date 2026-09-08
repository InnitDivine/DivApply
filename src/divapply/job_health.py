"""Explain blocked application packets and repair a bounded selection of jobs."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import TypedDict
from urllib.parse import parse_qs, urlparse

from divapply.database import get_connection
from divapply.scoring.requirements import SCORING_VERSION


class RepairReport(TypedDict):
    selected: int
    repaired: int
    errors: int
    jobs: list[dict]


def _needs_audit(job: dict) -> bool:
    return (
        job.get("fit_score") is None or job.get("scoring_version") != SCORING_VERSION
        or bool(job.get("detail_error") or job.get("score_error"))
    )


def _pending_packet(job: dict, min_score: int, *, refresh: bool, retry_failed: bool) -> bool:
    """Select real work, not already-ready or policy-blocked packets on every run."""
    if job.get("availability_state") == "closed":
        return False
    if refresh:
        return True
    if _needs_audit(job):
        if not retry_failed and (job.get("score_attempts") or 0) >= 5:
            return False
        retry_at = job.get("score_retry_at")
        if retry_at and not retry_failed:
            try:
                when = datetime.fromisoformat(str(retry_at))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                if when > datetime.now(timezone.utc):
                    return False
            except ValueError:
                pass
        return True
    if (job.get("fit_score") or 0) < min_score or job.get("eligibility_status") == "unmet":
        return False
    if job.get("source_verification") != "official" or job.get("application_mode") != "active":
        return False
    if not job.get("tailored_resume_path") and (job.get("tailor_attempts") or 0) >= 5 and not retry_failed:
        return False  # A cover cannot be generated until its resume succeeds.
    for column, attempts in (("tailored_resume_path", "tailor_attempts"), ("cover_letter_path", "cover_attempts")):
        raw = job.get(column)
        if raw and (not Path(raw).is_file() or Path(raw).suffix.casefold() != ".pdf"):
            return True
        if not raw and (retry_failed or (job.get(attempts) or 0) < 5):
            return True
    return False


def document_issue(job: dict, min_score: int = 7) -> str:
    if job.get("availability_state") == "closed" or job.get("archived_at"):
        return "Closed or archived"
    if job.get("detail_error"):
        return "Job page needs a successful refresh"
    if job.get("score_error"):
        return "Scoring failed; retry needed"
    if _needs_audit(job):
        return "Needs new qualification audit"
    if job.get("eligibility_status") == "unmet":
        return "Does not meet minimum qualifications"
    if (job.get("fit_score") or 0) < min_score:
        return f"Below document threshold ({min_score})"
    if job.get("source_verification") != "official":
        return "Verify the direct employer source"
    if job.get("application_mode") != "active":
        return "Market or schedule needs manual review"
    resume = job.get("tailored_resume_path")
    cover = job.get("cover_letter_path")
    if not resume:
        if (job.get("tailor_attempts") or 0) >= 5:
            return "Resume retry limit reached"
        return "Resume failed; retry needed" if job.get("tailor_error") else "Resume waiting to generate"
    if not Path(resume).is_file():
        return "Saved resume file is missing"
    if not cover:
        if (job.get("cover_attempts") or 0) >= 5:
            return "Cover letter retry limit reached"
        return "Cover failed; retry needed" if job.get("cover_error") else "Cover letter waiting to generate"
    if not Path(cover).is_file():
        return "Saved cover letter file is missing"
    if any(Path(raw).suffix.casefold() != ".pdf" for raw in (resume, cover)):
        return "PDF conversion needed"
    return "Packet ready"


def audit_jobs(*, conn=None, min_score: int = 7) -> dict:
    conn = conn or get_connection()
    jobs = [dict(row) for row in conn.execute(
        "SELECT * FROM jobs WHERE archived_at IS NULL ORDER BY fit_score DESC, title"
    )]
    rows = [{"url": job["url"], "title": job["title"], "company": job.get("company"),
             "score": job.get("fit_score"), "eligibility": job.get("eligibility_status") or "not audited",
             "documents": document_issue(job, min_score),
             "error": job.get("detail_error") or job.get("score_error") or job.get("tailor_error") or job.get("cover_error") or job.get("requirements_error") or ""}
            for job in jobs]
    return {"active": len(rows), "counts": dict(Counter(row["documents"] for row in rows)), "jobs": rows}


def refresh_job(job: dict, conn) -> dict:
    """Read employer/ATS evidence, never grade a cached aggregator description."""
    from divapply.manual_url import extract_manual_job_metadata, is_aggregator_url
    from divapply.security import sanitize_external_url

    source_url = job["url"]
    if is_aggregator_url(source_url):
        direct = sanitize_external_url(job.get("detail_source_url") or job.get("application_url"))
        if not direct or is_aggregator_url(direct):
            # State listings often publish their exact JC number even when
            # the board omits its outbound Apply URL. Resolve that identifier,
            # not a guessed title/company search result.
            text = "\n".join(str(job.get(key) or "") for key in ("title", "full_description", "description"))
            controls = set(re.findall(r"\bJC[- ](\d{5,8})\b", text, re.I))
            state_employer = re.search(r"\b(california|ca)\b.*\b(department|governor|state)\b", str(job.get("company") or ""), re.I)
            if state_employer and len(controls) == 1:
                direct = "https://www.calcareers.ca.gov/CalHrPublic/Jobs/JobPosting.aspx?JobControlId=" + controls.pop()
        if not direct or is_aggregator_url(direct):
            # Follow only links actually present on the board page, never a
            # company-name search result that might be a different vacancy.
            listing = extract_manual_job_metadata(source_url)
            direct = sanitize_external_url(str(listing.get("application_url") or ""))
        if not direct or is_aggregator_url(direct):
            raise ValueError("Direct employer posting not found. Add the employer's job URL; no score was assigned from the job board.")
        source_url = direct
    metadata = extract_manual_job_metadata(source_url, require_full=True)
    final_url = str(metadata.get("final_url") or source_url)
    if is_aggregator_url(final_url):
        raise ValueError("The employer link returned to a job board; a direct posting is needed before scoring.")
    now = datetime.now(timezone.utc).isoformat()
    if metadata.get("inactive"):
        conn.execute(
            "UPDATE jobs SET availability_state='closed', availability_checked_at=?, "
            "detail_error='Posting is no longer available', fit_score=NULL, qualification_score=NULL, "
            "scoring_version=NULL WHERE url=? AND archived_at IS NULL",
            (now, job["url"]),
        )
        conn.commit()
        return {**job, "availability_state": "closed"}
    description = str(metadata.get("description") or "")
    if not metadata.get("description_complete") or len(description.strip()) < 200:
        raise ValueError("The live page did not return a complete job description")
    if is_aggregator_url(job["url"]):
        _check_posting_identity(job, metadata, final_url)
    values = {
        "full_description": description, "application_url": metadata.get("application_url") or job.get("application_url"),
        "detail_scraped_at": now, "detail_error": None, "detail_source_url": final_url,
        "availability_state": "open", "availability_checked_at": now,
        "fit_score": None, "qualification_score": None, "scoring_version": None,
        "employment_type": metadata.get("employment_type") or job.get("employment_type"),
        **{key: metadata.get(key) for key in (
            "requirements_description", "requirements_sources", "requirements_error", "requirements_checked_at",
        )},
    }
    conn.execute(
        "UPDATE jobs SET " + ", ".join(key + "=?" for key in values) + " WHERE url=? AND archived_at IS NULL",
        (*values.values(), job["url"]),
    )
    conn.commit()
    return {**job, **values}


def _check_posting_identity(job: dict, metadata: dict, url: str) -> None:
    """Reject a board's generic careers link or mismatched job before grading."""
    def words(value):
        return set(re.findall(r"[a-z0-9]+", str(value or "").casefold())) - {"job", "jobs", "careers"}

    title = re.sub(r"\bJC[- ]\d{5,8}\b", "", str(job.get("title") or ""), flags=re.I).strip()
    expected = words(title)
    actual = words(metadata.get("title"))
    normalized_title = " ".join(re.findall(r"[a-z0-9]+", title.casefold()))
    normalized_body = " ".join(re.findall(r"[a-z0-9]+", str(metadata.get("description") or "").casefold()))
    if not expected or (len(expected & actual) / len(expected) < 0.6 and normalized_title not in normalized_body):
        raise ValueError("The employer link does not match the saved job title; verify the direct posting.")
    # A specific state job-control number is stronger than a generic Analyst
    # title. Never accept a different requisition sharing the same title.
    job_control = re.search(r"\bJC[- ](\d{5,8})\b", str(job.get("title") or ""), re.I)
    if job_control:
        query = {key.casefold(): value for key, value in parse_qs(urlparse(url).query).items()}
        if query.get("jobcontrolid") != [job_control.group(1)]:
            raise ValueError("The employer posting has a different job-control number.")
    expected_company = words(job.get("company")) - {"inc", "llc", "ca", "california", "company", "of", "the", "and", "department", "city", "county"}
    actual_company = words(metadata.get("company"))
    page_words = actual_company | words(metadata.get("description"))
    if expected_company and len(expected_company & page_words) / len(expected_company) < 0.5:
        raise ValueError("The employer name could not be matched to the direct posting.")


def repair_jobs(
    *, limit: int = 3, min_score: int = 7, urls: list[str] | None = None,
    refresh: bool = True, rescore: bool = True, prepare: bool = True,
    retry_failed: bool = False, dry_run: bool = False,
    only_pending: bool = False, validation_mode: str = "normal",
) -> RepairReport:
    """Run one complete refresh/grade/packet cycle per selected job, never apply."""
    from divapply.scoring.scorer import run_scoring
    from divapply.scoring.tailor import run_tailoring
    from divapply.scoring.cover_letter import run_cover_letters
    from divapply.scoring.pdf import batch_convert

    if limit < 0:
        raise ValueError("limit must be zero (all) or positive")
    conn = get_connection()
    query = "SELECT * FROM jobs WHERE archived_at IS NULL AND applied_at IS NULL"
    parameters: list = []
    if urls:
        query += " AND url IN (" + ",".join("?" for _ in urls) + ")"
        parameters.extend(urls)
    query += " ORDER BY CASE WHEN source_verification='official' THEN 0 ELSE 1 END, fit_score DESC, title"
    jobs = [dict(row) for row in conn.execute(query, parameters)]
    if only_pending:
        jobs = [job for job in jobs if _pending_packet(job, min_score, refresh=refresh, retry_failed=retry_failed)]
    if limit:
        jobs = jobs[:limit]
    result: RepairReport = {"selected": len(jobs), "repaired": 0, "errors": 0, "jobs": []}
    for job in jobs:
        item = {"title": job["title"], "url": job["url"], "before": document_issue(job, min_score)}
        if dry_run:
            result["jobs"].append(item)
            continue
        refreshed = False
        should_score = rescore or (only_pending and (_needs_audit(job) or refresh))
        should_refresh = refresh or (only_pending and should_score)
        try:
            if should_refresh:
                job = refresh_job(job, conn)
                refreshed = True
            if job.get("availability_state") != "closed":
                if should_score:
                    scored = run_scoring(target_url=job["url"], rescore=True, refresh=not refreshed)
                    if scored.get("errors") or not scored.get("scored"):
                        raise RuntimeError("Scoring did not complete; see the saved error and job description")
                for column, attempts, error in (
                    ("tailored_resume_path", "tailor_attempts", "tailor_error"),
                    ("cover_letter_path", "cover_attempts", "cover_error"),
                ):
                    raw = job.get(column)
                    if prepare and raw and not Path(raw).is_file():
                        conn.execute(f"UPDATE jobs SET {column}=NULL, {attempts}=0 WHERE url=? AND archived_at IS NULL", (job["url"],))
                    elif prepare and retry_failed and not raw:
                        conn.execute(f"UPDATE jobs SET {attempts}=0, {error}=NULL WHERE url=? AND archived_at IS NULL", (job["url"],))
                conn.commit()
                current = dict(conn.execute("SELECT * FROM jobs WHERE url=?", (job["url"],)).fetchone())
                eligible = (
                    current.get("scoring_version") == SCORING_VERSION
                    and current.get("eligibility_status") != "unmet"
                    and (current.get("fit_score") or 0) >= min_score
                    and current.get("source_verification") == "official"
                    and current.get("application_mode") == "active"
                )
                if prepare and eligible:
                    tailored = run_tailoring(target_url=job["url"], min_score=min_score, validation_mode=validation_mode)
                    covered = run_cover_letters(target_url=job["url"], min_score=min_score, validation_mode=validation_mode)
                    if tailored.get("errors") or tailored.get("failed") or covered.get("errors"):
                        raise RuntimeError("Document generation needs review; see saved resume or cover error")
                    batch_convert(limit=2, target_url=job["url"])
                    completed = dict(conn.execute("SELECT * FROM jobs WHERE url=?", (job["url"],)).fetchone())
                    issue = document_issue(completed, min_score)
                    if issue != "Packet ready":
                        raise RuntimeError(issue)
                result["repaired"] += 1
        except Exception as exc:
            from divapply.privacy import redact_error_snippet
            item["error"] = redact_error_snippet(str(exc), max_length=400)
            if should_refresh and not refreshed:
                conn.execute(
                    "UPDATE jobs SET eligibility_status='uncertain', detail_error=?, "
                    "fit_score=NULL, qualification_score=NULL, scoring_version=NULL WHERE url=? AND archived_at IS NULL",
                    (item["error"], job["url"]),
                )
                conn.commit()
            result["errors"] += 1
        current = dict(conn.execute("SELECT * FROM jobs WHERE url=?", (job["url"],)).fetchone())
        item.update({"score": current.get("fit_score"), "eligibility": current.get("eligibility_status"),
                     "after": document_issue(current, min_score)})
        result["jobs"].append(item)
    return result
