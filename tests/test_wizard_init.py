from __future__ import annotations

import json

from divapply.wizard import init as wizard_init


def test_infer_profile_defaults_from_resume_text() -> None:
    resume = """Example Person
example@example.com | (555) 123-4567 | https://linkedin.com/in/example | https://github.com/example

SKILLS
Customer service, Data entry, Microsoft Office
Scheduling

EXPERIENCE
Front Desk Associate | Example Employer | 2024-Present

EDUCATION
Example College, Associate Degree, GPA 3.2
"""

    defaults = wizard_init._infer_profile_defaults(resume)

    assert defaults["full_name"] == "Example Person"
    assert defaults["email"] == "example@example.com"
    assert defaults["phone"] == "(555) 123-4567"
    assert defaults["linkedin_url"] == "https://linkedin.com/in/example"
    assert defaults["github_url"] == "https://github.com/example"
    assert defaults["skills"] == "Customer service, Data entry, Microsoft Office, Scheduling"
    assert defaults["current_job_title"] == "Front Desk Associate"
    assert defaults["preserved_companies"] == "Example Employer"
    assert defaults["education_level"] == "Associate Degree"
    assert "GPA 3.2" in defaults["real_metrics"]


def test_setup_profile_uses_simplified_schema_and_omits_stale_prompts(tmp_path, monkeypatch) -> None:
    resume_path = tmp_path / "resume.txt"
    profile_path = tmp_path / "profile.json"
    resume_path.write_text(
        """Example Person
example@example.com | 555-123-4567

SKILLS
Customer service, Data entry
""",
        encoding="utf-8",
    )

    prompts: list[str] = []

    def fake_prompt(message: str, *args, default: str = "", **kwargs) -> str:
        prompts.append(message)
        required_answers = {
            "City": "Logan",
            "Country": "United States",
            "Currency": "USD",
        }
        return required_answers.get(message, default)

    monkeypatch.setattr(wizard_init, "RESUME_PATH", resume_path)
    monkeypatch.setattr(wizard_init, "RESUME_PDF_PATH", tmp_path / "missing.pdf")
    monkeypatch.setattr(wizard_init, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(wizard_init.Prompt, "ask", fake_prompt)
    monkeypatch.setattr(wizard_init.Confirm, "ask", lambda *args, **kwargs: False)
    monkeypatch.setattr(wizard_init, "protect_file", lambda path: None)

    profile = wizard_init._setup_profile()
    saved = json.loads(profile_path.read_text(encoding="utf-8"))

    assert saved == profile
    assert profile["personal"]["full_name"] == "Example Person"
    assert profile["personal"]["email"] == "example@example.com"
    assert profile["skills"] == ["Customer service", "Data entry"]
    assert "skills_boundary" not in profile
    assert "target_role" not in profile["experience"]
    assert "years_of_experience_total" not in profile["experience"]

    stale_prompts = {
        "Target role (what you're applying for, e.g. 'Senior Backend Engineer')",
        "Years of professional experience",
        "Programming languages",
        "Frameworks & libraries",
        "Tools & platforms (e.g. Docker, AWS, Git)",
    }
    assert stale_prompts.isdisjoint(prompts)
