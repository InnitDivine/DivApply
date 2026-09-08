from __future__ import annotations

import json

import httpx
import pytest

from divapply import database, job_health
from divapply.enrichment import requirements as linked
from divapply.scoring import scorer
from divapply.scoring.context import format_job_context
from divapply.scoring.requirements import SCORING_VERSION, qualification_assessment


def requirement(status="met", kind="required", quote="A high school diploma is required.",
                evidence="High school diploma awarded.", reason="Documented credential."):
    return dict(requirement=quote, status=status, kind=kind, quote=quote, evidence=evidence, reason=reason)


def assess(rows, **kwargs):
    posting = "A high school diploma is required. A CCNA is preferred."
    if any(row.get("quote") == "Five years of professional network administration required." for row in rows):
        posting += " Five years of professional network administration required."
    return qualification_assessment(rows, posting=posting,
                                    evidence="High school diploma awarded. Independent home lab projects.", raw_score=9, **kwargs)


def test_required_years_shortfall_cannot_be_hidden_by_keyword_similarity():
    result = assess([requirement(), requirement(status="unmet", quote="Five years of professional network administration required.",
                                               evidence="", reason="Projects do not establish five professional years.")])
    assert result["score"] == 4
    assert result["eligibility_status"] == "unmet"
    assert "Five years" in result["qualification_gaps"]


def test_preferred_gap_does_not_disqualify_a_qualified_candidate():
    result = assess([requirement(), requirement(status="unmet", kind="preferred", quote="A CCNA is preferred.", evidence="")])
    assert result["score"] == 9
    assert result["eligibility_status"] == "meets"


@pytest.mark.parametrize("rows", [[], [requirement(evidence="An invented high school diploma.")],
                                  [requirement(quote="A fabricated requirement is stated here.")]])
def test_missing_or_invented_evidence_never_produces_a_strong_match(rows):
    result = assess(rows)
    assert result["score"] == 6
    assert result["eligibility_status"] == "uncertain"


def test_future_degree_projection_keeps_full_score_without_claiming_present_day_eligibility():
    result = assess([requirement()], projected=True)
    assert (result["score"], result["eligibility_status"]) == (9, "projected")


def test_alternative_pathway_is_not_a_requirement_to_meet_both_options():
    posting = "A bachelor's degree OR four years of office administration experience is required."
    evidence = "Bachelor of Science in Public Health awarded."
    result = qualification_assessment([
        requirement(quote=posting, evidence=evidence, reason="The awarded degree satisfies the first allowed pathway.")
    ], posting=posting, evidence=evidence, raw_score=8)
    assert (result["score"], result["eligibility_status"]) == (8, "meets")


def test_public_health_projection_does_not_waive_a_required_different_degree_field():
    posting = "A bachelor's degree in computer science is required."
    result = qualification_assessment([
        requirement(quote=posting, status="unmet", evidence="", reason="The projected field is Public Health, not computer science.")
    ], posting=posting, evidence="Projected Bachelor of Science in Public Health.", raw_score=9, projected=True)
    assert (result["score"], result["eligibility_status"]) == (4, "unmet")


def test_missing_hours_do_not_prove_full_time_equivalent_experience():
    posting = "Two years of full-time-equivalent office experience required."
    evidence = "Office assistant, 2023-2025. Hours per week not documented."
    result = qualification_assessment([
        requirement(quote=posting, status="uncertain", evidence=evidence, reason="Cannot calculate FTE years without hours.")
    ], posting=posting, evidence=evidence, raw_score=9)
    assert (result["score"], result["eligibility_status"]) == (6, "uncertain")


def test_transferred_or_inactive_bachelors_cannot_be_projected_as_completed():
    for status in ("transferred", "inactive", "withdrawn"):
        context = scorer._build_profile_evidence_context({"education_schools": [{
            "degree": "Bachelor of Science", "degree_received": False, "status": status,
        }]}, assume_completed_bachelors=True)
        assert "SCORING-ONLY EDUCATION PROJECTION" not in context


def test_degree_projection_preserves_actual_december_completion_timing():
    context = scorer._build_profile_evidence_context({"education_schools": [{
        "school": "Example State University", "degree": "Bachelor of Science",
        "major": "Public Health", "degree_received": False, "end_year": "present",
        "expected_graduation_year": "2026", "expected_graduation_month": 12,
    }]}, assume_completed_bachelors=True)
    assert "SCORING-ONLY EDUCATION PROJECTION" in context
    assert "Actual education timing: Example State University | in progress; expected December 2026" in context


def test_projected_degree_does_not_waive_required_professional_experience():
    result = assess([requirement(), requirement(status="unmet", quote="Five years of professional network administration required.",
                                               evidence="", reason="Five professional years are not established.")], projected=True)
    assert (result["score"], result["eligibility_status"]) == (4, "unmet")


def test_projected_degree_does_not_hide_incomplete_qualification_evidence():
    result = assess([requirement()], projected=True, incomplete=True)
    assert (result["score"], result["eligibility_status"]) == (6, "uncertain")


def test_degree_projection_changes_matching_not_candidate_facts_or_readiness(monkeypatch):
    import copy
    profile = {"education_schools": [{"school": "Example University", "degree": "Bachelor of Science",
                                     "major": "Public Health", "degree_received": False, "status": "in progress"}]}
    original = copy.deepcopy(profile)
    context = scorer._build_profile_evidence_context(profile, assume_completed_bachelors=True)
    projection_quote = next(line for line in context.splitlines() if line.startswith("SCORING-ONLY EDUCATION PROJECTION"))
    posting = "Bachelor's degree in Public Health required."

    class Client:
        def chat(self, messages, **kwargs):
            assert projection_quote in messages[-1]["content"]
            return "FIT_SCORE: 9\nMATCHED_SKILLS: Public Health\nMISSING_SKILLS: none\nSCORE_REASONING: Meets the degree requirement under the supplied projection.\nREQUIREMENTS_JSON: " + json.dumps([
                requirement(quote=posting, evidence=projection_quote, reason="Degree is assumed completed for matching.")
            ])

    monkeypatch.setattr(scorer, "get_client_for_stage", lambda _stage: Client())
    result = scorer.score_job("Bachelor of Science in progress.", {"title": "Program Assistant", "full_description": posting},
                              profile_context=context, source_verification="official")
    assert result["score"] == 9
    assert result["eligibility_status"] == "projected"
    assert result["application_readiness"] == "review"
    assert "degree_completion_pending" in json.loads(result["readiness_flags"])
    assert "projected fit" in result["apply_or_skip_reason"]
    assert "verified fit" not in result["apply_or_skip_reason"]
    assert json.loads(result["score_breakdown"])["qualification_score"] == 9
    assert profile == original


def test_unread_linked_qualifications_prevent_confirmed_eligibility():
    result = assess([requirement()], incomplete=True)
    assert result["eligibility_status"] == "uncertain"
    assert result["score"] == 6


def test_grader_cannot_silently_omit_an_explicit_years_requirement():
    result = qualification_assessment([requirement()],
        posting="A high school diploma is required. At least five years of network administration experience required.",
        evidence="High school diploma awarded.", raw_score=9)
    assert result["score"] == 6
    assert result["eligibility_status"] == "uncertain"
    assert "five years" in result["qualification_gaps"]


def test_coverage_warning_does_not_invent_a_negated_degree_requirement():
    result = qualification_assessment([requirement()],
        posting="A high school diploma is required. No college degree is required.",
        evidence="High school diploma awarded.", raw_score=9)
    assert result["score"] == 9
    assert result["eligibility_status"] == "meets"


@pytest.mark.parametrize("fragment", [
    "the degree of independence and judgment required in making determinations and",
    "Academic education from an accredited college/university may be substituted for the required experience on a year-for-year basis.",
    "12th grade may be substituted for one year of the required general experience",
    "(One year of clerical work experience may be substituted for the required",
    "required months of this experience before they can be eligible for",
    "at least one year in a position equivalent in level of responsibility to the",
    "Confidential information that should be excluded includes your driver license number (unless required).",
    "Required License or Certificate:",
    "A valid California Driver License, Class C or higher, may be required at the time of appointment.",
    "May need to possess a valid driver's license as required by the position.",
    "Official transcripts and official foreign degree transcripts will be required prior to appointment.",
    "Certification Required",
    "required general experience on the basis of either (a) one year of general",
    "Equivalent experience will be accepted in lieu of the required degree or diploma.",
    "Applicants who have completed all but six months will be admitted to the examination, but must complete the required months before appointment.",
    "If you do not have at least three (3) years experience with any of these technologies, select none.",
    "Incumbents are required to progress to journey level within 60 months of appointment.",
    "Depending upon assignment, demonstrated technical competency and/or certification pertaining to the information technology used by the appointing department may be required.",
])
def test_coverage_does_not_promote_conditions_headers_or_paperwork_to_minimums(fragment):
    result = qualification_assessment([requirement()],
        posting="A high school diploma is required.\n" + fragment,
        evidence="High school diploma awarded.", raw_score=9)
    assert (result["score"], result["eligibility_status"]) == (9, "meets")


def test_json_encoded_quote_arrays_still_require_every_verbatim_fact():
    posting = "A high school diploma is required. Two years of office experience required."
    evidence = "High school diploma awarded. Three years of office experience."
    row = requirement(quote=json.dumps(["A high school diploma is required.", "Two years of office experience required."]),
                      evidence=json.dumps(["High school diploma awarded.", "Three years of office experience."]))
    result = qualification_assessment([row], posting=posting, evidence=evidence, raw_score=8)
    assert result["score"] == 8
    row["evidence"] = json.dumps(["High school diploma awarded.", "Five years of office experience."])
    assert qualification_assessment([row], posting=posting, evidence=evidence, raw_score=8)["score"] == 6


def test_trainable_duty_gap_is_not_a_mandatory_previous_employment_requirement():
    duty = "Process records in the agency's filing system and learn the applicable rules."
    result = qualification_assessment([requirement(), requirement(kind="duty", status="uncertain", quote=duty, evidence="")],
        posting="A high school diploma is required. " + duty,
        evidence="High school diploma awarded.", raw_score=8)
    assert (result["score"], result["eligibility_status"]) == (8, "meets")


def test_literal_bracketed_quotation_is_not_mistaken_for_a_json_array():
    posting = "[A high school diploma is required.]"
    result = qualification_assessment([requirement(quote=posting)],
        posting=posting, evidence="High school diploma awarded.", raw_score=8)
    assert (result["score"], result["eligibility_status"]) == (8, "meets")


@pytest.mark.parametrize("hard_requirement", [
    "Bachelor's degree required.",
    "A valid California nursing license is required.",
    "CompTIA A+ certification required.",
    "Three (3) years of analytical experience required.",
    "At least 15 semester units of computer science.",
])
def test_false_positive_fixes_still_flag_omitted_real_minimums(hard_requirement):
    result = qualification_assessment([requirement()],
        posting="A high school diploma is required.\n" + hard_requirement,
        evidence="High school diploma awarded.", raw_score=9)
    assert (result["score"], result["eligibility_status"]) == (6, "uncertain")
    assert hard_requirement in result["qualification_gaps"]


def test_resume_skills_do_not_repeat_the_same_item():
    from divapply.scoring.tailor import _trim_list_items
    assert _trim_list_items("staff training, Staff Training, Excel, Excel, records", 3) == "staff training, Excel, records"


def test_unrelated_readable_exam_cannot_clear_a_failed_class_spec(monkeypatch):
    def fetch(_client, url):
        if "SpecCrossReference" in url:
            raise ValueError("unavailable")
        return httpx.Response(200, request=httpx.Request("GET", url), text="<main>Office Assistant Minimum Qualifications: High school diploma.</main>")
    monkeypatch.setattr(linked, "_fetch", fetch)
    result = linked.linked_qualification_evidence(
        '<a href="https://hrnet.calhr.ca.gov/SpecCrossReference.aspx">Research Data Analyst II</a>'
        '<a href="https://calcareers.ca.gov/ExamBulletin.aspx">Exam</a>', "https://calcareers.ca.gov/job")
    assert result["requirements_description"]
    assert "Research Data Analyst II" in result["requirements_error"]


def test_approved_cover_and_resume_fallbacks_both_get_pdf_database_links(tmp_path, monkeypatch):
    from divapply import config
    from divapply.scoring import pdf
    db_path = tmp_path / "jobs.db"
    conn = database.init_db(db_path)
    paths = [tmp_path / "resume.txt", tmp_path / "example_CL.txt"]
    for path in paths:
        path.write_text("Approved text", encoding="utf-8")
    (tmp_path / "unapproved.txt").write_text("Review required", encoding="utf-8")
    conn.execute("INSERT INTO jobs(url,title,tailored_resume_path,cover_letter_path) VALUES (?,?,?,?)",
                 ("https://example.com/1", "Assistant", *map(str, paths)))
    conn.commit()
    monkeypatch.setattr(database, "get_connection", lambda: conn)
    monkeypatch.setattr(pdf, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(config, "COVER_LETTER_DIR", tmp_path)
    monkeypatch.setattr(config, "load_profile", lambda: {})
    converted = []
    def convert(path, **_kwargs):
        converted.append(path)
        output = path.with_suffix(".pdf")
        output.write_bytes(b"PDF fixture")
        return output
    monkeypatch.setattr(pdf, "convert_to_pdf", convert)
    assert pdf.batch_convert(target_url="https://example.com/1") == 2
    saved = conn.execute("SELECT tailored_resume_path,cover_letter_path FROM jobs").fetchone()
    assert tuple(saved) == tuple(str(path.with_suffix(".pdf")) for path in paths)
    assert converted == paths
    database.close_connection(db_path)


def test_scoring_receives_requirements_after_application_headings_and_long_duties(monkeypatch):
    hard_requirement = "Five years of professional network administration required."
    description = "APPLICATION INSTRUCTIONS\nApply through our portal.\nDUTIES\n" + "Maintain network services. " * 700 + "\nMINIMUM QUALIFICATIONS\n" + hard_requirement
    seen = []

    class Client:
        def chat(self, messages, **kwargs):
            seen.append(messages[-1]["content"])
            return "FIT_SCORE: 9\nMATCHED_SKILLS: networking\nMISSING_SKILLS: none\nSCORE_REASONING: Strong keywords.\nREQUIREMENTS_JSON: " + json.dumps([
                requirement(status="unmet", quote=hard_requirement, evidence="", reason="Home labs are not five professional years.")
            ])

    monkeypatch.setattr(scorer, "get_client_for_stage", lambda _stage: Client())
    result = scorer.score_job("Independent home lab projects.", {"title": "Network Administrator", "full_description": description})
    assert hard_requirement in seen[0]
    assert "middle omitted" not in seen[0]
    assert result["score"] == 4
    assert result["eligibility_status"] == "unmet"
    assert result["scoring_version"] == SCORING_VERSION


def test_linked_qualification_text_is_part_of_the_audited_context():
    context = format_job_context({"full_description": "Posting duties.", "requirements_description": "Three years of analytical experience required."},
                                 description_limit=60000, preserve_sections=True)
    assert "Three years of analytical experience required." in context


def test_official_class_link_is_fetched_and_saved_with_its_source(monkeypatch):
    client_type = httpx.Client
    seen = []

    def respond(request):
        seen.append(str(request.url))
        return httpx.Response(200, text="<main><h1>Office Assistant</h1><h2>Minimum Qualifications</h2><p>High school education.</p></main>")

    monkeypatch.setattr(linked.httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))
    result = linked.linked_qualification_evidence(
        '<a href="https://hrnet.calhr.ca.gov/CalHRNet/SpecCrossReference.aspx?ClassID=1">Office Assistant</a>',
        "https://www.calcareers.ca.gov/CalHrPublic/Jobs/JobPosting.aspx?JobControlId=1",
    )
    assert len(seen) == 1
    assert "High school education" in result["requirements_description"]
    assert json.loads(result["requirements_sources"])[0]["status"] == "read"
    assert not result["requirements_error"]


def test_qualification_redirect_cannot_leave_the_official_domains():
    seen = []

    def respond(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://outside.example/spec"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="official state domains"):
            linked._fetch(client, "https://hrnet.calhr.ca.gov/spec")
    assert len(seen) == 1


def test_failed_class_download_is_visible_not_silently_ignored(monkeypatch):
    monkeypatch.setattr(linked, "_fetch", lambda *_: (_ for _ in ()).throw(ValueError("blocked")))
    result = linked.linked_qualification_evidence('<a href="https://hrnet.calhr.ca.gov/SpecCrossReference.aspx">Analyst II</a>',
                                                "https://www.calcareers.ca.gov/job")
    assert "Analyst II" in result["requirements_error"]
    assert not result["requirements_description"]


def test_repair_limit_and_dry_run_do_not_touch_jobs_or_call_ai(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    conn = database.init_db(db_path)
    for n in range(5):
        conn.execute("INSERT INTO jobs(url, title, fit_score) VALUES (?, ?, ?)", (f"https://example.com/{n}", f"Job {n}", 8))
    conn.commit()
    monkeypatch.setattr(job_health, "get_connection", lambda: conn)
    monkeypatch.setattr(scorer, "run_scoring", lambda **_: pytest.fail("dry-run called AI"))
    result = job_health.repair_jobs(limit=2, dry_run=True)
    assert result["selected"] == 2
    assert result["repaired"] == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE fit_score=8").fetchone()[0] == 5
    database.close_connection(db_path)


def test_unmet_qualifications_do_not_enter_document_or_autoapply_queue(tmp_path):
    db_path = tmp_path / "jobs.db"
    conn = database.init_db(db_path)
    conn.execute("INSERT INTO jobs(url,title,fit_score,full_description,application_mode,source_verification,eligibility_status) VALUES (?,?,?,?,?,?,?)",
                 ("https://example.com/1", "Analyst", 4, "Detailed requirements. " * 30, "active", "official", "unmet"))
    conn.commit()
    assert database.get_jobs_by_stage(conn=conn, stage="pending_tailor", min_score=1) == []
    database.close_connection(db_path)
