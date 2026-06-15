from __future__ import annotations

import json

import yaml

from divapply import editor


def test_render_editor_shows_simple_setup_controls() -> None:
    html = editor.render_editor(
        {
            "personal": {"full_name": "Dalton Joseph De Arrieta", "email": "dalton@example.com"},
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
                    "name": "Brett Jaekle",
                    "title": "Fitness Director",
                    "phone": "(775) 830-9270",
                    "email": "brett@example.com",
                    "address": "NV, US",
                }
            ],
            "resume_facts": {"preserved_projects": ["Home lab"], "real_metrics": ["45 WPM"]},
        },
        {
            "locations": [{"location": "Logan, UT", "remote": False}],
            "location": {"accept_patterns": ["logan", "north logan"], "reject_patterns": ["ogden"]},
            "queries": [{"query": "front desk", "tier": 1}],
            "boards": ["indeed", "linkedin"],
            "exclude_titles": ["manager"],
            "defaults": {"results_per_site": 50, "hours_old": 168},
        },
        token="token",
    )

    assert "First name" in html
    assert "Middle name" in html
    assert "Last name" in html
    assert "Email" in html
    assert "Dalton" in html
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
    assert "Brett Jaekle | Fitness Director | (775) 830-9270 | brett@example.com | NV, US" in html
    assert "Projects" in html
    assert "Home lab" in html
    assert "Metrics" in html
    assert "45 WPM" in html
    assert "Search these locations" in html
    assert "Accept postings that mention" in html
    assert "Search for these jobs" in html
    assert "front desk | 1" in html
    assert "indeed" in html
    assert "Leave blank for ApplyPilot-style broad search" in html
    assert "Projected" not in html
    assert "Weekly" not in html
    assert "Save Settings" in html


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
    search_path.write_text("locations:\n  - location: Logan, UT\n    remote: false\n", encoding="utf-8")

    monkeypatch.setattr(editor, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(editor, "SEARCH_CONFIG_PATH", search_path)

    editor.save_editor_settings(
        {
            "first_name": "Dalton",
            "middle_name": "Joseph",
            "last_name": "De Arrieta",
            "preferred_name": "Dalton",
            "email": "dalton@example.com",
            "phone": "555-123-4567",
            "address": "123 Main St",
            "city": "Logan",
            "province_state": "UT",
            "postal_code": "84341",
            "country": "United States",
            "linkedin_url": "https://linkedin.example/dalton",
            "github_url": "https://github.com/InnitDivine",
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
                "Nate Bennet | Mine Supervisor, Nevada Gold Mines | (775) 397-5034 | | NV, US\n"
                "Brett Jaekle | Fitness Director | (775) 830-9270 | brett@example.com | NV, US\n"
            ),
            "projects": "Home lab\nPortfolio website\n",
            "real_metrics": "45 WPM\n3.2 GPA\n",
            "schedule_type": "part_time",
            "locations": "Logan, UT | onsite\nRemote | remote\n",
            "accept_patterns": "logan\nnorth logan\nremote\n",
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

    assert profile["personal"]["first_name"] == "Dalton"
    assert profile["personal"]["middle_name"] == "Joseph"
    assert profile["personal"]["last_name"] == "De Arrieta"
    assert profile["personal"]["full_name"] == "Dalton Joseph De Arrieta"
    assert profile["personal"]["email"] == "dalton@example.com"
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
            "name": "Nate Bennet",
            "title": "Mine Supervisor, Nevada Gold Mines",
            "phone": "(775) 397-5034",
            "address": "NV, US",
        },
        {
            "name": "Brett Jaekle",
            "title": "Fitness Director",
            "phone": "(775) 830-9270",
            "email": "brett@example.com",
            "address": "NV, US",
        },
    ]
    assert profile["resume_facts"]["preserved_companies"] == ["Example Gym", "County Office"]
    assert profile["resume_facts"]["preserved_school"] == "Example College"
    assert profile["resume_facts"]["preserved_projects"] == ["Home lab", "Portfolio website"]
    assert profile["resume_facts"]["real_metrics"] == ["45 WPM", "3.2 GPA"]
    assert search["search_city"] == "Logan, UT"
    assert search["locations"] == [
        {"location": "Logan, UT", "remote": False},
        {"location": "Remote", "remote": True},
    ]
    assert search["location"]["accept_patterns"] == ["logan", "north logan", "remote"]
    assert search["location"]["reject_patterns"] == ["ogden", "salt lake city"]
    assert search["queries"] == [
        {"query": "front desk", "tier": 1},
        {"query": "cashier", "tier": 2},
    ]
    assert search["boards"] == ["indeed", "linkedin"]
    assert search["sites"] == ["indeed", "linkedin"]
    assert search["exclude_titles"] == ["manager", "supervisor"]
    assert "include_titles" not in search
    assert search["defaults"]["results_per_site"] == 75
    assert search["defaults"]["hours_old"] == 120
    assert search["require_part_time"] is True
    assert search["customer_service_require_part_time"] is True
    assert search["customer_service_max_hours_per_week"] == 20


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
                        "location": "Logan, UT",
                    }
                ],
                "education_schools": [
                    {
                        "school": "Example College",
                        "city_state": "Logan, UT",
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
                        "name": "Brett Jaekle",
                        "title": "Fitness Director",
                        "phone": "(775) 830-9270",
                        "email": "brett@example.com",
                        "address": "NV, US",
                        "relationship": "Former supervisor",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    search_path.write_text("locations:\n  - location: Logan, UT\n    remote: false\n", encoding="utf-8")

    monkeypatch.setattr(editor, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(editor, "SEARCH_CONFIG_PATH", search_path)

    editor.save_editor_settings(
        {
            "target_hourly_rate": "15",
            "schedule_type": "part_time",
            "work_history": "Front Desk Associate | Example Gym | 2024 to 2026 | Updated tasks.\n",
            "education": "Example College | Associate | General Studies | 2022 to 2024 | 3.3 | Updated note.\n",
            "certifications": "CPR | AHA | Active | 2028\n",
            "references": "Brett Jaekle | Fitness Director | (775) 830-9270 | brett@example.com | NV, US\n",
            "locations": "Logan, UT | onsite\n",
            "boards": "indeed\n",
            "queries": "front desk | 1\n",
            "exclude_titles": "",
            "include_titles": "",
            "accept_patterns": "logan\n",
            "reject_patterns": "ogden\n",
            "results_per_site": "50",
            "hours_old": "168",
        }
    )

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["work_history"][0]["tasks"] == "Updated tasks."
    assert profile["work_history"][0]["location"] == "Logan, UT"
    assert profile["education_schools"][0]["gpa"] == "3.3"
    assert profile["education_schools"][0]["city_state"] == "Logan, UT"
    assert profile["education_schools"][0]["degree_received"] is True
    assert profile["education_schools"][0]["units"] == "60"
    assert profile["education_schools"][0]["units_type"] == "Semester"
    assert profile["certifications"][0]["expires"] == "2028"
    assert profile["certifications"][0]["number"] == "ABC123"
    assert profile["references"][0]["relationship"] == "Former supervisor"
