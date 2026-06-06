from __future__ import annotations

from divapply.config import load_credentials


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
