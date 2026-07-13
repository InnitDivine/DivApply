from __future__ import annotations

import json

import yaml

from divapply import editor


def test_render_editor_shows_simple_setup_controls() -> None:
    html = editor.render_editor(
        {
            "personal": {"full_name": "Jordan Alex Example", "email": "jordan@example.com"},
            "compensation": {
                "target_hourly_rate": "15",
            },
            "skills": ["customer service", "front desk"],
            "work_history": [
                {
                    "title": "Front Desk Associate",
                    "company": "Example Gym",
                    "dates": "2024 to 2025",
                    "tasks": "Customer service and facility support.",
                }
            ],
            "education_schools": [
                {
                    "school": "Example College",
                    "degree": "Associate",
                    "major": "General Studies",
                    "start_year": "2022",
                    "end_year": "2024",
                    "gpa": "3.2",
                    "notes": "Graduated.",
                }
            ],
            "certifications": [{"name": "CPR", "issuer": "AHA", "status": "Active", "expires": "2027"}],
            "references": [
                {
                    "name": "Casey Supervisor",
                    "title": "Fitness Director",
                    "phone": "(555) 010-0102",
                    "email": "casey@example.com",
                    "address": "Exampletown, ZZ",
                }
            ],
            "resume_facts": {"preserved_projects": ["Home lab"], "real_metrics": ["45 WPM"]},
        },
        {
            "locations": [{"location": "Exampletown, UT", "remote": False}],
            "location": {"accept_patterns": ["Exampletown", "north Exampletown"], "reject_patterns": ["ogden"]},
            "queries": [{"query": "front desk", "tier": 1}],
            "boards": ["indeed", "linkedin"],
            "exclude_titles": ["manager"],
            "defaults": {"results_per_site": 50, "hours_old": 168},
        },
        token="token",
    )

    assert "First name" in html
    assert '<a class="skip-link" href="#settings-form">Skip to settings form</a>' in html
    assert '<form id="settings-form" method="post" action="/save" aria-label="DivApply settings">' in html
    assert 'id="email" name="email" type="email" autocomplete="email"' in html
    assert 'id="phone" name="phone" type="tel" autocomplete="tel"' in html
    assert 'id="linkedin_url" name="linkedin_url" type="url" autocomplete="url"' in html
    assert "min-height: 44px" in html
    assert "Middle name" in html
    assert "Last name" in html
    assert "Email" in html
    assert "Jordan" in html
    assert "Hourly pay target" in html
    assert "Work type" in html
    assert "Skills" in html
    assert "customer service" in html
    assert "Past Jobs" in html
    assert "Front Desk Associate | Example Gym | 2024 to 2025 | Customer service and facility support." in html
    assert "Education" in html
    assert "Example College | Associate | General Studies | 2022 to 2024 | 3.2 | Graduated." in html
    assert "Certifications" in html
    assert "CPR | AHA | Active | 2027" in html
    assert "References" in html
    assert "Casey Supervisor | Fitness Director | (555) 010-0102 | casey@example.com | Exampletown, ZZ" in html
    assert "Projects" in html
    assert "Home lab" in html
    assert "Metrics" in html
    assert "45 WPM" in html
    assert "Search these locations" in html
    assert "Accept postings that mention" in html
    assert "Search for these jobs" in html
    assert "front desk | 1" in html
    assert "indeed" in html
    assert "Leave blank for broad search" in html
    assert "Projected" not in html
    assert "Weekly" not in html
    assert "Save Settings" in html


def test_render_editor_escapes_profile_search_values_and_csrf_token() -> None:
    html = editor.render_editor(
        {
            "personal": {
                "first_name": '<script>alert("profile")</script>',
                "email": 'bad" onfocus="alert(1)',
            },
            "skills": ['customer <service>'],
        },
        {
            "queries": [{"query": '<img src=x onerror=alert(1)>', "tier": 1}],
            "locations": [{"location": 'Exampletown "><script>alert(1)</script>', "remote": False}],
        },
        token='token" autofocus onfocus="alert(1)',
    )

    assert '<script>alert("profile")</script>' not in html
    assert '<img src=x onerror=alert(1)>' not in html
    assert 'token" autofocus onfocus="alert(1)' not in html
    assert "&lt;script&gt;alert(&quot;profile&quot;)&lt;/script&gt;" in html
    assert "customer &lt;service&gt;" in html
    assert "token&quot; autofocus onfocus=&quot;alert(1)" in html


def test_editor_round_trip_preserves_scopes_labels_schedule_and_skill_authority(tmp_path, monkeypatch) -> None:
    profile_path = tmp_path / "profile.json"
    search_path = tmp_path / "searches.yaml"
    profile = {
        "personal": {"full_name": "Jordan Example"},
        "compensation": {"target_hourly_rate": "25"},
        "skills": ["stale flat skill"],
        "skills_boundary": {
            "technical_support": ["Windows troubleshooting"],
            "systems": ["Linux"],
        },
    }
    search = {
        "locations": [
            {"label": "Current market", "location": "Exampletown, ZZ", "remote": False},
            {"label": "Future market", "location": "Sample City, YY", "remote": False},
        ],
        "queries": [
            {
                "query": "part time help desk",
                "tier": 1,
                "location_labels": ["Current market"],
            },
            {
                "query": "IT technician",
                "tier": 1,
                "location_labels": ["Future market"],
            },
        ],
        "boards": ["indeed"],
        "preferred_schedule": "full_time",
        "require_part_time": False,
        "defaults": {"results_per_site": 25, "hours_old": 72},
    }
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    search_path.write_text(yaml.safe_dump(search, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(editor, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(editor, "SEARCH_CONFIG_PATH", search_path)

    values = editor._profile_values(profile, search)

    assert values["skills"] == "Windows troubleshooting\nLinux"
    assert values["schedule_type"] == "full_time"
    assert values["locations"] == (
        "Current market | Exampletown, ZZ | onsite\n"
        "Future market | Sample City, YY | onsite"
    )
    assert values["queries"] == (
        "part time help desk | 1 | Current market\n"
        "IT technician | 1 | Future market"
    )

    editor.save_editor_settings({key: str(value) for key, value in values.items()})
    saved_profile = json.loads(profile_path.read_text(encoding="utf-8"))
    saved_search = yaml.safe_load(search_path.read_text(encoding="utf-8"))

    assert saved_profile["skills"] == ["Windows troubleshooting", "Linux"]
    assert saved_profile["skills_boundary"] == profile["skills_boundary"]
    assert saved_search["locations"] == search["locations"]
    assert saved_search["queries"] == search["queries"]
    assert saved_search["preferred_schedule"] == "full_time"
    assert saved_search["require_part_time"] is False

    values["skills"] = "Windows troubleshooting\nPython"
    values["schedule_type"] = "either"
    editor.save_editor_settings({key: str(value) for key, value in values.items()})
    edited_profile = json.loads(profile_path.read_text(encoding="utf-8"))
    edited_search = yaml.safe_load(search_path.read_text(encoding="utf-8"))

    assert edited_profile["skills"] == ["Windows troubleshooting", "Python"]
    assert edited_profile["skills_boundary"] == {
        "skills": ["Windows troubleshooting", "Python"]
    }
    assert edited_search["preferred_schedule"] == "any"
    assert edited_search["require_part_time"] is False


def test_editor_round_trip_normalizes_legacy_schedule_and_escaped_scope_delimiters(tmp_path, monkeypatch) -> None:
    profile_path = tmp_path / "profile.json"
    search_path = tmp_path / "searches.yaml"
    profile = {"personal": {}, "compensation": {"target_hourly_rate": 20}}
    search = {
        "locations": [
            {
                "label": "Future | market; cohort",
                "location": "Sample | City, ZZ",
                "remote": False,
            }
        ],
        "queries": [
            {
                "query": "IT | support",
                "tier": 1,
                "location_labels": ["Future | market; cohort"],
            }
        ],
        "customer_service_require_part_time": True,
        "customer_service_max_hours_per_week": 24,
        "max_hours_per_week": 24,
    }
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    search_path.write_text(yaml.safe_dump(search, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(editor, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(editor, "SEARCH_CONFIG_PATH", search_path)

    values = editor._profile_values(profile, search)

    assert values["schedule_type"] == "part_time"
    assert "%7C" in values["locations"] and "%3B" in values["locations"]
    assert "%7C" in values["queries"] and "%3B" in values["queries"]

    editor.save_editor_settings({key: str(value) for key, value in values.items()})
    saved = yaml.safe_load(search_path.read_text(encoding="utf-8"))

    assert saved["locations"] == search["locations"]
    assert saved["queries"] == search["queries"]
    assert saved["require_part_time"] is True
    assert saved["preferred_schedule"] == "part_time"
    assert "customer_service_require_part_time" not in saved
    assert "customer_service_max_hours_per_week" not in saved
    assert "max_hours_per_week" not in saved


def test_save_editor_settings_updates_profile_and_search(tmp_path, monkeypatch) -> None:
    profile_path = tmp_path / "profile.json"
    search_path = tmp_path / "searches.yaml"
    profile_path.write_text(
        json.dumps(
            {
                "personal": {"full_name": "Old Name"},
                "job_search": {"target": "old", "schedule": "old"},
                "compensation": {"salary_currency": "USD"},
                "resume_facts": {"preserved_projects": ["Old project"], "real_metrics": ["Old metric"]},
            }
        ),
        encoding="utf-8",
    )
    search_path.write_text("locations:\n  - location: Exampletown, ZZ\n    remote: false\n", encoding="utf-8")

    monkeypatch.setattr(editor, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(editor, "SEARCH_CONFIG_PATH", search_path)

    editor.save_editor_settings(
        {
            "first_name": "Jordan",
            "middle_name": "Alex",
            "last_name": "Example",
            "preferred_name": "Jordan",
            "email": "jordan@example.com",
            "phone": "555-123-4567",
            "address": "100 Example Avenue",
            "city": "Exampletown",
            "province_state": "ZZ",
            "postal_code": "00000",
            "country": "United States",
            "linkedin_url": "https://linkedin.example/jordan",
            "github_url": "https://github.com/example-user",
            "website_url": "https://example.com",
            "target_hourly_rate": "15",
            "skills": "customer service\nfront desk\n",
            "work_history": (
                "Front Desk Associate | Example Gym | 2024 to 2025 | Customer service and facility support.\n"
                "Accounting Assistant | County Office | 2025 | Reconciled deposits.\n"
            ),
            "education": "Example College | Associate | General Studies | 2022 to 2024 | 3.2 | Graduated.\n",
            "certifications": "CPR | AHA | Active | 2027\nFood Handler | State | Active | 2028\n",
            "references": (
                "Morgan Supervisor | Mine Supervisor, Example Mine | (555) 010-0101 | | North Exampletown, ZZ\n"
                "Casey Supervisor | Fitness Director | (555) 010-0102 | casey@example.com | South Exampletown, ZZ\n"
            ),
            "projects": "Home lab\nPortfolio website\n",
            "real_metrics": "45 WPM\n3.2 GPA\n",
            "schedule_type": "part_time",
            "locations": "Exampletown, UT | onsite\nRemote | remote\n",
            "accept_patterns": "Exampletown\nnorth Exampletown\nremote\n",
            "reject_patterns": "ogden\nsalt lake city\n",
            "queries": "front desk | 1\ncashier | 2\n",
            "boards": "indeed\nlinkedin\n",
            "exclude_titles": "manager\nsupervisor\n",
            "include_titles": "",
            "results_per_site": "75",
            "hours_old": "120",
        }
    )

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    search = yaml.safe_load(search_path.read_text(encoding="utf-8"))

    assert profile["personal"]["first_name"] == "Jordan"
    assert profile["personal"]["middle_name"] == "Alex"
    assert profile["personal"]["last_name"] == "Example"
    assert profile["personal"]["full_name"] == "Jordan Alex Example"
    assert profile["personal"]["email"] == "jordan@example.com"
    assert profile["compensation"]["target_hourly_rate"] == "15"
    assert "target_hours_per_week" not in profile["compensation"]
    assert "projected_weekly_income" not in profile["compensation"]
    assert "projected_annual_income" not in profile["compensation"]
    assert profile["compensation"]["salary_expectation"] == "15600"
    assert profile["compensation"]["salary_range_min"] == "15600"
    assert profile["compensation"]["salary_range_max"] == "15600"
    assert "$15/hr" in profile["compensation"]["hourly_expectation"]
    assert "availability" not in profile
    assert "job_search" not in profile
    assert profile["skills"] == ["customer service", "front desk"]
    assert profile["work_history"] == [
        {
            "title": "Front Desk Associate",
            "company": "Example Gym",
            "dates": "2024 to 2025",
            "tasks": "Customer service and facility support.",
        },
        {
            "title": "Accounting Assistant",
            "company": "County Office",
            "dates": "2025",
            "tasks": "Reconciled deposits.",
        },
    ]
    assert profile["education_schools"] == [
        {
            "school": "Example College",
            "degree": "Associate",
            "major": "General Studies",
            "gpa": "3.2",
            "start_year": "2022",
            "end_year": "2024",
            "notes": "Graduated.",
        }
    ]
    assert profile["certifications"] == [
        {"name": "CPR", "issuer": "AHA", "status": "Active", "expires": "2027"},
        {"name": "Food Handler", "issuer": "State", "status": "Active", "expires": "2028"},
    ]
    assert profile["references"] == [
        {
            "name": "Morgan Supervisor",
            "title": "Mine Supervisor, Example Mine",
            "phone": "(555) 010-0101",
            "address": "North Exampletown, ZZ",
        },
        {
            "name": "Casey Supervisor",
            "title": "Fitness Director",
            "phone": "(555) 010-0102",
            "email": "casey@example.com",
            "address": "South Exampletown, ZZ",
        },
    ]
    assert profile["resume_facts"]["preserved_companies"] == ["Example Gym", "County Office"]
    assert profile["resume_facts"]["preserved_school"] == "Example College"
    assert profile["resume_facts"]["preserved_projects"] == ["Home lab", "Portfolio website"]
    assert profile["resume_facts"]["real_metrics"] == ["45 WPM", "3.2 GPA"]
    assert "search_city" not in search
    assert search["locations"] == [
        {"location": "Exampletown, UT", "remote": False},
        {"location": "Remote", "remote": True},
    ]
    assert search["location"]["accept_patterns"] == ["Exampletown", "north Exampletown", "remote"]
    assert search["location"]["reject_patterns"] == ["ogden", "salt lake city"]
    assert search["queries"] == [
        {"query": "front desk", "tier": 1},
        {"query": "cashier", "tier": 2},
    ]
    assert search["boards"] == ["indeed", "linkedin"]
    assert "sites" not in search
    assert search["exclude_titles"] == ["manager", "supervisor"]
    assert "include_titles" not in search
    assert search["defaults"]["results_per_site"] == 75
    assert search["defaults"]["hours_old"] == 120
    assert search["require_part_time"] is True
    assert search["preferred_schedule"] == "part_time"
    assert "customer_service_require_part_time" not in search
    assert "customer_service_max_hours_per_week" not in search


def test_save_editor_settings_preserves_extra_profile_record_fields(tmp_path, monkeypatch) -> None:
    profile_path = tmp_path / "profile.json"
    search_path = tmp_path / "searches.yaml"
    profile_path.write_text(
        json.dumps(
            {
                "personal": {},
                "job_search": {},
                "compensation": {},
                "work_history": [
                    {
                        "title": "Front Desk Associate",
                        "company": "Example Gym",
                        "dates": "2024 to 2025",
                        "tasks": "Customer service.",
                        "location": "Exampletown, ZZ",
                    }
                ],
                "education_schools": [
                    {
                        "school": "Example College",
                        "city_state": "Exampletown, ZZ",
                        "degree": "Associate",
                        "major": "General Studies",
                        "degree_received": True,
                        "units": "60",
                        "units_type": "Semester",
                        "gpa": "3.2",
                        "start_year": "2022",
                        "end_year": "2024",
                        "notes": "Graduated.",
                    }
                ],
                "certifications": [
                    {
                        "name": "CPR",
                        "issuer": "AHA",
                        "number": "ABC123",
                        "status": "Active",
                        "expires": "2027",
                    }
                ],
                "references": [
                    {
                        "name": "Casey Supervisor",
                        "title": "Fitness Director",
                        "phone": "(555) 010-0102",
                        "email": "casey@example.com",
                        "address": "Exampletown, ZZ",
                        "relationship": "Former supervisor",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    search_path.write_text("locations:\n  - location: Exampletown, UT\n    remote: false\n", encoding="utf-8")

    monkeypatch.setattr(editor, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(editor, "SEARCH_CONFIG_PATH", search_path)

    editor.save_editor_settings(
        {
            "target_hourly_rate": "15",
            "schedule_type": "part_time",
            "work_history": "Front Desk Associate | Example Gym | 2024 to 2026 | Updated tasks.\n",
            "education": "Example College | Associate | General Studies | 2022 to 2024 | 3.3 | Updated note.\n",
            "certifications": "CPR | AHA | Active | 2028\n",
            "references": "Casey Supervisor | Fitness Director | (555) 010-0102 | casey@example.com | Exampletown, ZZ\n",
            "locations": "Exampletown, ZZ | onsite\n",
            "boards": "indeed\n",
            "queries": "front desk | 1\n",
            "exclude_titles": "",
            "include_titles": "",
            "accept_patterns": "exampletown\n",
            "reject_patterns": "othertown\n",
            "results_per_site": "50",
            "hours_old": "168",
        }
    )

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["work_history"][0]["tasks"] == "Updated tasks."
    assert profile["work_history"][0]["location"] == "Exampletown, ZZ"
    assert profile["education_schools"][0]["gpa"] == "3.3"
    assert profile["education_schools"][0]["city_state"] == "Exampletown, ZZ"
    assert profile["education_schools"][0]["degree_received"] is True
    assert profile["education_schools"][0]["units"] == "60"
    assert profile["education_schools"][0]["units_type"] == "Semester"
    assert profile["certifications"][0]["expires"] == "2028"
    assert profile["certifications"][0]["number"] == "ABC123"
    assert profile["references"][0]["relationship"] == "Former supervisor"


def test_save_editor_settings_clamps_invalid_numbers_and_query_tiers(tmp_path, monkeypatch) -> None:
    profile_path = tmp_path / "profile.json"
    search_path = tmp_path / "searches.yaml"
    profile_path.write_text("{}", encoding="utf-8")
    search_path.write_text("boards:\n  - indeed\n", encoding="utf-8")

    monkeypatch.setattr(editor, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(editor, "SEARCH_CONFIG_PATH", search_path)

    editor.save_editor_settings(
        {
            "target_hourly_rate": "-25",
            "schedule_type": "side_hustle",
            "queries": "too high | 99\ntoo low | -2\nnot numeric | senior\nplain query\n",
            "boards": "",
            "locations": "",
            "results_per_site": "0",
            "hours_old": "not-a-number",
        }
    )

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    search = yaml.safe_load(search_path.read_text(encoding="utf-8"))

    assert profile["compensation"]["target_hourly_rate"] == "0"
    assert profile["compensation"]["salary_expectation"] == "0"
    assert "20 hours per week" in profile["compensation"]["hourly_expectation"]
    assert search["queries"] == [
        {"query": "too high", "tier": 3},
        {"query": "too low", "tier": 1},
        {"query": "not numeric", "tier": 1},
        {"query": "plain query", "tier": 1},
    ]
    assert search["boards"] == ["indeed"]
    assert search["defaults"]["results_per_site"] == 1
    assert search["defaults"]["hours_old"] == 168
    assert search["require_part_time"] is True
    assert search["preferred_schedule"] == "part_time"
