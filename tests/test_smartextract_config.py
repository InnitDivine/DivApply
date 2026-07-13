from __future__ import annotations

from divapply import config
from divapply.database import close_connection, init_db
from divapply.discovery import smartextract


def test_smartextract_site_loader_treats_empty_yaml_as_no_sites(tmp_path, monkeypatch) -> None:
    user_config = tmp_path / "user"
    user_config.mkdir()
    (user_config / "sites.yaml").write_text("", encoding="utf-8")

    monkeypatch.setattr(config, "USER_CONFIG_DIR", user_config)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "package")

    assert smartextract.load_sites() == []


def test_smartextract_site_loader_applies_explicit_verification_default(tmp_path, monkeypatch) -> None:
    user_config = tmp_path / "user"
    user_config.mkdir()
    (user_config / "sites.yaml").write_text(
        "default_source_verification: official\n"
        "sites:\n"
        "  - name: Example Careers\n"
        "    url: https://jobs.example.com\n"
        "    type: static\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "USER_CONFIG_DIR", user_config)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "package")

    assert smartextract.load_sites()[0]["source_verification"] == "official"


def test_smartextract_stores_company_for_direct_site_jobs(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)

    smartextract._store_jobs_filtered(
        conn,
        [
            {
                "url": "https://Exampletownutah.applicantpro.com/jobs/1",
                "title": "IT Support Technician",
                "company": "City of Exampletown",
                "location": "Exampletown, UT",
                "description": "Local IT support role",
            }
        ],
        site="City of Exampletown",
        strategy="unit",
        accept_locs=["Exampletown"],
        reject_locs=[],
        filter_rules={},
        market_label="Current market",
        search_query="part time IT support",
        application_mode="active",
        source_verification="official",
    )

    row = conn.execute(
        "SELECT company, market_label, search_query, application_mode, source_verification, "
        "official_url_verified_at FROM jobs WHERE url = ?",
        ("https://Exampletownutah.applicantpro.com/jobs/1",),
    ).fetchone()

    assert row["company"] == "City of Exampletown"
    assert row["market_label"] == "Current market"
    assert row["search_query"] == "part time IT support"
    assert row["application_mode"] == "active"
    assert row["source_verification"] == "official"
    assert row["official_url_verified_at"]
    close_connection(db_path)


def test_official_refresh_promotes_existing_manual_row_but_unverified_refresh_cannot(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    url = "https://jobs.example.com/official/1"
    conn.execute(
        "INSERT INTO jobs (url, title, location, strategy, discovered_at, application_mode, source_verification, "
        "full_description, fit_score, score_reasoning, matched_skills, tailored_resume_path, cover_letter_path) "
        "VALUES (?, ?, ?, 'manual_url', '2026-01-01', 'manual_review', 'unknown', ?, 8, ?, ?, ?, ?)",
        (
            url,
            "Old title",
            "Exampletown, UT",
            "Stale manual description",
            "Stale score",
            '["stale"]',
            "stale-resume.pdf",
            "stale-cover.pdf",
        ),
    )
    conn.commit()

    smartextract._store_jobs_filtered(
        conn,
        [{"url": url, "title": "Verified IT Assistant", "location": "Exampletown, UT"}],
        site="Official Employer",
        strategy="official_feed",
        accept_locs=["Exampletown"],
        reject_locs=[],
        market_label="Current market",
        application_mode="active",
        source_verification="official",
    )
    promoted = conn.execute(
        "SELECT title, application_mode, source_verification, official_url_verified_at, full_description, "
        "fit_score, score_reasoning, matched_skills, tailored_resume_path, cover_letter_path "
        "FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert promoted["title"] == "Verified IT Assistant"
    assert promoted["application_mode"] == "active"
    assert promoted["source_verification"] == "official"
    assert promoted["official_url_verified_at"]
    assert promoted["full_description"] is None
    assert promoted["fit_score"] is None
    assert promoted["score_reasoning"] is None
    assert promoted["matched_skills"] is None
    assert promoted["tailored_resume_path"] is None
    assert promoted["cover_letter_path"] is None

    smartextract._store_jobs_filtered(
        conn,
        [{"url": url, "title": "Aggregator overwrite", "location": "Exampletown, UT"}],
        site="Aggregator",
        strategy="aggregator",
        accept_locs=["Exampletown"],
        reject_locs=[],
        market_label="Current market",
        application_mode="active",
        source_verification="unverified_aggregator",
    )
    preserved = conn.execute(
        "SELECT title, application_mode, source_verification FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert dict(preserved) == {
        "title": "Verified IT Assistant",
        "application_mode": "active",
        "source_verification": "official",
    }
    close_connection(db_path)


def test_unchanged_official_refresh_preserves_unapplied_score_and_documents(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    url = "https://jobs.example.com/official/unchanged"
    conn.execute(
        "INSERT INTO jobs (url, title, company, description, location, site, strategy, discovered_at, market_label, "
        "application_mode, source_verification, application_url, full_description, detail_scraped_at, "
        "fit_score, score_reasoning, tailored_resume_path, cover_letter_path) "
        "VALUES (?, 'IT Assistant', 'Official Employer', 'Listing snippet', 'Exampletown, UT', "
        "'Official Employer', 'official_feed', '2026-01-01', 'Current market', 'active', 'official', ?, "
        "'Verified enriched description', '2026-01-01', 8, 'Keep score', ?, ?)",
        (url, url, "keep-resume.pdf", "keep-cover.pdf"),
    )
    conn.commit()

    smartextract._store_jobs_filtered(
        conn,
        [
            {
                "url": url,
                "title": "IT Assistant",
                "company": "Official Employer",
                "description": "Listing snippet",
                "location": "Exampletown, UT",
            }
        ],
        site="Official Employer",
        strategy="official_feed",
        accept_locs=["Exampletown"],
        reject_locs=[],
        market_label="Current market",
        application_mode="active",
        source_verification="official",
    )

    row = conn.execute(
        "SELECT full_description, fit_score, score_reasoning, tailored_resume_path, cover_letter_path "
        "FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert dict(row) == {
        "full_description": "Verified enriched description",
        "fit_score": 8,
        "score_reasoning": "Keep score",
        "tailored_resume_path": "keep-resume.pdf",
        "cover_letter_path": "keep-cover.pdf",
    }
    close_connection(db_path)


def test_build_scrape_targets_honors_query_location_scopes() -> None:
    sites = [
        {
            "name": "Example Board",
            "type": "search",
            "url": "https://jobs.example.com/search?q={query_encoded}&l={location_encoded}",
        }
    ]
    search_cfg = {
        "queries": [
            {"query": "part time help desk", "location_labels": ["Current market"]},
            {"query": "IT technician", "location_labels": ["Future market"]},
        ],
        "locations": [
            {"label": "Current market", "location": "Exampletown, YY"},
            {"label": "Future market", "location": "Sample City, ZZ"},
        ],
    }

    targets = smartextract.build_scrape_targets(sites=sites, search_cfg=search_cfg)

    assert [(target["query"], target["location_label"]) for target in targets] == [
        ("part time help desk", "Current market"),
        ("IT technician", "Future market"),
    ]
    assert "Exampletown%2C+YY" in targets[0]["url"]
    assert "Sample+City%2C+ZZ" in targets[1]["url"]


def test_greenhouse_target_uses_deterministic_adapter() -> None:
    targets = smartextract.build_scrape_targets(
        sites=[
            {
                "name": "Example Employer",
                "url": "https://job-boards.greenhouse.io/exampleboard",
                "type": "static",
                "source_verification": "official",
            }
        ],
        search_cfg={},
    )

    assert targets[0]["adapter"] == "greenhouse"


def test_greenhouse_api_extracts_full_official_description(monkeypatch) -> None:
    class Response:
        def json(self):
            return {
                "jobs": [
                    {
                        "title": "IT Support Specialist",
                        "absolute_url": "https://job-boards.greenhouse.io/exampleboard/jobs/1",
                        "location": {"name": "Remote, US"},
                        "content": "&lt;p&gt;Part-time role supporting systems and users.&lt;/p&gt;",
                    },
                    {
                        "title": "Hostile redirect",
                        "absolute_url": "https://attacker.example/jobs/2",
                        "location": {"name": "Remote, US"},
                        "content": "<p>Do not trust this row.</p>",
                    }
                ]
            }

    monkeypatch.setattr(smartextract, "validate_external_url", lambda url, **kwargs: url)
    monkeypatch.setattr(smartextract, "_fetch_job_page", lambda *args, **kwargs: Response())

    result = smartextract._run_greenhouse_board(
        "Example Employer",
        "https://job-boards.greenhouse.io/exampleboard",
    )

    assert result["status"] == "PASS"
    assert result["strategy"] == "greenhouse_api"
    assert result["total"] == 1
    assert result["jobs"][0]["full_description"] == "Part-time role supporting systems and users."
    assert "<p>" not in result["jobs"][0]["full_description"]
