from __future__ import annotations

import yaml

from divapply import config


def test_load_search_config_empty_file_returns_empty_dict(tmp_path, monkeypatch) -> None:
    search_path = tmp_path / "searches.yaml"
    search_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(config, "SEARCH_CONFIG_PATH", search_path)
    monkeypatch.setattr(config, "LEGACY_SEARCH_CONFIG_PATH", tmp_path / "missing.yaml")

    assert config.load_search_config() == {}


def test_normalize_search_config_accepts_simple_user_keys() -> None:
    cfg = config.normalize_search_config(
        {
            "search_city": "Logan, UT",
            "job_boards": ["indeed"],
            "search_terms": ["front desk part time"],
            "nearby_locations": ["logan", "north logan"],
            "reject_locations": ["ogden", "salt lake city"],
            "target_titles": ["front desk"],
            "avoid_titles": ["manager"],
            "require_part_time": True,
            "max_hours_per_week": 15,
        }
    )

    assert cfg["locations"] == [{"label": "Logan, UT", "location": "Logan, UT"}]
    assert cfg["queries"] == [{"query": "front desk part time", "tier": 1}]
    assert cfg["sites"] == ["indeed"]
    assert cfg["boards"] == ["indeed"]
    assert cfg["location_accept"] == ["logan", "north logan"]
    assert cfg["location"]["reject_patterns"] == ["ogden", "salt lake city"]
    assert cfg["include_titles"] == ["front desk"]
    assert cfg["exclude_titles"] == ["manager"]
    # Legacy aliases still normalize, but new configs/editor saves do not need
    # these customer-service-specific keys.
    assert cfg["customer_service_require_part_time"] is True
    assert cfg["customer_service_max_hours_per_week"] == 15


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


def test_get_apply_timeout_defaults_to_no_timeout(monkeypatch) -> None:
    monkeypatch.delenv("DIVAPPLY_APPLY_TIMEOUT", raising=False)
    monkeypatch.delenv("APPLYPILOT_APPLY_TIMEOUT", raising=False)

    assert config.get_apply_timeout() is None


def test_get_apply_timeout_uses_env_with_floor(monkeypatch) -> None:
    monkeypatch.setenv("DIVAPPLY_APPLY_TIMEOUT", "10")

    assert config.get_apply_timeout() == 30

    monkeypatch.setenv("DIVAPPLY_APPLY_TIMEOUT", "120")

    assert config.get_apply_timeout() == 120

    monkeypatch.setenv("DIVAPPLY_APPLY_TIMEOUT", "off")

    assert config.get_apply_timeout() is None
