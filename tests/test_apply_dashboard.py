from __future__ import annotations

from rich.console import Group

from divapply.apply.dashboard import ApplyDashboardState, render_full


def test_apply_dashboard_state_isolated_between_instances() -> None:
    first = ApplyDashboardState()
    second = ApplyDashboardState()

    first.init_worker(1)
    first.update_state(1, jobs_applied=2, jobs_failed=1, total_cost=0.25)

    assert first.get_totals() == {"applied": 2, "failed": 1, "cost": 0.25}
    assert second.get_totals() == {"applied": 0, "failed": 0, "cost": 0}
    assert second.get_state(1) is None


def test_render_full_accepts_explicit_dashboard_state() -> None:
    state = ApplyDashboardState(max_events=1)
    state.init_worker(0)
    state.update_state(0, status="applied", job_title="Support Engineer", company="Example")
    state.add_event("[green]submitted[/green]")

    rendered = render_full(state)

    assert isinstance(rendered, Group)
