from __future__ import annotations

from divapply import social
from divapply.security import UnsafeUrlError


def test_social_credentials_ignore_profile_passwords(monkeypatch) -> None:
    profile = {
        "personal": {"email": "person@example.com", "password": "profile-secret"},
        "site_credentials": {
            "linkedin.com": {
                "username": "profile-user",
                "password": "profile-site-secret",
            }
        },
    }

    monkeypatch.delenv("DIVAPPLY_LOGIN_USERNAME", raising=False)
    monkeypatch.delenv("DIVAPPLY_LOGIN_PASSWORD", raising=False)
    monkeypatch.delenv("APPLYPILOT_LOGIN_USERNAME", raising=False)
    monkeypatch.delenv("APPLYPILOT_LOGIN_PASSWORD", raising=False)
    monkeypatch.setattr(social, "load_env", lambda: None)
    monkeypatch.setattr(social, "load_credentials", lambda: {})

    assert social._get_credentials(profile, "linkedin.com") == ("person@example.com", "")


def test_social_credentials_use_credentials_yaml(monkeypatch) -> None:
    profile = {"personal": {"email": "person@example.com"}}

    monkeypatch.setattr(social, "load_env", lambda: None)
    monkeypatch.setattr(
        social,
        "load_credentials",
        lambda: {
            "default": {"username": "default-user", "password": "default-password"},
            "sites": {
                "linkedin.com": {
                    "username": "site-user",
                    "password": "site-password",
                }
            },
        },
    )

    assert social._get_credentials(profile, "linkedin.com") == ("site-user", "site-password")
    assert social._get_credentials(profile, "facebook.com") == ("default-user", "default-password")


def test_linkedin_profile_url_defaults_and_accepts_linkedin() -> None:
    assert social._linkedin_profile_url({"personal": {}}) == "https://www.linkedin.com/in/me"
    assert (
        social._linkedin_profile_url({"personal": {"linkedin_url": "https://www.linkedin.com/in/example"}})
        == "https://www.linkedin.com/in/example"
    )


def test_linkedin_profile_url_rejects_unsafe_or_wrong_hosts() -> None:
    for value in ("javascript:alert(1)", "https://evil.example/in/example", "http://127.0.0.1:8080/profile"):
        try:
            social._linkedin_profile_url({"personal": {"linkedin_url": value}})
        except UnsafeUrlError:
            pass
        else:
            raise AssertionError(f"expected unsafe LinkedIn URL to be rejected: {value}")
