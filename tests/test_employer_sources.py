from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from divapply import database, job_health, manual_url
from divapply.enrichment import requirements as linked
from divapply.scoring import scorer
from divapply.scoring.requirements import qualification_assessment


EMPLOYER = "https://careers.example.test/jobs/123"
BOARD = "https://www.indeed.com/viewjob?jk=123"
DESCRIPTION = "Support Technician at Example Company. Responsibilities: provide desktop support. " * 4 + "\nMinimum Qualifications: Two years of professional IT experience required."


def metadata(url=EMPLOYER):
    return dict(title="Support Technician", company="Example Company", description=DESCRIPTION,
                final_url=url, application_url=url + "/apply", description_complete=True, inactive=False)


@pytest.fixture
def queue(tmp_path, monkeypatch):
    path = tmp_path / "jobs.db"
    conn = database.init_db(path)
    monkeypatch.setattr(job_health, "get_connection", lambda: conn)
    monkeypatch.setattr(scorer, "get_connection", lambda: conn)
    resume = tmp_path / "resume.txt"
    resume.write_text("Independent desktop support training.", encoding="utf-8")
    monkeypatch.setattr(scorer, "RESUME_PATH", resume)
    monkeypatch.setattr(scorer, "load_profile", lambda: {})
    monkeypatch.setattr(scorer, "load_search_config", lambda: {})
    yield conn
    database.close_connection(path)


def insert(conn, *, url=BOARD, application_url=EMPLOYER):
    conn.execute("INSERT INTO jobs(url,title,company,application_url,full_description,fit_score,qualification_score,tailored_resume_path) VALUES (?,?,?,?,?,?,?,?)",
                 (url, "Support Technician", "Example Company", application_url,
                  "Short board summary. " * 20, 9, 9, "user-edited-resume.pdf"))
    conn.commit()
    return dict(conn.execute("SELECT * FROM jobs WHERE url=?", (url,)).fetchone())


def test_board_discovery_uses_direct_page_without_reading_board_or_deleting_documents(queue, monkeypatch):
    job = insert(queue)
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return metadata(url)
    monkeypatch.setattr(manual_url, "extract_manual_job_metadata", fetch)
    refreshed = job_health.refresh_job(job, queue)
    assert calls == [(EMPLOYER, {"require_full": True})]
    assert refreshed["full_description"] == DESCRIPTION
    assert refreshed["detail_source_url"] == EMPLOYER
    assert refreshed["fit_score"] is None
    assert refreshed["tailored_resume_path"] == "user-edited-resume.pdf"
    assert queue.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_rescore_fetches_live_employer_before_grading_even_with_a_long_saved_description(queue, monkeypatch):
    insert(queue)
    events = []
    def fetch(url, **kwargs):
        events.append("fetch")
        return metadata(url)
    def grade(*args, **kwargs):
        events.append("score")
        job = args[1]
        assert job["full_description"] == DESCRIPTION
        assert job["detail_source_url"] == EMPLOYER
        return {"score": 4, "reasoning": "Professional experience required."}
    monkeypatch.setattr(manual_url, "extract_manual_job_metadata", fetch)
    monkeypatch.setattr(scorer, "score_job", grade)
    result = scorer.run_scoring(rescore=True)
    assert events == ["fetch", "score"]
    assert result["scored"] == 1
    assert result["errors"] == 0


@pytest.mark.parametrize("response", ["blocked", "mismatch", "unreadable", "board_redirect"])
def test_unreadable_or_wrong_employer_page_is_unscored_not_a_low_fit(queue, monkeypatch, response):
    insert(queue)
    def fetch(url, **kwargs):
        if response == "blocked":
            raise ValueError("Employer HTTP 403")
        result = metadata(url)
        if response == "mismatch":
            result.update(title="Chief Financial Officer", description="Other Finance Corp. Minimum qualifications: " * 20)
        if response == "unreadable":
            result["description_complete"] = False
        if response == "board_redirect":
            result["final_url"] = BOARD
        return result
    monkeypatch.setattr(manual_url, "extract_manual_job_metadata", fetch)
    monkeypatch.setattr(scorer, "score_job", lambda *a, **k: pytest.fail("Bad source reached AI"))
    result = scorer.run_scoring(rescore=True)
    saved = queue.execute("SELECT * FROM jobs").fetchone()
    assert result["scored"] == 0 and result["errors"] == 1
    assert saved["fit_score"] is None and saved["qualification_score"] is None
    assert saved["detail_error"] and saved["scoring_version"] is None
    assert saved["tailored_resume_path"] == "user-edited-resume.pdf"


def test_missing_direct_link_does_not_grade_aggregator_copy(queue, monkeypatch):
    insert(queue, application_url=BOARD)
    monkeypatch.setattr(manual_url, "extract_manual_job_metadata", lambda *a, **k: metadata(BOARD))
    monkeypatch.setattr(scorer, "score_job", lambda *a, **k: pytest.fail("Scored a board copy"))
    result = scorer.run_scoring(rescore=True)
    assert result["scored"] == 0
    assert "Direct employer posting not found" in queue.execute("SELECT detail_error FROM jobs").fetchone()[0]


def test_closed_employer_page_is_not_scored_or_deleted(queue, monkeypatch):
    insert(queue)
    monkeypatch.setattr(manual_url, "extract_manual_job_metadata", lambda *a, **k: metadata() | {"inactive": True})
    monkeypatch.setattr(scorer, "score_job", lambda *a, **k: pytest.fail("Scored closed posting"))
    result = scorer.run_scoring(rescore=True)
    assert result["scored"] == 0
    saved = queue.execute("SELECT * FROM jobs").fetchone()
    assert saved["availability_state"] == "closed" and saved["fit_score"] is None
    assert saved["tailored_resume_path"] == "user-edited-resume.pdf"


def test_known_state_requisition_resolves_without_guessing_a_title_search(queue, monkeypatch):
    job = insert(queue, application_url=None)
    job.update(title="INFORMATION TECHNOLOGY ASSOCIATE JC-530524", company="California Department of Public Health")
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return metadata(url) | {"title": "Information Technology Associate", "company": "California Department of Public Health"}
    monkeypatch.setattr(manual_url, "extract_manual_job_metadata", fetch)
    result = job_health.refresh_job(job, queue)
    assert len(calls) == 1
    assert calls[0].endswith("JobControlId=530524")
    assert result["detail_source_url"] == calls[0]


def test_all_bulletin_text_survives_past_old_six_thousand_character_cutoff():
    requirement = "Four years of paid professional IT experience required."
    html = "<div id='JobBulletin'><h1>Analyst I</h1><h2>Duties</h2>" + "Provide service. " * 1300 + "<h2>Minimum Qualifications</h2>" + requirement + "</div>"
    result = manual_url.parse_job_page(html, "https://www.jobapscloud.com/Placer/sup/bulpreview.asp?R1=2026&R2=1&R3=1")
    assert len(result["description"]) > 20000
    assert requirement in result["description"]
    assert result["description_complete"] is True


def test_schema_teaser_cannot_hide_full_visible_requirements():
    schema = json.dumps({"@type": "JobPosting", "title": "Support Technician", "description": "Help users with IT."})
    html = f'<script type="application/ld+json">{schema}</script><main><h1>Support Technician</h1>{DESCRIPTION}</main>'
    result = manual_url.parse_job_page(html, EMPLOYER)
    assert "Two years of professional IT experience required." in result["description"]
    assert result["description_complete"] is True


def test_empty_calcareers_template_is_not_a_job_description():
    html = "<main>Exam notifications and application instructions. " * 20 + "</main>"
    result = manual_url.parse_job_page(html, "https://calcareers.ca.gov/CalHrPublic/Jobs/JobPosting.aspx?JobControlId=1")
    assert result["description_complete"] is False


def test_javascript_shell_renders_before_scoring(monkeypatch):
    monkeypatch.setattr(manual_url, "_fetch_job_page", lambda *a, **k: httpx.Response(
        200, text="<div id='app'>Enable JavaScript to view this posting.</div>", request=httpx.Request("GET", EMPLOYER)))
    calls = []
    def render(url):
        calls.append(url)
        return metadata(url)
    monkeypatch.setattr(manual_url, "_render_job_page", render)
    result = manual_url.extract_manual_job_metadata(EMPLOYER, require_full=True)
    assert calls == [EMPLOYER]
    assert result["description"] == DESCRIPTION


def test_separate_verbatim_quotes_are_verified_without_accepting_paraphrases():
    posting = "A high school diploma is required.\nOther duties.\nTwo years of office experience required."
    evidence = "High school diploma awarded.\nOther information.\nThree years of office experience."
    row = {"requirement": "Diploma and two years", "kind": "required", "status": "met",
           "quote": ["A high school diploma is required.", "Two years of office experience required."],
           "evidence": ["High school diploma awarded.", "Three years of office experience."], "reason": "Both supported."}
    result = qualification_assessment([row], posting=posting, evidence=evidence, raw_score=9)
    assert result["score"] == 9
    row["evidence"][1] = "Four years of office experience."
    result = qualification_assessment([row], posting=posting, evidence=evidence, raw_score=9)
    assert result["score"] == 6


def test_background_check_is_a_readiness_step_not_missing_qualification():
    required = "A high school diploma is required."
    background = "A background investigation is required prior to being hired."
    rows = [{"requirement": required, "quote": required, "kind": "required", "status": "met", "evidence": "High school diploma awarded."},
            {"requirement": background, "quote": background, "kind": "required", "status": "uncertain"}]
    result = qualification_assessment(rows, posting=required + " " + background, evidence="High school diploma awarded.", raw_score=9)
    assert result["score"] == 9
    assert json.loads(result["requirements_assessment"])[1]["kind"] == "readiness"


def test_duty_statement_is_read_even_without_a_minimum_qualification_heading(monkeypatch):
    def fetch(*a, **k):
        return httpx.Response(200, text="<main>Analyst I Duty Statement: Research records and assist the public. " * 5 + "</main>",
                              request=httpx.Request("GET", "https://calcareers.ca.gov/FileDownload.aspx?id=1"))
    monkeypatch.setattr(linked, "_fetch", fetch)
    result = linked.linked_qualification_evidence('<a href="/FileDownload.aspx?id=1">Duty Statement</a>', "https://calcareers.ca.gov/job")
    assert "Research records" in result["requirements_description"]
    assert json.loads(result["requirements_sources"])[0]["kind"] == "duties"


def test_a_duty_statement_naming_the_class_cannot_hide_a_failed_qualification_spec(monkeypatch):
    def fetch(_client, url):
        if "SpecCrossReference" in url:
            raise ValueError("Unavailable specification")
        return httpx.Response(200, text="<main>Information Technology Associate Duty Statement. Support users with desktop systems. " * 5 + "</main>",
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(linked, "_fetch", fetch)
    html = '<a href="/FileDownload.aspx?id=1">Duty Statement</a><a href="https://hrnet.calhr.ca.gov/SpecCrossReference.aspx?ClassID=1401">Information Technology Associate</a>'
    result = linked.linked_qualification_evidence(html, "https://calcareers.ca.gov/job")
    assert result["requirements_description"]
    assert "Information Technology Associate" in result["requirements_error"]


def test_previously_refreshed_input_is_not_downloaded_twice_in_packet_workflow(queue, monkeypatch):
    insert(queue, url=EMPLOYER)
    queue.execute("UPDATE jobs SET detail_source_url=?,detail_scraped_at=?", (EMPLOYER, datetime.now(timezone.utc).isoformat()))
    queue.commit()
    monkeypatch.setattr(job_health, "refresh_job", lambda *a, **k: pytest.fail("Duplicate download"))
    monkeypatch.setattr(scorer, "score_job", lambda *a, **k: {"score": 5, "reasoning": "Fixture."})
    assert scorer.run_scoring(target_url=EMPLOYER, refresh=False)["scored"] == 1


def test_calhr_series_keeps_shared_and_selected_minimums_not_other_levels():
    html = """<main><table><tr><td>1401</td><td>IT Associate</td></tr><tr><td>1405</td><td>IT Manager</td></tr></table>
    <h2>Minimum Qualifications</h2><h3>All classifications</h3><p>Education must include IT coursework.</p>
    <h3>IT Associate</h3><p>60 semester units including 15 IT units.</p>
    <h3>IT Manager</h3><p>Six years of management required.</p>
    <h2>Knowledge and Abilities</h2><p>Common troubleshooting skills.</p></main>"""
    response = httpx.Response(200, text=html)
    text = linked._document_text(response, classification="IT ASSOCIATE")
    assert "Education must include IT coursework." in text
    assert "60 semester units including 15 IT units." in text
    assert "Six years of management required." not in text
    assert "Common troubleshooting skills." in text


def test_calhr_fallback_requires_exact_code_and_class_name(monkeypatch):
    url = "https://hrnet.calhr.ca.gov/CalHRNet/SpecCrossReference.aspx?ClassID=1401"
    html = "<table><tr><td>1401</td><td>Information Technology Associate</td></tr></table><h2>Minimum Qualifications</h2>"
    seen = []
    def render(url, **kwargs):
        seen.append(url)
        return html, url
    monkeypatch.setattr(manual_url, "render_public_page", render)
    response = linked._calhr_portal_fallback(url, "INFORMATION TECHNOLOGY ASSOCIATE")
    assert str(response.url).endswith("/1401")
    with pytest.raises(ValueError, match="did not match"):
        linked._calhr_portal_fallback(url, "Information Technology Manager")
    assert len(seen) == 2


def test_calhr_h2_classes_keep_only_the_selected_minimums_and_its_alternatives():
    html = """<main><table><tr><td>Program Technician</td></tr><tr><td>Program Technician II</td></tr>
    <tr><td>Program Technician III</td></tr></table>
    <h2>Minimum Qualifications</h2>
    <h2>Program Technician</h2><h3>Either I</h3><p>General experience in a lower class.</p>
    <h3>Or II</h3><p>Lower-class school substitution.</p>
    <h2>Program Technician II</h2><h3>Either I</h3><p>18 months in California state service.</p>
    <h3>Or II</h3><p>Two years of equivalent governmental or private experience.</p>
    <h2>Program Technician III</h2><h3>Either I</h3><p>One year in the higher class.</p>
    <h3>Or II</h3><p>Three years including higher-level responsibility.</p>
    <h2>Knowledge and Abilities</h2><h2>All Levels:</h2><p>Learn relevant laws and procedures.</p></main>"""
    text = linked._document_text(httpx.Response(200, text=html), classification="PROGRAM TECHNICIAN II")
    assert "18 months in California state service." in text
    assert "Two years of equivalent governmental or private experience." in text
    assert "Lower-class school substitution." not in text
    assert "higher-level responsibility." not in text
    assert "General experience in a lower class." not in text
    assert "Learn relevant laws and procedures." in text


def test_calhr_http_failure_uses_verified_public_portal(monkeypatch):
    spec_url = "https://hrnet.calhr.ca.gov/CalHRNet/SpecCrossReference.aspx?ClassID=1401"
    def fail(*args):
        response = httpx.Response(403, request=httpx.Request("GET", spec_url))
        response.raise_for_status()
    monkeypatch.setattr(linked, "_fetch", fail)
    calls = []
    def fallback(url, label):
        calls.append((url, label))
        return httpx.Response(200, text="<main>Information Technology Associate Minimum Qualifications: Two years of IT experience or specified college coursework.</main>",
                              request=httpx.Request("GET", "https://eservices.calhr.ca.gov/Public/ClassSpec/1401"))
    monkeypatch.setattr(linked, "_calhr_portal_fallback", fallback)
    result = linked.linked_qualification_evidence(f'<a href="{spec_url}">Information Technology Associate</a>', "https://calcareers.ca.gov/job")
    assert calls == [(spec_url, "Information Technology Associate")]
    assert not result["requirements_error"]
    assert json.loads(result["requirements_sources"])[0]["status"] == "read"


def test_dashboard_keeps_legacy_jobs_but_does_not_present_old_scores_as_current(queue):
    from divapply.dashboard_data import fetch_dashboard_snapshot
    insert(queue)
    queue.execute("UPDATE jobs SET scoring_version='requirements-v2'")
    queue.commit()
    snapshot = fetch_dashboard_snapshot(queue)
    assert snapshot.total == 1
    assert snapshot.scored == snapshot.high_fit == 0
    assert snapshot.score_dist == {}
    assert snapshot.jobs[0]["fit_score"] is None
    assert snapshot.jobs[0]["prior_fit_score"] == 9
    assert queue.execute("SELECT fit_score FROM jobs").fetchone()[0] == 9
