from __future__ import annotations

from types import SimpleNamespace

from divapply import jobspy_runtime


def test_jobspy_runtime_accepts_only_supported_secure_versions(monkeypatch) -> None:
    versions = {
        "python-jobspy": "1.1.82",
        "numpy": "1.26.3",
        "beautifulsoup4": "4.13.4",
        "markdownify": "1.2.3",
        "pandas": "2.3.3",
        "pydantic": "2.13.4",
        "regex": "2024.11.6",
        "requests": "2.32.5",
        "tls-client": "1.0.1",
    }
    monkeypatch.setattr(jobspy_runtime.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(
        jobspy_runtime.importlib,
        "import_module",
        lambda name: SimpleNamespace(scrape_jobs=lambda: None) if name == "jobspy" else None,
    )

    assert jobspy_runtime.validate_installed_jobspy() == []


def test_jobspy_runtime_rejects_unsupported_or_vulnerable_versions(monkeypatch) -> None:
    versions = {
        "python-jobspy": "1.1.82",
        "numpy": "1.26.3",
        "beautifulsoup4": "4.13.4",
        "markdownify": "0.13.1",
        "pandas": "3.0.0",
        "pydantic": "2.13.4",
        "regex": "2025.1.0",
        "requests": "2.32.5",
        "tls-client": "1.0.1",
    }
    monkeypatch.setattr(jobspy_runtime.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(
        jobspy_runtime.importlib,
        "import_module",
        lambda name: SimpleNamespace(scrape_jobs=lambda: None) if name == "jobspy" else None,
    )

    issues = jobspy_runtime.validate_installed_jobspy()

    assert any("markdownify" in issue for issue in issues)
    assert any("pandas" in issue for issue in issues)
    assert any("regex" in issue for issue in issues)


def test_jobspy_runtime_rejects_broken_public_api_import(monkeypatch) -> None:
    def fail_import(name: str):
        raise ImportError(f"cannot import {name}")

    monkeypatch.setattr(jobspy_runtime.importlib, "import_module", fail_import)
    monkeypatch.setattr(jobspy_runtime.metadata, "version", lambda name: "1.1.82")

    issues = jobspy_runtime.validate_installed_jobspy()

    assert any("JobSpy import failed" in issue for issue in issues)
