from __future__ import annotations

from pathlib import Path

from divapply.config import migrate_legacy_user_data


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_migrate_legacy_user_data_copies_files(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    current = tmp_path / "current"

    _write(legacy / "profile.json", '{"name":"Dalton"}')
    _write(legacy / "searches.yaml", "queries:\n  - query: Customer Service\n")
    _write(legacy / ".env", "OPENAI_API_KEY=test\n")
    _write(legacy / "resume.txt", "resume text")
    _write(legacy / "resume.pdf", "%PDF-1.4")
    _write(legacy / "applypilot.db", "sqlite placeholder")

    report = migrate_legacy_user_data(source_dir=legacy, target_dir=current)

    assert report == {
        "profile": "copied",
        "searches": "copied",
        "env": "copied",
        "resume_txt": "copied",
        "resume_pdf": "copied",
        "database": "copied",
    }
    assert (current / "profile.json").read_text(encoding="utf-8") == '{"name":"Dalton"}'
    assert (current / "searches.yaml").exists()
    assert (current / ".env").exists()
    assert (current / "resume.txt").exists()
    assert (current / "resume.pdf").exists()
    assert (current / "divapply.db").read_text(encoding="utf-8") == "sqlite placeholder"


def test_migrate_legacy_user_data_skips_existing_files(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    current = tmp_path / "current"

    _write(legacy / "profile.json", '{"name":"Legacy"}')
    _write(current / "profile.json", '{"name":"Current"}')

    report = migrate_legacy_user_data(source_dir=legacy, target_dir=current)

    assert report["profile"] == "skipped"
    assert (current / "profile.json").read_text(encoding="utf-8") == '{"name":"Current"}'

