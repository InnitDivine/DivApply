from __future__ import annotations

from divapply.scoring.context import format_job_context
from divapply.scoring.cover_letter import _build_cover_letter_prompt, _read_tailored_resume_text, _strip_preamble
from divapply.scoring import cover_letter
from divapply.scoring.validator import validate_cover_letter


def _profile() -> dict:
    return {
        "skills_boundary": {
            "languages": ["Python", "SQL"],
            "tools": ["Excel"],
        }
    }


def _job() -> dict:
    return {
        "title": "Reporting Analyst",
        "company": "Example Health",
        "site": "Indeed",
        "location": "Remote",
        "full_description": "Build Python and SQL reporting for patient support workflows.",
    }


def _valid_letter(body: str = "I built Python reporting workflows that match this role's reporting work.") -> str:
    return "\n\n".join(
        [
            "Dear Hiring Manager,",
            body,
            "Example Health needs clear reporting for patient support workflows. Let's discuss.",
            "Jane",
        ]
    )


def test_strip_preamble_removes_leaked_intro() -> None:
    text = "Here is the cover letter:\n\nDear Hiring Manager,\nI built reports.\nJane"

    assert _strip_preamble(text).startswith("Dear Hiring Manager,")


def test_cover_reads_exact_owned_tailored_text(tmp_path, monkeypatch) -> None:
    tailored_dir = tmp_path / "tailored"
    tailored_dir.mkdir()
    artifact = tailored_dir / "role.txt"
    artifact.write_text("Exact tailored evidence", encoding="utf-8")
    monkeypatch.setattr(cover_letter, "TAILORED_DIR", tailored_dir)

    assert _read_tailored_resume_text({"tailored_resume_path": str(artifact)}) == "Exact tailored evidence"


def test_cover_rejects_missing_or_outside_tailored_artifact(tmp_path, monkeypatch) -> None:
    import pytest

    tailored_dir = tmp_path / "tailored"
    tailored_dir.mkdir()
    outside = tmp_path / "master.txt"
    outside.write_text("Master resume", encoding="utf-8")
    monkeypatch.setattr(cover_letter, "TAILORED_DIR", tailored_dir)

    with pytest.raises(FileNotFoundError):
        _read_tailored_resume_text({"tailored_resume_path": str(tailored_dir / "missing.txt")})
    with pytest.raises(ValueError, match="outside"):
        _read_tailored_resume_text({"tailored_resume_path": str(outside)})


def test_validate_cover_letter_blocks_generic_ai_phrase() -> None:
    report = validate_cover_letter(
        _valid_letter("I am writing to express my interest in the Reporting Analyst role."),
        mode="normal",
        profile=_profile(),
        job=_job(),
    )

    assert not report["passed"]
    assert any("Generic cover-letter phrase" in error for error in report["errors"])


def test_validate_cover_letter_blocks_job_only_tool_claim() -> None:
    job = _job() | {"full_description": "Build dashboards in Salesforce and SQL."}
    letter = _valid_letter("I have built Salesforce dashboards and SQL reporting workflows.")

    report = validate_cover_letter(
        letter,
        mode="normal",
        profile=_profile(),
        resume_text="Built SQL reports in Excel.",
        job=job,
    )

    assert not report["passed"]
    assert any("salesforce" in error.lower() for error in report["errors"])


def test_validate_cover_letter_blocks_private_credential_language() -> None:
    report = validate_cover_letter(
        _valid_letter("I used login tokens to automate Python reporting workflows."),
        mode="normal",
        profile=_profile(),
        resume_text="Built Python reports in Excel.",
        job=_job(),
    )

    assert not report["passed"]
    assert any("credential" in error.lower() for error in report["errors"])


def test_validate_cover_letter_blocks_too_long_normal_mode() -> None:
    long_body = " ".join(["Python reporting"] * 140)

    report = validate_cover_letter(
        _valid_letter(long_body),
        mode="normal",
        profile=_profile(),
        job=_job(),
    )

    assert not report["passed"]
    assert any("Too long" in error for error in report["errors"])


def test_format_job_context_includes_safe_referral_context_only() -> None:
    text = format_job_context(
        _job()
        | {
            "referral_context": "Referred by a current analyst for reporting work.",
            "employer_context": "password: secret",
        }
    )

    assert "REFERRAL CONTEXT: Referred by a current analyst for reporting work." in text
    assert "password" not in text.lower()
    assert "secret" not in text.lower()


def test_cover_prompt_keeps_transferable_work_and_availability_truthful() -> None:
    prompt = _build_cover_letter_prompt(
        {
            "experience": {"years_of_professional_it_experience": "0"},
            "personal": {"preferred_name": "Jane"},
        }
    )

    assert "Transferable experience is not the same as prior target-role employment" in prompt
    assert "Do not relabel front-desk work as IT support" in prompt
    assert 'never say the candidate has already done IT work "in the field"' in prompt
    assert 'do not claim a general "background in end-user support"' in prompt
    assert 'Do not call that verified work "client-facing"' in prompt
    assert "Do not claim phone, call, email, chat, training, or follow-up experience" in prompt
    assert 'Do not say the candidate has solved "the same problems from both sides"' in prompt
    assert "Do not promise relocation, commute, immediate on-site presence, or schedule availability" in prompt
    assert 'Never say a list of IT skills was used "across" paid/public-sector and lab/project settings' in prompt
    assert "Name the exact target job title once" in prompt
    assert "Never turn the target job title into the name of training" in prompt
    assert "never put a paid/public-sector setting and a home-lab/project setting in the same sentence" in prompt
    assert "Never merge separate projects" in prompt
    assert "client-sector list is company context, not candidate experience" in prompt
    assert "Keep each paid employer or paid-work setting in its own sentence" in prompt
    assert "Known projects to reference" not in prompt


def test_cover_validator_rejects_paid_it_relabel_when_profile_says_zero() -> None:
    profile = _profile() | {
        "experience": {"years_of_professional_it_experience": "0"},
    }
    report = validate_cover_letter(
        _valid_letter("My municipal front desk IT support and field support experience included ticket handling."),
        mode="strict",
        profile=profile,
        resume_text="Municipal front desk customer service; home-lab IT projects.",
        job=_job(),
    )

    assert not report["passed"]
    assert any("professional IT experience boundary" in error for error in report["errors"])


def test_cover_validator_rejects_cross_context_it_and_healthcare_overclaims() -> None:
    profile = _profile() | {
        "experience": {
            "years_of_professional_it_experience": "0",
            "years_of_professional_healthcare_experience": "0",
        },
    }
    bodies = (
        "I support computers, networks, and users in real settings from municipal front desks.",
        "At the municipal counter I solved access and device-related issues for users.",
        "I bring a year of patient-facing service from a municipal public counter.",
        "This IT support role matches work I have already done in the field and in my home lab.",
        "This role matches my background in end-user support, Windows, and Linux troubleshooting.",
    )

    for body in bodies:
        report = validate_cover_letter(
            _valid_letter(body),
            mode="strict",
            profile=profile,
            resume_text="Municipal customer service; county ERP work; separate home-lab IT projects.",
            job=_job(),
        )
        assert not report["passed"], body


def test_cover_validator_rejects_candidate_name_repeated_after_salutation() -> None:
    profile = _profile() | {"personal": {"full_name": "Jane Doe"}}
    report = validate_cover_letter(
        "Dear Hiring Manager,\n\nJane Doe, I built Python reports in Excel.\n\nExample Health needs reporting.\n\nJane",
        mode="strict",
        profile=profile,
        resume_text="Built Python reports in Excel.",
        job=_job(),
    )

    assert not report["passed"]
    assert any("candidate name after salutation" in error for error in report["errors"])


def test_cover_validator_rejects_paid_role_and_it_skill_context_joins() -> None:
    profile = _profile() | {
        "experience": {"years_of_professional_it_experience": "0"},
    }
    bodies = (
        "In municipal front desk support, I handled technology questions for end users.",
        "I handled front-line technical questions in a high-volume municipal setting.",
        "I bring Windows 10/11 support and customer service from real operations work.",
    )

    for body in bodies:
        report = validate_cover_letter(
            _valid_letter(body),
            mode="strict",
            profile=profile,
            resume_text="Municipal customer service; separate home-lab Windows projects.",
            job=_job(),
        )
        assert not report["passed"], body
        assert any("professional IT experience boundary" in error for error in report["errors"])


def test_cover_validator_rejects_ambiguous_cross_setting_skill_attribution() -> None:
    report = validate_cover_letter(
        _valid_letter(
            "Microsoft 365, Windows troubleshooting, and written procedures match work I have done "
            "across public-sector and lab settings."
        ),
        mode="strict",
        profile=_profile() | {"experience": {"years_of_professional_it_experience": "0"}},
        resume_text="Public-sector Microsoft 365 procedures; separate home-lab Windows troubleshooting.",
        job=_job(),
    )

    assert not report["passed"]
    assert any("across paid-work and lab settings" in error for error in report["errors"])


def test_cover_validator_rejects_target_title_recast_as_training() -> None:
    job = _job() | {"title": "IT Support Specialist (Part-Time)"}
    report = validate_cover_letter(
        _valid_letter(
            "The IT Support Specialist (Part-Time) role fits my goals. "
            "My current IT Support Specialist training gives me a direct base for this role."
        ),
        mode="strict",
        profile=_profile(),
        resume_text=(
            "IT Support Specialist\nInformation Technology Certificate Program (in progress)\n"
            "Built a Windows home lab."
        ),
        job=job,
    )

    assert not report["passed"]
    assert any("target job title as unsupported training" in error for error in report["errors"])


def test_cover_validator_rejects_mixed_paid_and_lab_it_sentence() -> None:
    report = validate_cover_letter(
        _valid_letter(
            "My Windows troubleshooting, PC hardware, Microsoft 365, and basic networking were built "
            "through home lab work and structured public-sector roles."
        ),
        mode="strict",
        profile=_profile() | {"experience": {"years_of_professional_it_experience": "0"}},
        resume_text="Public-sector records work. Separate home lab with Windows troubleshooting.",
        job=_job(),
    )

    assert not report["passed"]
    assert any("paid-work and lab evidence" in error for error in report["errors"])


def test_cover_validator_rejects_project_domain_absent_from_tailored_resume() -> None:
    report = validate_cover_letter(
        _valid_letter("I built candidate.example.com with Nginx and Docker."),
        mode="strict",
        profile=_profile() | {"resume_facts": {"preserved_projects": ["candidate.example.com", "Docker lab"]}},
        resume_text="Home lab: Docker services. Separate portfolio project omitted from this tailored resume.",
        job=_job(),
    )

    assert not report["passed"]
    assert any("anchor absent from tailored resume" in error for error in report["errors"])


def test_cover_validator_rejects_employer_sectors_as_candidate_experience() -> None:
    report = validate_cover_letter(
        _valid_letter(
            "Example Health serves education, nonprofit, healthcare, and government clients, and that mix "
            "fits the settings where I have already worked."
        ),
        mode="strict",
        profile=_profile() | {"experience": {"years_of_professional_healthcare_experience": "0"}},
        resume_text="Municipal work, school-district work, and public-health education.",
        job=_job(),
    )

    assert not report["passed"]
    assert any("sector context" in error for error in report["errors"])


def test_cover_validator_rejects_recorded_gap_punctuation_alias() -> None:
    report = validate_cover_letter(
        _valid_letter("Accurate municipal records fit the asset-tracking discipline this role needs."),
        mode="strict",
        profile=_profile(),
        resume_text="Municipal records and separate general theatre inventory.",
        job=_job() | {"missing_skills": "asset inventory"},
    )

    assert not report["passed"]
    assert any("recorded candidate evidence gap" in error for error in report["errors"])


def test_cover_validator_rejects_city_and_county_duty_aggregation() -> None:
    report = validate_cover_letter(
        _valid_letter(
            "I bring public-sector support from the City front desk and county accounting work that required "
            "structured procedures, records handling, and escalation."
        ),
        mode="strict",
        profile=_profile() | {"experience": {"years_of_professional_it_experience": "0"}},
        resume_text="City front desk issue escalation. County accounting records and ERP procedures.",
        job=_job(),
    )

    assert not report["passed"]
    assert any("distinct paid-work settings" in error for error in report["errors"])


def test_cover_validator_rejects_client_relabel_without_resume_evidence() -> None:
    report = validate_cover_letter(
        _valid_letter("My municipal public-counter work and home lab provide a mix of client-facing problem solving."),
        mode="strict",
        profile=_profile(),
        resume_text="Municipal resident service and member support.",
        job=_job(),
    )

    assert not report["passed"]
    assert any("client-facing" in error for error in report["errors"])


def test_cover_validator_rejects_unsupported_channel_and_context_equivalence() -> None:
    bodies = (
        "I have worked the same kind of problems from both sides, public service and technical troubleshooting.",
        "Your regular follow-up calls fit the way I have worked in public-facing roles.",
        "Your virtual trainings and follow-up work match the kind of service I have done.",
    )

    for body in bodies:
        report = validate_cover_letter(
            _valid_letter(body),
            mode="strict",
            profile=_profile(),
            resume_text="Municipal resident service and separate home-lab projects.",
            job=_job(),
        )
        assert not report["passed"], body


def test_generate_cover_letter_raises_after_validation_retries_are_exhausted(
    monkeypatch,
) -> None:
    class InvalidClient:
        def chat(self, *_args, **_kwargs) -> str:
            return _valid_letter("I am writing to express my interest in this role.")

    monkeypatch.setattr(cover_letter, "get_client_for_stage", lambda _stage: InvalidClient())

    import pytest

    with pytest.raises(cover_letter.CoverLetterValidationError):
        cover_letter.generate_cover_letter(
            "Built Python reports in Excel.",
            _job(),
            _profile(),
            max_retries=1,
            validation_mode="strict",
        )
