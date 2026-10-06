"""MCP server exposing the local HealthWatcher database to Claude."""

import re
from datetime import date, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import analytics, db

mcp = FastMCP(
    "healthwatcher",
    instructions=(
        "Local store of the user's Garmin (sleep, HRV, resting HR, stress, body battery, readiness, "
        "training status, VO2max, weight, activities, planned workouts) and Strava activity data, plus "
        "a TSS-based training-load model (CTL fitness / ATL fatigue / TSB form) and subjective check-ins. "
        "Start with get_coach_briefing for any health/training question."
    ),
)


def _r(days: int) -> tuple[str, str]:
    e = date.today()
    return (e - timedelta(days=days)).isoformat(), e.isoformat()


@mcp.tool()
def get_coach_briefing(days: int = 14) -> str:
    """Markdown snapshot: profile & thresholds, today's readiness verdict and flags, PMC load metrics,
    last N days of sleep/HRV/RHR/body battery/stress/TSS, weekly summaries, recent sessions,
    planned workouts and check-ins. Call this first."""
    return analytics.briefing(days)


@mcp.tool()
def get_readiness(day: str | None = None) -> dict[str, Any]:
    """Rule-based readiness verdict (Rest / Recovery / Easy / Train / Go) with flags for a day (YYYY-MM-DD, default today)."""
    return analytics.assessment(day)


@mcp.tool()
def get_daily_metrics(days: int = 30, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    """Daily Garmin wellness rows (steps, kcal, RHR, stress, body battery, sleep stages/score, HRV, readiness,
    training status, acute/chronic load, VO2max, weight). Use start/end (YYYY-MM-DD) or last `days`."""
    s, e = (start, end or date.today().isoformat()) if start else _r(days)
    return list(analytics.load_daily(s, e).values())


@mcp.tool()
def get_activities(days: int = 28, sport_group: str | None = None) -> list[dict[str, Any]]:
    """Unified Garmin+Strava sessions for the last N days with estimated TSS, HR zones, Garmin training load and
    training effect. sport_group filter: Run, Bike, Swim, Strength, Walk/Hike, Other."""
    acts = analytics.load_activities(*_r(days))
    return [a for a in acts if not sport_group or a["group"] == sport_group]


@mcp.tool()
def get_training_load(days: int = 90, project_days: int = 14) -> dict[str, Any]:
    """Performance Management Chart: daily TSS, CTL (fitness), ATL (fatigue), TSB (form). Includes a projection
    over planned workouts for `project_days`."""
    s, e = _r(days)
    p = analytics.pmc(s, (date.today() + timedelta(days=project_days)).isoformat())
    return {"load": analytics.load_metrics(p), "thresholds": analytics.thresholds(), "series": p}


@mcp.tool()
def get_weekly_summary(weeks: int = 12) -> list[dict[str, Any]]:
    """Per-week TSS, duration, distance, sessions by sport, HR-zone time, CTL/ATL/TSB and sleep/HRV/RHR averages."""
    return analytics.weekly(*_r(weeks * 7))


@mcp.tool()
def get_planned_workouts(days_ahead: int = 28) -> list[dict[str, Any]]:
    """Workouts scheduled in the Garmin Connect calendar (incl. Garmin Coach plans)."""
    t = date.today()
    return db.rows("SELECT id, day, name, sport, duration_s, distance_m, workout_id, item_type FROM planned "
                   "WHERE day BETWEEN ? AND ? ORDER BY day", (t.isoformat(), (t + timedelta(days=days_ahead)).isoformat()))


@mcp.tool()
def get_checkins(days: int = 30) -> list[dict[str, Any]]:
    """Subjective daily check-ins (energy, soreness, mood, motivation 1-5, illness, injury, notes)."""
    return db.rows("SELECT * FROM checkins WHERE day >= ? ORDER BY day", (_r(days)[0],))


@mcp.tool()
def log_checkin(energy: int | None = None, soreness: int | None = None, mood: int | None = None,
                motivation: int | None = None, illness: bool = False, injury: str | None = None,
                notes: str | None = None, day: str | None = None) -> dict[str, Any]:
    """Record how the athlete feels today (1-5 scales; soreness 5 = very sore). Merges into an existing check-in."""
    d = day or date.today().isoformat()
    existing = (db.rows("SELECT * FROM checkins WHERE day=?", (d,)) or [{}])[0]
    row = {**existing, "day": d, "illness": int(illness or existing.get("illness") or 0), "updated_at": db.now_iso()}
    for k, v in dict(energy=energy, soreness=soreness, mood=mood, motivation=motivation, injury=injury, notes=notes).items():
        if v is not None:
            row[k] = v
    with db.session() as c:
        db.upsert(c, "checkins", "day", row)
    return row


@mcp.tool()
def query_sql(sql: str) -> list[dict[str, Any]]:
    """Read-only SQL over the local SQLite DB. Tables: daily, garmin_activities, strava_activities, planned,
    checkins, raw(day, kind, json - full Garmin payloads, kinds garmin.summary/sleep/hrv/readiness/
    training_status/heart_rates/stress/body_comp/calendar), view activities (unified). Max 500 rows."""
    if not re.match(r"^\s*(select|with|pragma\s+table_info)\b", sql, re.I):
        raise ValueError("Only SELECT / WITH queries are allowed.")
    return db.rows(sql, readonly=True)[:500]


@mcp.tool()
def sync_now() -> dict[str, Any]:
    """Fetch the latest data from Garmin Connect and Strava right now (takes a few seconds)."""
    from .server import run_sync

    return run_sync()


def main() -> None:
    db.init()
    mcp.run()


if __name__ == "__main__":
    main()
