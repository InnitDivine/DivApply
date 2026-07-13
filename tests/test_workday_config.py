from __future__ import annotations

import yaml

from divapply import config
from divapply.discovery import workday


def test_workday_employer_loader_uses_user_config_override(tmp_path, monkeypatch) -> None:
    user_config = tmp_path / "user"
    package_config = tmp_path / "package"
    user_config.mkdir()
    package_config.mkdir()

    (user_config / "employers.yaml").write_text("employers: {}\n", encoding="utf-8")
    (package_config / "employers.yaml").write_text(
        yaml.safe_dump(
            {
                "employers": {
                    "intel": {
                        "name": "Intel (Folsom CA)",
                        "tenant": "intel",
                        "site_id": "External",
                        "base_url": "https://intel.wd1.myworkdayjobs.com",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "USER_CONFIG_DIR", user_config)
    monkeypatch.setattr(config, "CONFIG_DIR", package_config)

    assert workday.load_employers() == {}


def test_workday_discovery_empty_registry_is_clean_skip() -> None:
    result = workday.run_workday_discovery(employers={})

    assert result == {
        "status": "skipped",
        "found": 0,
        "new": 0,
        "existing": 0,
        "queries": 0,
    }


def test_workday_employer_loader_treats_empty_yaml_as_empty_registry(tmp_path, monkeypatch) -> None:
    user_config = tmp_path / "user"
    user_config.mkdir()
    (user_config / "employers.yaml").write_text("", encoding="utf-8")

    monkeypatch.setattr(config, "USER_CONFIG_DIR", user_config)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "package")

    assert workday.load_employers() == {}


def test_workday_discovery_scopes_queries_to_labeled_employers(monkeypatch) -> None:
    employers = {
        "current_org": {"name": "Current Org", "location_labels": ["Current market"]},
        "future_org": {"name": "Future Org", "location_labels": ["Future market"]},
    }
    monkeypatch.setattr(
        config,
        "load_search_config",
        lambda: {
            "queries": [
                {"query": "part time help desk", "tier": 1, "location_labels": ["Current market"]},
                {"query": "IT technician", "tier": 1, "location_labels": ["Future market"]},
            ],
            "locations": [
                {"label": "Current market", "location": "Exampletown, YY"},
                {"label": "Future market", "location": "Sample City, ZZ"},
            ],
        },
    )
    calls: list[tuple[str, list[str]]] = []

    def fake_scrape(*, search_text, employers, **_kwargs):
        calls.append((search_text, list(employers)))
        return {"new": 0, "existing": 0, "found": 0}

    monkeypatch.setattr(workday, "scrape_employers", fake_scrape)

    result = workday.run_workday_discovery(employers=employers)

    assert calls == [
        ("part time help desk", ["current_org"]),
        ("IT technician", ["future_org"]),
    ]
    assert result["queries"] == 2
