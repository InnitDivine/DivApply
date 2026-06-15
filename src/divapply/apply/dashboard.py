"""Rich live dashboard for the apply pipeline.

Displays real-time worker status, job progress, and recent events
in a terminal dashboard using the Rich library.
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

logger = logging.getLogger(__name__)


@dataclass
class WorkerState:
    """Tracks the current state of the apply worker."""

    worker_id: int = 0
    status: str = "starting"  # starting, applying, applied, failed, expired, captcha, idle, done
    job_title: str = ""
    company: str = ""
    score: int = 0
    start_time: float = 0.0
    actions: int = 0
    last_action: str = ""
    jobs_applied: int = 0
    jobs_failed: int = 0
    jobs_done: int = 0
    total_cost: float = 0.0
    log_file: Path | None = None


MAX_EVENTS = 8


class ApplyDashboardState:
    """Thread-safe state container for one live apply dashboard."""

    def __init__(self, *, max_events: int = MAX_EVENTS) -> None:
        self.max_events = max_events
        self._worker_states: dict[int, WorkerState] = {}
        self._events: list[str] = []
        self._lock = threading.Lock()

    def init_worker(self, worker_id: int = 0) -> None:
        """Register a worker in this dashboard."""
        with self._lock:
            self._worker_states[worker_id] = WorkerState(worker_id=worker_id)

    def update_state(self, worker_id: int = 0, **kwargs) -> None:
        """Update one registered worker's state fields."""
        with self._lock:
            state = self._worker_states.get(worker_id)
            if state is not None:
                for key, value in kwargs.items():
                    setattr(state, key, value)

    def get_state(self, worker_id: int = 0) -> WorkerState | None:
        """Read one worker's current state."""
        with self._lock:
            return self._worker_states.get(worker_id)

    def add_event(self, msg: str) -> None:
        """Add a timestamped event to this dashboard's event log."""
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._events.append(f"[dim]{ts}[/dim] {msg}")
            if len(self._events) > self.max_events:
                self._events.pop(0)

    def worker_states(self) -> list[WorkerState]:
        """Return worker states sorted for deterministic rendering."""
        with self._lock:
            return sorted(self._worker_states.values(), key=lambda s: s.worker_id)

    def event_lines(self) -> list[str]:
        """Return a copy of the recent event log."""
        with self._lock:
            return list(self._events)

    def get_totals(self) -> dict[str, int | float]:
        """Compute aggregate totals across all workers."""
        with self._lock:
            applied = sum(s.jobs_applied for s in self._worker_states.values())
            failed = sum(s.jobs_failed for s in self._worker_states.values())
            cost = sum(s.total_cost for s in self._worker_states.values())
        return {"applied": applied, "failed": failed, "cost": cost}


_default_state = ApplyDashboardState()


# ---------------------------------------------------------------------------
# State mutation helpers
# ---------------------------------------------------------------------------

def init_worker(worker_id: int = 0) -> None:
    """Register the worker in the dashboard state."""
    _default_state.init_worker(worker_id)


def update_state(worker_id: int = 0, **kwargs) -> None:
    """Update the worker's state fields.

    Args:
        worker_id: Which worker to update.
        **kwargs: Field names and values to set on WorkerState.
    """
    _default_state.update_state(worker_id, **kwargs)


def get_state(worker_id: int = 0) -> WorkerState | None:
    """Read the worker's current state."""
    return _default_state.get_state(worker_id)


def add_event(msg: str) -> None:
    """Add a timestamped event to the scrolling event log.

    Args:
        msg: Rich markup string describing the event.
    """
    _default_state.add_event(msg)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# Status -> Rich style mapping
_STATUS_STYLES: dict[str, str] = {
    "starting": "dim",
    "idle": "dim",
    "applying": "yellow",
    "applied": "bold green",
    "failed": "red",
    "expired": "dim red",
    "captcha": "magenta",
    "login_issue": "red",
    "done": "bold",
}


def render_dashboard(state: ApplyDashboardState | None = None) -> Table:
    """Build the Rich table showing all worker statuses.

    Returns:
        A Rich Table object ready for display.
    """
    table = Table(title="DivApply Dashboard", expand=True, show_lines=False)
    table.add_column("W", style="bold", width=3, justify="center")
    table.add_column("Job", min_width=30, max_width=50, no_wrap=True)
    table.add_column("Status", width=12, justify="center")
    table.add_column("Time", width=6, justify="right")
    table.add_column("Acts", width=5, justify="right")
    table.add_column("Last Action", min_width=20, max_width=35, no_wrap=True)
    table.add_column("OK", width=4, justify="right", style="green")
    table.add_column("Fail", width=4, justify="right", style="red")
    table.add_column("Cost", width=8, justify="right")

    dashboard_state = state or _default_state
    states = dashboard_state.worker_states()

    total_applied = 0
    total_failed = 0
    total_cost = 0.0

    for s in states:
        elapsed = ""
        if s.start_time and s.status == "applying":
            elapsed = f"{int(time.time() - s.start_time)}s"

        style = _STATUS_STYLES.get(s.status, "")
        status_text = Text(s.status.upper(), style=style)

        job_text = f"{s.job_title[:28]} @ {s.company[:16]}" if s.job_title else ""

        table.add_row(
            str(s.worker_id),
            job_text,
            status_text,
            elapsed,
            str(s.actions) if s.actions else "",
            s.last_action[:35] if s.last_action else "",
            str(s.jobs_applied),
            str(s.jobs_failed),
            f"${s.total_cost:.3f}" if s.total_cost else "",
        )
        total_applied += s.jobs_applied
        total_failed += s.jobs_failed
        total_cost += s.total_cost

    # Totals row
    table.add_section()
    table.add_row(
        "", "", "", "", "", "TOTAL",
        str(total_applied), str(total_failed), f"${total_cost:.3f}",
        style="bold",
    )

    return table


def render_full(state: ApplyDashboardState | None = None) -> Table | Group:
    """Render the dashboard table plus the recent events panel.

    Returns:
        A Rich Group (table + events panel) or just the table if no events.
    """
    dashboard_state = state or _default_state
    table = render_dashboard(dashboard_state)
    event_lines = dashboard_state.event_lines()

    if event_lines:
        event_text = Text.from_markup("\n".join(event_lines))
        events_panel = Panel(
            event_text,
            title="Recent Events",
            border_style="dim",
            height=min(MAX_EVENTS + 2, len(event_lines) + 2),
        )
        return Group(table, events_panel)

    return table


def get_totals() -> dict[str, int | float]:
    """Compute aggregate totals across all workers.

    Returns:
        Dict with keys: applied, failed, cost.
    """
    return _default_state.get_totals()
