from __future__ import annotations

import json
from datetime import date

from divapply import config
from divapply.database import archive_job, close_connection, init_db
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


def test_v130_static_source_default_location_fills_only_blank_results() -> None:
    search_cfg = {
        "locations": [{"label": "Future market", "location": "Sample City, ZZ"}],
        "market_policies": {"Future market": {"application_mode": "active"}},
    }
    targets = smartextract.build_scrape_targets(
        sites=[
            {
                "name": "Sample City",
                "type": "static",
                "url": "https://jobs.example.com/careers/sample",
                "source_verification": "official",
                "location_label": "Future market",
                "default_location": "Sample City, ZZ",
            }
        ],
        search_cfg=search_cfg,
    )

    assert targets[0]["location_label"] == "Future market"
    assert targets[0]["default_location"] == "Sample City, ZZ"
    assert targets[0]["application_mode"] == "active"
    jobs = smartextract._apply_target_location_default(
        [
            {"title": "Blank", "location": ""},
            {"title": "Concrete", "location": "Other City, ZZ"},
        ],
        targets[0],
    )
    assert jobs[0]["location"] == "Sample City, ZZ"
    assert jobs[1]["location"] == "Other City, ZZ"


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


def test_v97_phenom_target_uses_explicit_deterministic_adapter() -> None:
    targets = smartextract.build_scrape_targets(
        sites=[
            {
                "name": "Example Health",
                "url": "https://careers.example.com/us/en/search-results?keywords={query_encoded}",
                "type": "search",
                "adapter": "phenom",
                "source_verification": "official",
                "location_labels": ["Destination market"],
            }
        ],
        search_cfg={
            "queries": [
                {
                    "query": "device support technician",
                    "location_labels": ["Destination market"],
                }
            ],
            "locations": [
                {
                    "label": "Destination market",
                    "location": "Example City, ZZ",
                }
            ],
            "market_policies": {
                "Destination market": {"application_mode": "active"},
            },
        },
    )

    assert len(targets) == 1
    assert targets[0]["adapter"] == "phenom"
    assert targets[0]["source_verification"] == "official"
    assert targets[0]["application_mode"] == "active"
    assert "device+support+technician" in targets[0]["url"]


def test_v97_phenom_ddo_extracts_validated_current_jobs(monkeypatch) -> None:
    app_config = {
        "baseUrl": "https://careers.example.com/us/en/",
        "baseDomain": "https://careers.example.com",
        "refNum": "EXAMPLE",
        "pageName": "search-results",
    }
    ddo = {
        "eagerLoadRefineSearch": {
            "status": 200,
            "hits": 1,
            "data": {
                "jobs": [
                    {
                        "jobId": "R-100",
                        "jobSeqNo": "EXAMPLER100EXTERNALENUS",
                        "title": "Device Support Technician I",
                        "location": "Example City, ZZ",
                        "descriptionTeaser": "Support Windows devices, users, and basic network troubleshooting.",
                        "JobSchedule": "Full Time",
                        "scheduledWeeklyHours": "40",
                    }
                ]
            },
        }
    }
    page = (
        "<html><script>var phApp = phApp || "
        f"{json.dumps(app_config)}; phApp.ddo = {json.dumps(ddo)}; phApp.pageName = 'search-results';"
        "</script></html>"
    )

    class Response:
        text = page

    monkeypatch.setattr(smartextract, "validate_external_url", lambda url, **_kwargs: url)
    monkeypatch.setattr(smartextract, "_fetch_job_page", lambda *_args, **_kwargs: Response())

    result = smartextract._run_phenom_search(
        "Example Health",
        "https://careers.example.com/us/en/search-results?keywords=device+support",
    )

    assert result["status"] == "PASS"
    assert result["strategy"] == "phenom_ddo"
    assert result["total"] == 1
    assert result["jobs"] == [
        {
            "url": "https://careers.example.com/us/en/job/R-100/Device-Support-Technician-I",
            "application_url": "https://careers.example.com/us/en/job/R-100/Device-Support-Technician-I",
            "title": "Device Support Technician I",
            "company": "Example Health",
            "location": "Example City, ZZ",
            "description": "Support Windows devices, users, and basic network troubleshooting.",
            "employment_type": "Full Time",
            "hours_per_week": "40",
        }
    ]


def test_v97_official_refresh_reopens_only_synthetic_expired_failure(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    url = "https://careers.example.com/us/en/job/R-100/Device-Support-Technician-I"
    conn.execute(
        "INSERT INTO jobs (url, title, location, strategy, discovered_at, apply_status, apply_error, "
        "apply_attempts, application_mode, source_verification) "
        "VALUES (?, 'Device Support Technician I', 'Example City, ZZ', 'manual_url_inactive', "
        "'2026-07-19', 'failed', 'expired: posting appears inactive', 99, 'manual_review', 'unknown')",
        (url,),
    )
    conn.commit()

    smartextract._store_jobs_filtered(
        conn,
        [
            {
                "url": url,
                "title": "Device Support Technician I",
                "company": "Example Health",
                "location": "Example City, ZZ",
                "description": "Current official listing.",
            }
        ],
        site="Example Health",
        strategy="phenom_ddo",
        accept_locs=["Example City"],
        reject_locs=[],
        market_label="Destination market",
        search_query="device support technician",
        application_mode="active",
        source_verification="official",
    )

    row = conn.execute(
        "SELECT apply_status, apply_error, apply_attempts, application_mode, source_verification "
        "FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    assert dict(row) == {
        "apply_status": None,
        "apply_error": None,
        "apply_attempts": 0,
        "application_mode": "active",
        "source_verification": "official",
    }
    close_connection(db_path)


def test_v102_v105_governmentjobs_adapter_parses_only_same_origin_open_rows(monkeypatch) -> None:
    page = """
    <html><body><div>2 jobs found</div><ul>
      <li class="job-item" data-job-id="52290-1">
        <h3><a class="job-details-link" href="/jobs/52290-1/part-time-dispatcher">Part-Time Dispatcher</a></h3>
        <div class="primaryInfo job-organization">City of Exampletown</div>
        <div class="primaryInfo"><span class="job-location">Exampletown, YY</span></div>
        <div class="primaryInfo">Part-Time Regular | $17.11 - $18.62 Hourly</div>
      </li>
      <li class="job-item" data-job-id="hostile">
        <h3><a class="job-details-link" href="https://attacker.example/jobs/1">Hostile row</a></h3>
        <div class="primaryInfo job-organization">Unknown</div>
        <div class="primaryInfo"><span class="job-location">Exampletown, YY</span></div>
      </li>
    </ul></body></html>
    """

    class Response:
        text = page

    def fake_fetch(_client, _url, *, headers):
        assert headers["User-Agent"]
        return Response()

    monkeypatch.setattr(smartextract, "_fetch_job_page", fake_fetch)

    result = smartextract._run_governmentjobs_search(
        "GovernmentJobs.com",
        "https://www.governmentjobs.com/jobs?keyword=part+time&location=Exampletown%2C+YY",
    )

    assert result["status"] == "PASS"
    assert result["strategy"] == "governmentjobs_html"
    assert result["total"] == 1
    assert result["jobs"] == [
        {
            "url": "https://www.governmentjobs.com/jobs/52290-1/part-time-dispatcher",
            "application_url": "https://www.governmentjobs.com/jobs/52290-1/part-time-dispatcher",
            "title": "Part-Time Dispatcher",
            "company": "City of Exampletown",
            "location": "Exampletown, YY",
            "salary": "$17.11 - $18.62 Hourly",
            "description": "Part-Time Regular | $17.11 - $18.62 Hourly",
            "employment_type": "Part-Time Regular",
            "availability_state": "open",
        }
    ]


def test_v111_governmentjobs_agency_board_fetches_fragment(monkeypatch) -> None:
    landing = """<html><body><div>0 jobs found</div></body></html>"""
    fragment = """
    <ul class="search-results-listing-container">
      <li class="list-item" data-job-id="5386884">
        <h3 class="job-item-link-container">
          <a class="item-details-link" data-department-name="Information Technology"
             href="/careers/examplecity/jobs/5386884/database-analyst-1500">Database Analyst 1500</a>
        </h3>
        <ul class="list-meta">
          <li>Temporary 1500 HR <span>-</span> $37.45 - $57.96 Hourly</li>
          <li class="categories-list">Category: IT and Computers</li>
        </ul>
        <div class="list-entry">Support and protect agency data systems.</div>
      </li>
      <li class="list-item" data-job-id="5386884">
        <h3><a class="item-details-link"
          href="/careers/examplecity/jobs/5386884/database-analyst-1500">Database Analyst 1500</a></h3>
      </li>
    </ul>
    """
    calls: list[tuple[str, dict[str, str]]] = []

    class Response:
        def __init__(self, text: str) -> None:
            self.text = text

    def fake_fetch(_client, url, *, headers):
        calls.append((url, headers))
        if url.endswith("/careers/home/index?agency=examplecity"):
            return Response(fragment)
        return Response(landing)

    monkeypatch.setattr(smartextract, "_fetch_job_page", fake_fetch)

    result = smartextract._run_governmentjobs_search(
        "City of Example",
        "https://www.governmentjobs.com/careers/examplecity",
    )

    assert [call[0] for call in calls] == [
        "https://www.governmentjobs.com/careers/examplecity",
        "https://www.governmentjobs.com/careers/home/index?agency=examplecity",
    ]
    assert calls[1][1]["X-Requested-With"] == "XMLHttpRequest"
    assert calls[1][1]["Referer"] == "https://www.governmentjobs.com/careers/examplecity"
    assert result["status"] == "PASS"
    assert result["total"] == 1
    assert result["jobs"] == [
        {
            "url": "https://www.governmentjobs.com/careers/examplecity/jobs/5386884/database-analyst-1500",
            "application_url": "https://www.governmentjobs.com/careers/examplecity/jobs/5386884/database-analyst-1500",
            "title": "Database Analyst 1500",
            "company": "City of Example",
            "location": "",
            "salary": "$37.45 - $57.96 Hourly",
            "description": "Support and protect agency data systems.",
            "employment_type": "Temporary 1500 HR",
            "availability_state": "open",
        }
    ]


def test_v111_governmentjobs_global_search_zero_is_authoritative(monkeypatch) -> None:
    calls: list[str] = []

    class Response:
        text = "<html><body><div>0 jobs found</div></body></html>"

    def fake_fetch(_client, url, *, headers):
        assert headers["User-Agent"]
        calls.append(url)
        return Response()

    monkeypatch.setattr(smartextract, "_fetch_job_page", fake_fetch)
    url = "https://www.governmentjobs.com/jobs?keyword=analyst&location=Exampletown%2C+YY"

    result = smartextract._run_governmentjobs_search("GovernmentJobs.com", url)

    assert calls == [url]
    assert result["status"] == "PASS"
    assert result["total"] == 0


def test_v102_v105_jobaps_adapter_requires_applyable_same_origin_board_row(monkeypatch) -> None:
    page = """
    <html><body><table>
      <tr>
        <th class="JobTitle">
          <a class="JobTitle" href="https://www.jobapscloud.com/Example/sup/bulpreview.asp?R1=2026&amp;R2=12351&amp;R3=02">Administrative Legal Clerk - Entry</a>
          <input id="rowJobProps_1" value="{&quot;url&quot;:&quot;https://www.jobapscloud.com/Example/sup/bulpreview.asp?R1=2026&amp;R2=12351&amp;R3=02&quot;,&quot;apply&quot;:&quot;https://www.jobapscloud.com/Example/NewRegPages/TermsOfUse.asp?RecruitNum1=2026&amp;RecruitNum2=12351&amp;RecruitNum3=02&quot;,&quot;noapply&quot;:&quot;0&quot;}" />
        </th>
        <td class="Locs">Sample City, ZZ<br/>Example County, ZZ</td>
        <td class="Dept">Sheriff</td>
        <td class="Salary">$23.45 - $29.32/hour</td>
        <td class="Deadline">Continuous</td>
      </tr>
      <tr>
        <th class="JobTitle">
          <a class="JobTitle" href="https://attacker.example/job">Hostile row</a>
          <input id="rowJobProps_2" value="{&quot;url&quot;:&quot;https://attacker.example/job&quot;,&quot;apply&quot;:&quot;https://attacker.example/apply&quot;,&quot;noapply&quot;:&quot;0&quot;}" />
        </th>
      </tr>
    </table></body></html>
    """

    class Response:
        text = page

    def fake_fetch(_client, _url, *, headers):
        assert headers["User-Agent"]
        return Response()

    monkeypatch.setattr(smartextract, "_fetch_job_page", fake_fetch)

    result = smartextract._run_jobaps_board(
        "Example County",
        "https://www.jobapscloud.com/Example/JobBoard.asp",
    )

    assert result["status"] == "PASS"
    assert result["strategy"] == "jobaps_html"
    assert result["total"] == 1
    assert result["jobs"][0]["title"] == "Administrative Legal Clerk - Entry"
    assert result["jobs"][0]["location"] == "Sample City, ZZ Example County, ZZ"
    assert result["jobs"][0]["application_url"].startswith("https://www.jobapscloud.com/Example/")
    assert result["jobs"][0]["availability_state"] == "open"


def test_v103_verified_open_refresh_reopens_legacy_but_not_sticky_archive(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    legacy_url = "https://www.governmentjobs.com/jobs/1/legacy"
    user_url = "https://www.governmentjobs.com/jobs/2/user-dismissed"
    policy_url = "https://www.governmentjobs.com/jobs/3/policy-mismatch"
    conn.executemany(
        "INSERT INTO jobs (url, title, location, archived_at, archive_reason) VALUES (?, ?, ?, ?, ?)",
        [
            (legacy_url, "Legacy role", "Exampletown, YY", "2026-01-01", "legacy"),
            (user_url, "User role", "Exampletown, YY", None, None),
            (policy_url, "Policy role", "Exampletown, YY", None, None),
        ],
    )
    conn.commit()
    assert archive_job(user_url, conn=conn) is True
    assert archive_job(policy_url, conn=conn, reason="policy") is True

    smartextract._store_jobs_filtered(
        conn,
        [
            {
                "url": legacy_url,
                "title": "Legacy role",
                "location": "Exampletown, YY",
                "availability_state": "open",
            },
            {
                "url": user_url,
                "title": "User role",
                "location": "Exampletown, YY",
                "availability_state": "open",
            },
            {
                "url": policy_url,
                "title": "Policy role",
                "location": "Exampletown, YY",
                "availability_state": "open",
            },
        ],
        site="Official Board",
        strategy="governmentjobs_html",
        accept_locs=["Exampletown"],
        reject_locs=[],
        application_mode="active",
        source_verification="official",
    )

    rows = {
        row["url"]: dict(row)
        for row in conn.execute(
            "SELECT url, archived_at, archive_reason, availability_state, availability_checked_at, last_seen_at "
            "FROM jobs WHERE url IN (?, ?, ?)",
            (legacy_url, user_url, policy_url),
        )
    }
    assert rows[legacy_url]["archived_at"] is None
    assert rows[legacy_url]["archive_reason"] is None
    assert rows[legacy_url]["availability_state"] == "open"
    assert rows[legacy_url]["availability_checked_at"]
    assert rows[legacy_url]["last_seen_at"]
    assert rows[user_url]["archived_at"]
    assert rows[user_url]["archive_reason"] == "user"
    assert rows[policy_url]["archived_at"]
    assert rows[policy_url]["archive_reason"] == "policy"
    close_connection(db_path)


def test_v104_v106_result_location_drives_market_and_title_policy(tmp_path) -> None:
    db_path = tmp_path / "divapply.db"
    conn = init_db(db_path)
    search_config = {
        "default_market_label": "Current market",
        "locations": [
            {"label": "Current market", "location": "Exampletown, YY"},
            {"label": "Destination market", "location": "Sample City, ZZ"},
        ],
        "market_policies": {
            "Current market": {
                "application_mode": "active",
                "include_titles": ["dispatcher", "custodian"],
            },
            "Destination market": {
                "application_mode": "active",
                "include_titles": ["IT assistant", "administrative clerk"],
            },
        },
    }

    smartextract._store_jobs_filtered(
        conn,
        [
            {
                "url": "https://www.governmentjobs.com/jobs/1/dispatcher",
                "title": "Part-Time Dispatcher",
                "location": "Exampletown, YY",
                "availability_state": "open",
            },
            {
                "url": "https://www.governmentjobs.com/jobs/2/bartender",
                "title": "Bartender",
                "location": "Sample City, ZZ",
                "availability_state": "open",
            },
            {
                "url": "https://www.governmentjobs.com/jobs/3/it-assistant",
                "title": "IT Assistant",
                "location": "Sample City, ZZ",
                "availability_state": "open",
            },
        ],
        site="GovernmentJobs.com",
        strategy="governmentjobs_html",
        accept_locs=["Exampletown", "Sample City"],
        reject_locs=[],
        filter_rules={"include_titles": ["dispatcher", "bartender", "IT assistant"]},
        market_label="Current market",
        application_mode="active",
        source_verification="official",
        search_config=search_config,
    )

    rows = conn.execute("SELECT title, market_label FROM jobs ORDER BY title").fetchall()
    assert [tuple(row) for row in rows] == [
        ("IT Assistant", "Destination market"),
        ("Part-Time Dispatcher", "Current market"),
    ]
    close_connection(db_path)


def test_v105_calcareers_parser_extracts_current_cards() -> None:
    page = """
    <html><body><div>1 job(s) found.</div>
      <div class="card-block">
        <a class="lead" href="https://www.calcareers.ca.gov/CalHrPublic/Jobs/JobPosting.aspx?JobControlId=524385">INFORMATION TECHNOLOGY ASSOCIATE</a>
        <div class="working-title details row"><div class="job-details">Technical Analyst</div></div>
        <div class="salary-range details row"><div class="job-details">$4935.00 - $8740.00</div></div>
        <div class="schedule details row"><div class="job-details">Permanent Fulltime</div></div>
        <div class="department details row"><div class="job-details">Example Department</div></div>
        <div class="location details row"><div class="job-details">Sample County</div></div>
        <div class="telework details row"><div class="job-details">Hybrid</div></div>
        <div class="filing-date details row"><div class="job-label">Filing Deadline:</div><div class="job-details">12/31/2099</div></div>
      </div>
    </body></html>
    """

    jobs = smartextract._parse_calcareers_results(page, "State of Example")

    assert jobs == [
        {
            "url": "https://www.calcareers.ca.gov/CalHrPublic/Jobs/JobPosting.aspx?JobControlId=524385",
            "application_url": "https://www.calcareers.ca.gov/CalHrPublic/Jobs/JobPosting.aspx?JobControlId=524385",
            "title": "INFORMATION TECHNOLOGY ASSOCIATE — Technical Analyst",
            "company": "Example Department",
            "location": "Sample County, CA",
            "salary": "$4935.00 - $8740.00",
            "description": "Permanent Fulltime; Hybrid; Filing Deadline: 12/31/2099",
            "employment_type": "Permanent Fulltime",
            "availability_state": "open",
        }
    ]


def test_v102_past_filing_deadline_is_not_open() -> None:
    today = date(2026, 7, 21)

    assert smartextract._filing_deadline_is_past("7/20/2026", today=today) is True
    assert smartextract._filing_deadline_is_past("7/21/2026", today=today) is False
    assert smartextract._filing_deadline_is_past("Continuous", today=today) is False


def test_v105_official_board_targets_use_deterministic_adapters_and_site_query_allowlist() -> None:
    search_config = {
        "queries": [
            {"query": "information technology associate", "location_labels": ["Destination market"]},
            {"query": "office assistant", "location_labels": ["Destination market"]},
        ],
        "locations": [{"label": "Destination market", "location": "Sample City, ZZ"}],
        "market_policies": {"Destination market": {"application_mode": "active"}},
    }
    targets = smartextract.build_scrape_targets(
        sites=[
            {
                "name": "GovernmentJobs.com",
                "url": "https://www.governmentjobs.com/jobs?keyword={query_encoded}&location={location_encoded}",
                "type": "search",
                "source_verification": "official",
            },
            {
                "name": "Example County",
                "url": "https://www.jobapscloud.com/Example/JobBoard.asp",
                "type": "static",
                "source_verification": "official",
            },
            {
                "name": "State of Example",
                "url": "https://www.calcareers.ca.gov/CalHRPublic/Search/JobSearchResults.aspx",
                "type": "search",
                "adapter": "calcareers",
                "queries": ["information technology associate"],
                "location_labels": ["Destination market"],
                "source_verification": "official",
            },
        ],
        search_cfg=search_config,
    )

    assert [(target["name"], target["query"], target["adapter"]) for target in targets] == [
        ("GovernmentJobs.com", "information technology associate", "governmentjobs"),
        ("GovernmentJobs.com", "office assistant", "governmentjobs"),
        ("Example County", None, "jobaps"),
        ("State of Example", "information technology associate", "calcareers"),
    ]
