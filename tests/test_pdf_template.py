from __future__ import annotations

from divapply.scoring.pdf import build_html, parse_resume


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
