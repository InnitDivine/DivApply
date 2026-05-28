from __future__ import annotations

from divapply.scoring.pdf import build_cover_letter_html, build_html, parse_resume


def test_resume_html_uses_orange_cream_one_page_template() -> None:
    resume = parse_resume("""Example Person
IT Support Specialist
Auburn, CA | person@example.com

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
    assert "Playfair Display" in html
    assert "DM Sans" in html
    assert "Technical Skills" in html


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
                "city": "Auburn",
                "province_state": "CA",
            }
        },
    )

    assert "Example &lt;Person&gt;" in html
    assert "A&amp;B &lt;systems&gt;" in html
    assert "&nbsp;|&nbsp;" in html
