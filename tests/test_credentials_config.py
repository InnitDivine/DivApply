from __future__ import annotations

import pytest

from divapply import config
from divapply.config import load_credentials
from divapply.security import PrivateFileError


def test_load_credentials_missing_or_empty_file_returns_empty_dict(tmp_path) -> None:
    missing = tmp_path / "missing.yaml"
    empty = tmp_path / "credentials.yaml"
    empty.write_text("", encoding="utf-8")

    assert load_credentials(missing) == {}
    assert load_credentials(empty) == {}


def test_load_credentials_reads_separate_credentials_file(tmp_path) -> None:
    path = tmp_path / "credentials.yaml"
    path.write_text(
        """
default:
  username: person@example.com
  password: fake-password
sites:
  example.com:
    username: site-user
    password: site-password
""",
        encoding="utf-8",
    )

    assert load_credentials(path)["sites"]["example.com"]["username"] == "site-user"


def test_load_credentials_fails_closed_when_private_permissions_fail(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "credentials.yaml"
    path.write_text("default: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        config,
        "_protect_private_user_root",
        lambda _root: (_ for _ in ()).throw(PrivateFileError("ACL denied")),
    )

    with pytest.raises(PrivateFileError, match="ACL denied"):
        load_credentials(path)
