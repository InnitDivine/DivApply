from __future__ import annotations

from divapply.apply import answers
from divapply.apply import prompt as prompt_mod


def test_apply_prompt_keeps_company_and_source_separate(tmp_path, monkeypatch) -> None:
    resume_txt = tmp_path / "tailored.txt"
    resume_pdf = tmp_path / "tailored.pdf"
    resume_txt.write_text("resume text", encoding="utf-8")
    resume_pdf.write_bytes(b"%PDF-1.4\n")

    profile = {
        "personal": {
            "full_name": "Example Person",
            "email": "person@example.com",
            "phone": "555-0100",
            "city": "Auburn",
        }
    }

    monkeypatch.setattr(prompt_mod.config, "APPLY_WORKER_DIR", tmp_path / "workers")
    monkeypatch.setattr(prompt_mod.config, "load_profile", lambda: profile)
    monkeypatch.setattr(prompt_mod.config, "load_search_config", lambda: {})
    monkeypatch.setattr(prompt_mod.config, "load_blocked_sso", lambda: [])
    monkeypatch.setattr(prompt_mod.config, "load_credentials", lambda: {})
    monkeypatch.setattr(prompt_mod, "_build_profile_summary", lambda profile: "profile summary")
    monkeypatch.setattr(prompt_mod, "_build_location_check", lambda profile, search_config: "location check")
    monkeypatch.setattr(prompt_mod, "_build_salary_section", lambda profile: "salary section")
    monkeypatch.setattr(prompt_mod, "_build_screening_section", lambda profile: "screening section")
    monkeypatch.setattr(prompt_mod, "_build_hard_rules", lambda profile: "hard rules")
    monkeypatch.setattr(answers, "render_answer_bank_for_prompt", lambda: "answer bank")

    prompt = prompt_mod.build_prompt(
        job={
            "url": "https://example.com/job",
            "application_url": "https://example.com/apply",
            "title": "Support Analyst",
            "company": "Real Employer",
            "site": "Indeed",
            "fit_score": 8,
            "tailored_resume_path": str(resume_txt),
        },
        tailored_resume="resume text",
    )

    assert "Company: Real Employer" in prompt
    assert "Source: Indeed" in prompt
    assert "Company: Indeed" not in prompt


def test_apply_prompt_ignores_credentials_saved_in_profile(tmp_path, monkeypatch) -> None:
    resume_txt = tmp_path / "tailored.txt"
    resume_pdf = tmp_path / "tailored.pdf"
    resume_txt.write_text("resume text", encoding="utf-8")
    resume_pdf.write_bytes(b"%PDF-1.4\n")

    profile = {
        "personal": {
            "full_name": "Example Person",
            "email": "person@example.com",
            "phone": "555-0100",
            "city": "Logan",
            "password": "profile-default-secret",
        },
        "site_credentials": {
            "example.com": {
                "username": "profile-user",
                "password": "profile-site-secret",
            }
        },
    }

    monkeypatch.delenv("DIVAPPLY_LOGIN_USERNAME", raising=False)
    monkeypatch.delenv("DIVAPPLY_LOGIN_PASSWORD", raising=False)
    monkeypatch.delenv("APPLYPILOT_LOGIN_USERNAME", raising=False)
    monkeypatch.delenv("APPLYPILOT_LOGIN_PASSWORD", raising=False)
    monkeypatch.setattr(prompt_mod.config, "APPLY_WORKER_DIR", tmp_path / "workers")
    monkeypatch.setattr(prompt_mod.config, "load_profile", lambda: profile)
    monkeypatch.setattr(prompt_mod.config, "load_search_config", lambda: {})
    monkeypatch.setattr(prompt_mod.config, "load_blocked_sso", lambda: [])
    monkeypatch.setattr(prompt_mod.config, "load_credentials", lambda: {})
    monkeypatch.setattr(prompt_mod, "_build_profile_summary", lambda profile: "profile summary")
    monkeypatch.setattr(prompt_mod, "_build_location_check", lambda profile, search_config: "location check")
    monkeypatch.setattr(prompt_mod, "_build_salary_section", lambda profile: "salary section")
    monkeypatch.setattr(prompt_mod, "_build_screening_section", lambda profile: "screening section")
    monkeypatch.setattr(prompt_mod, "_build_hard_rules", lambda profile: "hard rules")
    monkeypatch.setattr(answers, "render_answer_bank_for_prompt", lambda: "answer bank")

    prompt = prompt_mod.build_prompt(
        job={
            "url": "https://example.com/job",
            "application_url": "https://example.com/apply",
            "title": "Support Analyst",
            "company": "Real Employer",
            "site": "Indeed",
            "fit_score": 8,
            "tailored_resume_path": str(resume_txt),
        },
        tailored_resume="resume text",
    )

    assert "profile-default-secret" not in prompt
    assert "profile-site-secret" not in prompt
    assert "profile-user" not in prompt
    assert "No saved default password is available" in prompt


def test_salary_section_uses_part_time_guidance_when_full_time_unavailable() -> None:
    section = prompt_mod._build_salary_section(
        {
            "availability": {"available_for_full_time": "No while in school"},
            "compensation": {
                "salary_expectation": "55000",
                "salary_currency": "USD",
                "salary_range_min": "45000",
                "salary_range_max": "65000",
                "part_time_hourly_expectation": "Use posted hourly range.",
            },
        }
    )

    assert "low-hour part-time work while in school" in section
    assert "Use posted hourly range." in section
    assert "Do not apply unless the user explicitly selected it" in section


def test_apply_prompt_allows_normal_hourly_employee_applications(tmp_path, monkeypatch) -> None:
    resume_txt = tmp_path / "tailored.txt"
    resume_pdf = tmp_path / "tailored.pdf"
    resume_txt.write_text("resume text", encoding="utf-8")
    resume_pdf.write_bytes(b"%PDF-1.4\n")

    profile = {
        "personal": {
            "full_name": "Example Person",
            "email": "person@example.com",
            "phone": "555-0100",
            "city": "Logan",
        },
        "availability": {"available_for_full_time": "No while in school"},
        "compensation": {
            "salary_expectation": "55000",
            "salary_currency": "USD",
            "salary_range_min": "45000",
            "salary_range_max": "65000",
        },
    }

    monkeypatch.setattr(prompt_mod.config, "APPLY_WORKER_DIR", tmp_path / "workers")
    monkeypatch.setattr(prompt_mod.config, "load_profile", lambda: profile)
    monkeypatch.setattr(prompt_mod.config, "load_search_config", lambda: {})
    monkeypatch.setattr(prompt_mod.config, "load_blocked_sso", lambda: [])
    monkeypatch.setattr(prompt_mod.config, "load_credentials", lambda: {})
    monkeypatch.setattr(prompt_mod, "_build_profile_summary", lambda profile: "profile summary")
    monkeypatch.setattr(prompt_mod, "_build_location_check", lambda profile, search_config: "location check")
    monkeypatch.setattr(prompt_mod, "_build_screening_section", lambda profile: "screening section")
    monkeypatch.setattr(prompt_mod, "_build_hard_rules", lambda profile: "hard rules")
    monkeypatch.setattr(answers, "render_answer_bank_for_prompt", lambda: "answer bank")

    prompt = prompt_mod.build_prompt(
        job={
            "url": "https://example.com/job",
            "application_url": "https://example.com/apply",
            "title": "Front Desk Attendant",
            "company": "Real Employer",
            "site": "Indeed",
            "fit_score": 8,
            "tailored_resume_path": str(resume_txt),
        },
        tailored_resume="resume text",
    )

    assert "Normal hourly employee applications are OK" in prompt
    assert "FULL-TIME salaried positions only" not in prompt
