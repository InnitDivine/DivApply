from __future__ import annotations

from typer.testing import CliRunner

from divapply import cli, view
from divapply.cli import app


runner = CliRunner()


def test_dashboard_static_no_open_generates_file_without_starting_server(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}
    output = tmp_path / "dashboard.html"

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(view, "generate_dashboard", lambda: calls.setdefault("generated", str(output)))

    def fail_open_dashboard() -> None:
        raise AssertionError("static --no-open should not open a browser")

    def fail_serve_dashboard(*, port: int, open_browser: bool) -> str:
        raise AssertionError("static dashboard should not start the interactive server")

    monkeypatch.setattr(view, "open_dashboard", fail_open_dashboard)
    monkeypatch.setattr(view, "serve_dashboard", fail_serve_dashboard)

    result = runner.invoke(app, ["dashboard", "--static", "--no-open"])

    assert result.exit_code == 0
    assert calls["generated"] == str(output)
    assert "Dashboard written" in result.output
    assert output.name in result.output


def test_dashboard_static_default_opens_generated_dashboard_without_server(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)
    monkeypatch.setattr(view, "open_dashboard", lambda: calls.append("open"))

    def fail_generate_dashboard() -> str:
        raise AssertionError("open_dashboard owns generation in default static mode")

    def fail_serve_dashboard(*, port: int, open_browser: bool) -> str:
        raise AssertionError("static dashboard should not start the interactive server")

    monkeypatch.setattr(view, "generate_dashboard", fail_generate_dashboard)
    monkeypatch.setattr(view, "serve_dashboard", fail_serve_dashboard)

    result = runner.invoke(app, ["dashboard", "--static"])

    assert result.exit_code == 0
    assert calls == ["open"]


def test_dashboard_interactive_passes_port_and_no_open_to_server(monkeypatch) -> None:
    received: dict[str, object] = {}

    monkeypatch.setattr(cli, "_bootstrap", lambda: None)

    def fake_serve_dashboard(*, port: int, open_browser: bool) -> str:
        received["port"] = port
        received["open_browser"] = open_browser
        return "http://127.0.0.1:9999/"

    monkeypatch.setattr(view, "serve_dashboard", fake_serve_dashboard)
    monkeypatch.setattr(view, "generate_dashboard", lambda: (_ for _ in ()).throw(AssertionError("unexpected")))
    monkeypatch.setattr(view, "open_dashboard", lambda: (_ for _ in ()).throw(AssertionError("unexpected")))

    result = runner.invoke(app, ["dashboard", "--port", "9999", "--no-open"])

    assert result.exit_code == 0
    assert received == {"port": 9999, "open_browser": False}
