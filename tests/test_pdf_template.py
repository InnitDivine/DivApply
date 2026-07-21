from __future__ import annotations

import sys
import types

import pytest

from divapply.scoring import cover_letter as cover_letter_mod
from divapply.scoring import pdf as pdf_mod
from divapply.scoring import tailor as tailor_mod
from divapply.scoring.pdf import (
    build_cover_letter_html,
    build_html,
    parse_entries,
    parse_resume,
    parse_skills,
    render_pdf,
)


def test_batch_convert_propagates_item_failures(monkeypatch, tmp_path) -> None:
    from divapply.scoring import pdf

    (tmp_path / "resume.txt").write_text("resume", encoding="utf-8")
    monkeypatch.setattr(pdf, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(
        pdf,
        "convert_to_pdf",
        lambda _path: (_ for _ in ()).throw(RuntimeError("browser missing")),
    )

    with pytest.raises(RuntimeError, match="1 PDF conversion"):
        pdf.batch_convert()


def test_resume_html_uses_orange_cream_one_page_template() -> None:
    resume = parse_resume("""Example Person
IT Support Specialist
Sampleville, CA | person@example.com

SUMMARY
Hands-on support professional with Linux, Windows, and public-facing troubleshooting experience.

TECHNICAL SKILLS
Operating Systems: Windows, Linux
Tools: Python, SQL, Docker

EXPERIENCE
Support Analyst
Real Employer | 2025 - Present
- Troubleshot user issues and documented fixes.

EDUCATION
Associate Degree
Example College | 2024
""")

    html = build_html(resume)

    assert "@page" in html
    assert "size: letter" in html
    assert "margin: 0.32in 0.42in 0.28in 0.42in" in html
    assert "#c17f3e" in html
    assert "#e8dcc8" in html
    assert "font-family: Arial, 'Segoe UI', sans-serif" in html
    assert "font-family: Georgia, 'Times New Roman', serif" in html
    assert "Technical Skills" in html
    assert "fonts.googleapis.com" not in html
    assert "grid-template-columns: 1fr 1fr" not in html
    assert html.index("Real Employer") < html.index("2025 - Present")


def test_v98_ats_pdf_validator_accepts_complete_linear_text(monkeypatch, tmp_path) -> None:
    source = """Example Person
person@example.com

SUMMARY
Support professional with Windows troubleshooting experience.

EXPERIENCE
Support Assistant | Example Employer | 2024 - Present
- Documented support requests and resolved user issues.

EDUCATION
Associate Degree
Example College | 2024
"""

    class Page:
        def extract_text(self) -> str:
            return source

    class Reader:
        is_encrypted = False
        pages = [Page()]

    monkeypatch.setattr(pdf_mod, "PdfReader", lambda _path: Reader(), raising=False)

    report = pdf_mod.validate_ats_pdf(
        source,
        tmp_path / "resume.pdf",
        required_sections=["SUMMARY", "EXPERIENCE", "EDUCATION"],
    )

    assert report["token_coverage"] == 1.0
    assert report["sections_in_order"] is True


def test_v98_ats_pdf_validator_rejects_scrambled_section_order(monkeypatch, tmp_path) -> None:
    source = """Example Person

SUMMARY
Windows support experience.

EXPERIENCE
Support Assistant

EDUCATION
Example College
"""
    extracted = """Example Person

EDUCATION
Example College

SUMMARY
Windows support experience.

EXPERIENCE
Support Assistant
"""

    class Page:
        def extract_text(self) -> str:
            return extracted

    class Reader:
        is_encrypted = False
        pages = [Page()]

    monkeypatch.setattr(pdf_mod, "PdfReader", lambda _path: Reader(), raising=False)

    with pytest.raises(RuntimeError, match="ATS-readable"):
        pdf_mod.validate_ats_pdf(
            source,
            tmp_path / "resume.pdf",
            required_sections=["SUMMARY", "EXPERIENCE", "EDUCATION"],
        )


def test_v98_convert_to_pdf_deletes_output_when_ats_validation_fails(monkeypatch, tmp_path) -> None:
    source = tmp_path / "resume.txt"
    output = tmp_path / "resume.pdf"
    source.write_text("Example Person\n\nSUMMARY\nSupport experience.", encoding="utf-8")

    def fake_render(_html: str, output_path: str) -> None:
        from pathlib import Path

        Path(output_path).write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(pdf_mod, "render_pdf", fake_render)
    monkeypatch.setattr(
        pdf_mod,
        "validate_ats_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("not ATS-readable")),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="ATS-readable"):
        pdf_mod.convert_to_pdf(source, output_path=output)

    assert not output.exists()


def test_resume_html_escapes_resume_controlled_text() -> None:
    resume = parse_resume("""Example <Person>
IT & Support
person@example.com

SUMMARY
Support work with A&B <systems>.

EXPERIENCE
Support Analyst
AT&T <Ops> | 2025 - Present
- Fixed <broken> forms & reports.
""")

    html = build_html(resume)

    assert "Example &lt;Person&gt;" in html
    assert "IT &amp; Support" in html
    assert "A&amp;B &lt;systems&gt;" in html
    assert "AT&amp;T &lt;Ops&gt;" in html
    assert "Fixed &lt;broken&gt; forms &amp; reports." in html


def test_cover_letter_html_escapes_text_but_keeps_contact_separator() -> None:
    html = build_cover_letter_html(
        "Dear Hiring Manager,\n\nI support A&B <systems>.",
        {
            "personal": {
                "full_name": "Example <Person>",
                "email": "person@example.com",
                "phone": "555-0100",
                "city": "Sampleville",
                "province_state": "CA",
            }
        },
    )

    assert "Example &lt;Person&gt;" in html
    assert "A&amp;B &lt;systems&gt;" in html
    assert "&nbsp;|&nbsp;" in html
    assert "fonts.googleapis.com" not in html


def test_convert_to_pdf_html_only_detects_cover_letter_by_filename(tmp_path) -> None:
    from divapply.scoring.pdf import convert_to_pdf

    text_path = tmp_path / "Example_CL.txt"
    text_path.write_text("Hello,\n\nI support A&B <systems>.", encoding="utf-8")

    out = convert_to_pdf(
        text_path,
        output_path=tmp_path / "cover.html",
        html_only=True,
        profile={"personal": {"full_name": "Example Person", "email": "person@example.com"}},
    )

    html = out.read_text(encoding="utf-8")
    assert "Example Person" in html
    assert "A&amp;B &lt;systems&gt;" in html
    assert "Dear" not in text_path.read_text(encoding="utf-8")


def test_parse_resume_handles_malformed_generated_headings_and_preserves_sections() -> None:
    resume = parse_resume("""Example Person
Support Analyst
person@example.com

Summary:
Direct support professional with Windows and Linux troubleshooting experience.

### Technical Skills
- Operating Systems: Windows, Linux
- Tools: Python, SQL

Work Experience
Support Analyst
Example Employer | 2025 - Present
1. Troubleshot user issues and documented repeatable fixes.

Projects
Home Lab
Windows and Linux | 2024
- Built a small test environment.

Certifications & Licenses:
- CompTIA A+

Education
Associate Degree
Example College | 2024
""")

    assert resume["sections"]["SUMMARY"].startswith("Direct support")
    assert "TECHNICAL SKILLS" in resume["sections"]
    assert "EXPERIENCE" in resume["sections"]
    assert "PROJECTS" in resume["sections"]
    assert "CERTIFICATIONS" in resume["sections"]
    assert "EDUCATION" in resume["sections"]

    assert parse_skills(resume["sections"]["TECHNICAL SKILLS"]) == [
        ("Operating Systems", "Windows, Linux"),
        ("Tools", "Python, SQL"),
    ]
    assert parse_entries(resume["sections"]["EXPERIENCE"])[0]["bullets"] == [
        "Troubleshot user issues and documented repeatable fixes."
    ]

    html = build_html(resume)

    assert "Projects &amp; Home Lab" in html
    assert "Certifications &amp; Licenses" in html
    assert "Education" in html


def test_additional_experience_renders_as_distinct_compact_entries() -> None:
    resume = parse_resume("""Example Person
IT Support
person@example.com

EXPERIENCE
Support Assistant | Example Employer | 2025 - Present
- Documented support requests.

ADDITIONAL EXPERIENCE
Substitute Teacher | Example School District | 2023 - 2024
Equipment Operator | Example Mine | 2020 - 2021

EDUCATION
Associate Degree
Example College | 2024
""")

    assert "ADDITIONAL EXPERIENCE" in resume["sections"]
    html = build_html(resume)
    assert "Additional Experience" in html
    assert "Substitute Teacher" in html
    assert "Equipment Operator" in html
    assert html.index(">Additional Experience<") < html.index(">Education<")


def test_parse_resume_keeps_all_contact_lines_after_title_and_location() -> None:
    resume = parse_resume(
        """Example Person
IT Support Candidate
Exampletown, ZZ | Open to relocation
(555) 010-0100 | person@example.com
LinkedIn: https://linkedin.example/person
GitHub: https://github.com/example-person
Website: https://example-person.invalid

SUMMARY
Entry-level support candidate.
"""
    )

    assert resume["title"] == "IT Support Candidate"
    assert resume["location"] == "Exampletown, ZZ | Open to relocation"
    assert resume["contact"] == (
        "(555) 010-0100 | person@example.com | "
        "LinkedIn: https://linkedin.example/person | "
        "GitHub: https://github.com/example-person | "
        "Website: https://example-person.invalid"
    )
    html = build_html(resume)
    assert "Exampletown, ZZ" in html
    assert "person@example.com" in html
    assert "github.com/example-person" in html
    assert "example-person.invalid" in html


def test_parse_resume_keeps_contact_links_after_blank_header_separator() -> None:
    resume = parse_resume(
        """Example Person
IT Support Candidate
Exampletown, ZZ | person@example.com

LinkedIn: https://linkedin.example/person
GitHub: https://github.com/example-person

SUMMARY
Entry-level support candidate.
"""
    )

    assert "person@example.com" in resume["contact"]
    assert "linkedin.example/person" in resume["contact"]
    assert "github.com/example-person" in resume["contact"]


def test_render_pdf_blocks_external_network_resources(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    class FakeRequest:
        def __init__(self, url: str) -> None:
            self.url = url

    class FakeRoute:
        def __init__(self, url: str) -> None:
            self.request = FakeRequest(url)

        def abort(self) -> None:
            calls.append(f"abort:{self.request.url}")

        def continue_(self) -> None:
            calls.append(f"continue:{self.request.url}")

    class FakePage:
        def route(self, _pattern, handler) -> None:
            handler(FakeRoute("https://example.com/font.css"))
            handler(FakeRoute("data:text/plain,ok"))

        def set_content(self, _html, wait_until) -> None:
            calls.append(f"content:{wait_until}")

        def pdf(self, path, **_kwargs) -> None:
            calls.append(f"pdf:{path}")

    class FakeBrowser:
        def new_page(self) -> FakePage:
            return FakePage()

        def close(self) -> None:
            calls.append("close")

    class FakeChromium:
        def launch(self) -> FakeBrowser:
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    fake_sync_api = types.SimpleNamespace(sync_playwright=lambda: FakePlaywright())
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_sync_api))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    render_pdf("<html><body>Test</body></html>", str(tmp_path / "out.pdf"))

    assert "abort:https://example.com/font.css" in calls
    assert "continue:data:text/plain,ok" in calls
    assert "content:domcontentloaded" in calls


def test_generated_artifact_cleanup_stays_inside_expected_roots(tmp_path, monkeypatch) -> None:
    tailored_dir = tmp_path / "tailored_resumes"
    cover_dir = tmp_path / "cover_letters"
    outside_dir = tmp_path / "outside"
    tailored_dir.mkdir()
    cover_dir.mkdir()
    outside_dir.mkdir()
    monkeypatch.setattr(tailor_mod, "TAILORED_DIR", tailored_dir)
    monkeypatch.setattr(cover_letter_mod, "COVER_LETTER_DIR", cover_dir)

    resume_txt = tailored_dir / "Example.txt"
    job_trace = tailored_dir / "Example_JOB.txt"
    report = tailored_dir / "Example_REPORT.json"
    pdf = tailored_dir / "Example.pdf"
    outside = outside_dir / "Example.txt"
    cover_txt = cover_dir / "Example_CL.txt"
    unexpected_cover = cover_dir / "Example.txt"
    for path in (resume_txt, job_trace, report, pdf, outside, cover_txt, unexpected_cover):
        path.write_text("x", encoding="utf-8")

    tailor_mod._delete_temp_artifacts(resume_txt, job_trace, report, pdf, outside)
    cover_letter_mod._delete_temp_artifact(cover_txt)
    cover_letter_mod._delete_temp_artifact(unexpected_cover)

    assert not resume_txt.exists()
    assert not job_trace.exists()
    assert not report.exists()
    assert pdf.exists()
    assert outside.exists()
    assert not cover_txt.exists()
    assert unexpected_cover.exists()


def test_pdf_preserves_core_qualifications_heading() -> None:
    resume = parse_resume(
        """Jane Doe
Client Relations Specialist
jane@example.com

SUMMARY
Factual summary.

CORE QUALIFICATIONS
Public Service: Issue triage, records, escalation

EXPERIENCE
Assistant
Example Employer | 2022-Present
- Documented requests.

EDUCATION
Example College
"""
    )

    html = build_html(resume)

    assert "CORE QUALIFICATIONS" in resume["sections"]
    assert "Core Qualifications" in html
    assert "Technical Skills" not in html


def test_education_details_use_html_entity_without_mojibake() -> None:
    resume = parse_resume(
        """Jane Doe
jane@example.com

EDUCATION
Bachelor of Science (in progress)
Example University
Expected 2027
GPA: 3.6
"""
    )

    html = build_html(resume)

    assert "&middot;" in html
    assert "Â" not in html


def test_parse_entries_joins_indented_bullet_continuations() -> None:
    entries = parse_entries(
        """First Role
Example Employer | 2024-Present
- Processed requests and
  maintained records.

Second Role
Other Employer | 2022-2023
- Supported operations.
"""
    )

    assert [entry["title"] for entry in entries] == ["First Role", "Second Role"]
    assert entries[0]["bullets"] == ["Processed requests and maintained records."]


def test_parse_resume_recognizes_projects_and_home_lab_heading() -> None:
    resume = parse_resume(
        """Jane Doe
jane@example.com

EXPERIENCE
Assistant
Example Employer | 2024-Present
- Supported operations.

PROJECTS & HOME LAB
Home Lab
Linux | 2024-Present
- Administered a server.

EDUCATION
Example University
"""
    )

    assert "PROJECTS" in resume["sections"]
    assert "Home Lab" in resume["sections"]["PROJECTS"]
    assert "Home Lab" not in resume["sections"]["EXPERIENCE"]
