from __future__ import annotations

from divapply import social


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
