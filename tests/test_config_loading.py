from __future__ import annotations

from divapply import config


def test_load_search_config_empty_file_returns_empty_dict(tmp_path, monkeypatch) -> None:
    search_path = tmp_path / "searches.yaml"
    search_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(config, "SEARCH_CONFIG_PATH", search_path)
    monkeypatch.setattr(config, "LEGACY_SEARCH_CONFIG_PATH", tmp_path / "missing.yaml")

    assert config.load_search_config() == {}
