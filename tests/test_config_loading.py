from __future__ import annotations

import json

import yaml
import pytest

from divapply import config


def test_resolve_config_file_strictly_protects_user_override(tmp_path, monkeypatch) -> None:
    import divapply.security as security

    user_config = tmp_path / "user"
    user_config.mkdir()
    override = user_config / "sites.yaml"
    override.write_text("sites: []\n", encoding="utf-8")
    protected: list[tuple[object, bool]] = []
    monkeypatch.setattr(config, "USER_CONFIG_DIR", user_config)
    monkeypatch.setattr(
        security,
        "protect_file",
        lambda path, *, strict=True: protected.append((path, strict)),
    )

    assert config.resolve_config_file("sites.yaml") == override
    assert protected == [(override, True)]


def test_load_profile_overlays_canonical_transcript_school_facts(tmp_path, monkeypatch) -> None:
    from divapply import database

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "education_schools": [
                    {
                        "school": "Example University",
                        "gpa": "3.99",
                        "units": "101",
                        "notes": "Editable narrative remains.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(config, "LEGACY_PROFILE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(config, "load_search_config", lambda: {})
    monkeypatch.setattr(database, "get_coursework", lambda: [])
    monkeypatch.setattr(
        database,
        "get_education_records",
        lambda: [
            {
                "name": "Example University",
                "institutional_gpa": 3.6,
                "institutional_earned": 25.0,
                "total_earned": 113.0,
                "gpa_as_of": "2026-07-12",
                "degree": "Bachelor of Science",
                "major": "Public Health",
                "minor": "General Business",
                "expected_graduation_year": 2027,
                "degree_status": "in progress",
            }
        ],
    )

    loaded = config.load_profile()
    school = loaded["education_schools"][0]

    assert school["gpa"] == "3.6"
    assert school["units"] == "113"
    assert school["gpa_as_of"] == "2026-07-12"
    assert school["units_scope"] == "total"
    assert school["expected_graduation_year"] == "2027"
    assert school["minor"] == "General Business"
    assert school["education_record_source"] == "structured transcript"
    assert school["education_record_degree_status"] == "in progress"
    assert school["education_record_fields"] == [
        "degree",
        "degree_status",
        "expected_graduation_year",
        "gpa",
        "major",
        "minor",
        "units",
    ]
    assert school["notes"] == "Editable narrative remains."


def test_load_search_config_empty_file_returns_empty_dict(tmp_path, monkeypatch) -> None:
    search_path = tmp_path / "searches.yaml"
    search_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(config, "SEARCH_CONFIG_PATH", search_path)
    monkeypatch.setattr(config, "LEGACY_SEARCH_CONFIG_PATH", tmp_path / "missing.yaml")

    assert config.load_search_config() == {}


def test_normalize_search_config_accepts_simple_user_keys() -> None:
    cfg = config.normalize_search_config(
        {
            "search_city": "Exampletown, UT",
            "job_boards": ["indeed"],
            "search_terms": ["front desk part time"],
            "nearby_locations": ["Exampletown", "north Exampletown"],
            "reject_locations": ["ogden", "salt lake city"],
            "target_titles": ["front desk"],
            "avoid_titles": ["manager"],
            "require_part_time": True,
            "max_hours_per_week": 15,
        }
    )

    assert cfg["locations"] == [{"label": "Exampletown, UT", "location": "Exampletown, UT"}]
    assert cfg["queries"] == [{"query": "front desk part time", "tier": 1}]
    assert cfg["sites"] == ["indeed"]
    assert cfg["boards"] == ["indeed"]
    assert cfg["location_accept"] == ["Exampletown", "north Exampletown"]
    assert cfg["location"]["reject_patterns"] == ["ogden", "salt lake city"]
    assert cfg["include_titles"] == ["front desk"]
    assert cfg["exclude_titles"] == ["manager"]
    # Legacy aliases still normalize, but new configs/editor saves do not need
    # these customer-service-specific keys.
    assert cfg["customer_service_require_part_time"] is True
    assert cfg["customer_service_max_hours_per_week"] == 15


def test_validate_search_config_warns_for_legacy_aliases_without_breaking() -> None:
    report = config.validate_search_config(
        {
            "search_city": "Exampletown, UT",
            "job_boards": ["indeed"],
            "search_terms": ["front desk part time"],
            "nearby_locations": ["Exampletown"],
            "reject_locations": ["ogden"],
            "target_titles": ["front desk"],
            "avoid_titles": ["manager"],
            "avoid_keywords": ["commission only"],
            "trusted_sites": ["usu.edu"],
            "part_time_titles": ["customer service"],
        }
    )

    assert report["passed"]
    assert "job_boards is a legacy searches.yaml key; prefer boards" in report["warnings"]
    assert "search_terms is a legacy searches.yaml key; prefer queries" in report["warnings"]
    assert "nearby_locations is a legacy searches.yaml key; prefer locations" in report["warnings"]
    assert "target_titles is a legacy searches.yaml key; prefer include_titles" in report["warnings"]


def test_validate_search_config_does_not_warn_for_normalized_sites_alias() -> None:
    raw_cfg = {
        "queries": [{"query": "help desk", "tier": 1}],
        "locations": [{"location": "Exampletown, UT"}],
        "boards": ["indeed", "linkedin"],
    }
    report = config.validate_search_config(config.normalize_search_config(raw_cfg))

    assert report["passed"]
    assert "sites is a legacy searches.yaml key; prefer boards" not in report["warnings"]


def test_validate_search_config_accepts_target_families_and_query_location_scopes() -> None:
    report = config.validate_search_config(
        {
            "target_families": [
                {"name": "IT support", "priority": 1},
                {"name": "health information", "priority": 2},
            ],
            "queries": [
                {"query": "help desk", "tier": 1, "location_labels": ["Exampletown, UT", "Remote"]},
            ],
            "locations": [
                {"location": "Exampletown, UT"},
                {"label": "Remote", "location": "Remote", "remote": True},
            ],
        }
    )

    assert report["passed"]
    assert report["errors"] == []


def test_validate_search_config_rejects_invalid_target_families_and_unknown_location_scope() -> None:
    report = config.validate_search_config(
        {
            "target_families": [
                {"name": "", "priority": 1},
                {"name": "IT support", "priority": 4},
            ],
            "queries": [
                {"query": "help desk", "tier": 1, "location_labels": ["Nowhere"]},
            ],
            "locations": [{"location": "Exampletown, UT"}],
        }
    )

    assert not report["passed"]
    assert "target_families[0] needs a name" in report["errors"]
    assert "target_families[1].priority must be an integer from 1 to 3" in report["errors"]
    assert "queries[0].location_labels contains unknown location 'Nowhere'" in report["errors"]


def test_validate_search_config_rejects_unknown_preferred_schedule() -> None:
    report = config.validate_search_config(
        {
            "preferred_schedule": "weekends-maybe",
            "queries": [{"query": "help desk", "tier": 1}],
            "locations": [{"location": "Exampletown, UT"}],
        }
    )

    assert not report["passed"]
    assert "preferred_schedule must be one of: any, full_time, part_time" in report["errors"]


def test_validate_search_config_rejects_invalid_market_policies() -> None:
    report = config.validate_search_config(
        {
            "queries": [{"query": "help desk"}],
            "locations": [{"label": "Current market", "location": "Exampletown, YY"}],
            "default_market_label": "Unknown market",
            "market_policies": {
                "Unknown market": {
                    "preferred_schedule": "weekends",
                    "require_part_time": "sometimes",
                    "application_mode": "automatic",
                }
            },
        }
    )

    assert not report["passed"]
    assert "default_market_label must name a configured location label" in report["errors"]
    assert "market_policies contains unknown location label 'Unknown market'" in report["errors"]
    assert "market_policies.Unknown market.preferred_schedule is invalid" in report["errors"]
    assert "market_policies.Unknown market.require_part_time must be boolean" in report["errors"]
    assert "market_policies.Unknown market.application_mode is invalid" in report["errors"]


def test_shipped_search_example_uses_locations_without_default_manual_filters() -> None:
    example_path = config.CONFIG_DIR / "searches.example.yaml"
    cfg = yaml.safe_load(example_path.read_text(encoding="utf-8"))

    assert cfg["locations"]
    assert "location" not in cfg
    assert "exclude_titles" not in cfg
    assert "excluded_keywords" not in cfg
    assert "customer_service_title_terms" not in cfg
    assert "customer_service_require_part_time" not in cfg
    assert "customer_service_max_hours_per_week" not in cfg


def test_normalize_profile_accepts_flat_skills_without_job_search_aliases() -> None:
    profile = config._normalize_profile(
        {
            "skills": ["customer service", "data entry"],
            "job_search": {
                "target": "easy part-time work",
                "schedule": "5-15 hours per week",
                "preferred_roles": ["front desk", "student assistant"],
            },
            "availability": {"available_for_part_time": "5-15 hours per week"},
            "experience_inference": "legacy profile policy",
            "experience": {
                "target_role": "outdated search role",
                "target_roles": {"tier1": "front desk"},
                "years_of_experience_total": "99",
                "years_of_experience_customer_service": "2",
            },
            "compensation": {"hourly_expectation": "Use posted hourly range."},
        }
    )

    assert "job_search" not in profile
    assert profile["skills_boundary"] == {"skills": ["customer service", "data entry"]}
    assert "target_role" not in profile["experience"]
    assert "target_roles" not in profile["experience"]
    assert "years_of_experience_total" not in profile["experience"]
    assert profile["experience"]["years_of_experience_customer_service"] == "2"
    assert "availability" not in profile
    assert "experience_inference" not in profile
    assert profile["compensation"]["part_time_hourly_expectation"] == "Use posted hourly range."


def test_coursework_summary_keeps_recent_and_search_relevant_courses_without_raw_text() -> None:
    coursework = [
        {
            "school": "Example University",
            "course_title": f"General Elective {year}",
            "term": f"{year} Fall",
            "status": "Completed",
            "credits": 3,
            "raw_text": f"private transcript row {year}",
        }
        for year in range(2010, 2025)
    ]
    coursework.extend(
        [
            {
                "school": "Example University",
                "course_title": "Introduction to Information Systems",
                "term": "2011 Spring",
                "subject_area": "Information Technology",
                "status": "Completed",
                "credits": 3,
            },
            {
                "school": "Example University",
                "course_title": "Medical Terminology",
                "term": "2012 Summer",
                "subject_area": "Health",
                "status": "Completed",
                "credits": 3,
            },
            {
                "school": "Example University",
                "course_title": "Current Epidemiology",
                "term": "2026 Spring",
                "subject_area": "Public Health",
                "status": "Completed",
                "credits": 3,
            },
        ]
    )

    summary = config._summarize_coursework(
        coursework,
        search_config={
            "target_families": [
                {"name": "IT support", "priority": 1},
                {"name": "health information", "priority": 1},
            ]
        },
    )

    assert len(summary) == 1
    assert "Current Epidemiology" in summary[0]
    assert "Introduction to Information Systems" in summary[0]
    assert "Medical Terminology" in summary[0]
    assert "private transcript" not in summary[0]
    assert len(summary[0].split(": ", 1)[1].split(", ")) <= 12


def test_coursework_context_requires_verified_completion_and_finite_positive_credits() -> None:
    base = {
        "school": "Example University",
        "subject_area": "Information Systems",
    }
    coursework = [
        base | {"course_title": "Verified Course", "status": "Completed", "credits": 3},
        base | {"course_title": "Unknown Status", "credits": 3},
        base | {"course_title": "Unknown Credits", "status": "Completed"},
        base | {"course_title": "Infinite Credits", "status": "Completed", "credits": "inf"},
        base | {"course_title": "In Progress", "status": "In progress", "credits": 3},
    ]

    summary = config._summarize_coursework(coursework)

    assert summary == ["Example University: Verified Course [Information Systems]"]


def test_coursework_context_validation_fails_closed_for_malformed_policy() -> None:
    base = {
        "queries": [{"query": "help desk"}],
        "locations": [{"location": "Exampletown, YY"}],
    }
    malformed = base | {
        "coursework_context": {
            "include_patterns": "information systems",
            "max_per_school": "many",
        }
    }

    report = config.validate_search_config(malformed)
    summary = config._summarize_coursework(
        [
            {
                "school": "Example University",
                "course_title": "Information Systems",
                "status": "Completed",
                "credits": 3,
            }
        ],
        search_config=malformed,
    )

    assert not report["passed"]
    assert "coursework_context.include_patterns must be a list" in report["errors"]
    assert "coursework_context.max_per_school must be an integer from 1 to 24" in report["errors"]
    assert summary == []


def test_v96_bounded_integer_accepts_only_canonical_values() -> None:
    assert config._bounded_integer(1, 1, 24)
    assert config._bounded_integer("24", 1, 24)
    assert not config._bounded_integer(True, 1, 24)
    assert not config._bounded_integer(1.5, 1, 24)
    assert not config._bounded_integer(object(), 1, 24)
    assert not config._bounded_integer("25", 1, 24)


def test_coursework_context_policy_filters_low_value_rows_and_skill_tags() -> None:
    coursework = [
        {
            "school": "Example University",
            "course_title": "Introduction to Information Systems",
            "subject_area": "Information Systems",
            "term": "2021 Fall",
            "status": "Completed",
            "credits": 3,
            "skills": ["information systems", "digital workflows", "academic knowledge"],
        },
        {
            "school": "Example University",
            "course_title": "Epidemiology",
            "subject_area": "Public Health",
            "term": "2026 Spring",
            "status": "Completed",
            "credits": 3,
            "skills": ["public health", "statistics", "wellness"],
        },
        {
            "school": "Example University",
            "course_title": "Swimming",
            "subject_area": "Physical Education",
            "term": "2026 Summer",
            "status": "Completed",
            "credits": 1,
            "skills": ["physical fitness", "discipline"],
        },
        {
            "school": "Example University",
            "course_title": "Music Appreciation",
            "subject_area": "Arts and Humanities",
            "term": "2026 Summer",
            "status": "Completed",
            "credits": 3,
            "skills": ["cultural awareness"],
        },
        {
            "school": "Example University",
            "course_title": "Online Orientation",
            "subject_area": "Orientation",
            "term": "2026 Summer",
            "status": "Non-credit",
            "credits": 0,
            "skills": ["orientation"],
        },
    ]
    search_config = {
        "target_families": [
            {"name": "IT support", "priority": 1},
            {"name": "public health data", "priority": 2},
        ],
        "coursework_context": {
            "include_patterns": ["information systems", "public health"],
            "exclude_patterns": ["swimming", "music appreciation", "orientation"],
            "skill_exclude_patterns": ["academic knowledge", "wellness"],
            "max_per_school": 4,
        },
    }

    summary = config._summarize_coursework(coursework, search_config=search_config)
    skills = config._summarize_coursework_skills(coursework, search_config=search_config)

    assert summary == [
        "Example University: Epidemiology [Public Health], Introduction to Information Systems [Information Systems]"
    ]
    assert skills == ["Example University: digital workflows, information systems, public health, statistics"]


def test_get_apply_timeout_defaults_to_bounded_timeout(monkeypatch) -> None:
    monkeypatch.delenv("DIVAPPLY_APPLY_TIMEOUT", raising=False)
    monkeypatch.delenv("APPLYPILOT_APPLY_TIMEOUT", raising=False)

    assert config.get_apply_timeout() == 2700


def test_get_apply_timeout_uses_env_with_floor(monkeypatch) -> None:
    monkeypatch.setenv("DIVAPPLY_APPLY_TIMEOUT", "10")

    assert config.get_apply_timeout() == 30

    monkeypatch.setenv("DIVAPPLY_APPLY_TIMEOUT", "120")

    assert config.get_apply_timeout() == 120

    monkeypatch.setenv("DIVAPPLY_APPLY_TIMEOUT", "off")

    assert config.get_apply_timeout() is None


def test_gmail_mcp_is_disabled_and_legacy_opt_in_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("DIVAPPLY_ENABLE_GMAIL_MCP", raising=False)
    assert config.gmail_mcp_enabled() is False

    monkeypatch.setenv("DIVAPPLY_ENABLE_GMAIL_MCP", "true")
    with pytest.raises(RuntimeError, match="Gmail MCP is unavailable"):
        config.gmail_mcp_enabled()

    monkeypatch.setenv("DIVAPPLY_ENABLE_GMAIL_MCP", "invalid")
    assert config.gmail_mcp_enabled() is False


def test_log_retention_days_defaults_and_validates_env(monkeypatch) -> None:
    monkeypatch.delenv("DIVAPPLY_LOG_RETENTION_DAYS", raising=False)
    assert config.get_log_retention_days() == 30

    monkeypatch.setenv("DIVAPPLY_LOG_RETENTION_DAYS", "7")
    assert config.get_log_retention_days() == 7

    monkeypatch.setenv("DIVAPPLY_LOG_RETENTION_DAYS", "0")
    assert config.get_log_retention_days() == 0

    monkeypatch.setenv("DIVAPPLY_LOG_RETENTION_DAYS", "invalid")
    with pytest.raises(ValueError, match="DIVAPPLY_LOG_RETENTION_DAYS"):
        config.get_log_retention_days()
