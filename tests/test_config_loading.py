from __future__ import annotations

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
    assert cfg["customer_service_require_part_time"] is True
    assert cfg["customer_service_max_hours_per_week"] == 15


def test_normalize_profile_accepts_flat_skills_and_job_search() -> None:
    profile = config._normalize_profile(
        {
            "skills": ["customer service", "data entry"],
            "job_search": {
                "target": "easy part-time work",
                "schedule": "5-15 hours per week",
                "preferred_roles": ["front desk", "student assistant"],
            },
            "compensation": {"hourly_expectation": "Use posted hourly range."},
        }
    )

    assert profile["skills_boundary"] == {"skills": ["customer service", "data entry"]}
    assert profile["experience"]["target_role"] == "easy part-time work"
    assert profile["experience"]["target_roles"]["tier1"] == "front desk"
    assert profile["availability"]["available_for_part_time"] == "5-15 hours per week"
    assert profile["compensation"]["part_time_hourly_expectation"] == "Use posted hourly range."
