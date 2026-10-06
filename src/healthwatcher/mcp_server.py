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


DETAIL_HORIZON_DAYS = 28


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
def get_profile() -> dict[str, Any]:
    """The athlete's profile from the app's Profile tab: personal details, goals/races (with priority, date,
    target, status), training start date, season phases (prep/base/build/peak/taper) and current phase,
    available hours, thresholds, health limitations, equipment, coaching preferences, notes."""
    from . import profile as athlete

    p = athlete.get()
    return {"profile": p, "season": athlete.season(p), "age": athlete.age(p), "goal_types": athlete.GOAL_TYPES}


@mcp.tool()
def update_profile(changes: dict[str, Any], reason: str) -> dict[str, Any]:
    """Update the athlete's profile (shown in the app's Profile tab). `changes` is deep-merged: nested dicts
    (thresholds, health) merge key by key; lists (goals) are REPLACED, so send the full goals list - read it
    with get_profile first and keep each goal's id. Goal fields: id, name, date (YYYY-MM-DD), type (see
    goal_types), priority (A/B/C), target, status (planned/registered/done), notes. Only record what the
    athlete told you or agreed to; `reason` is shown to them in the change log."""
    from . import profile as athlete

    allowed = set(athlete.EMPTY) - {"updated_at", "updated_by"}
    bad = [k for k in changes if k not in allowed]
    if bad:
        return {"error": f"Unknown profile fields {bad}. Allowed: {sorted(allowed)}"}
    p = athlete.save(changes, by="coach", reason=reason, merge=True)
    return {"status": "saved", "season": athlete.season(p)}


@mcp.tool()
def add_planned_workouts(workouts: list[dict[str, Any]]) -> dict[str, Any]:
    """Put workouts on the app's Calendar as coach-planned sessions (local to the app - NOT pushed to the
    watch; use the garmin tools for that, with approval). Each item: day (YYYY-MM-DD), name, sport
    (running/cycling/swimming/strength_training/walking/...), duration_min, optional distance_km, tss
    (your estimate), kind (session | test | race) and description (markdown: purpose, warm-up / main set /
    cool-down with HR, power or pace targets from the athlete's thresholds, RPE, fuelling for long sessions).
    Only days within the next 28 days are accepted - later weeks belong in set_plan_weeks (outline only)."""
    import json as _json
    import uuid as _uuid

    ids, rejected = [], []
    horizon = (date.today() + timedelta(days=DETAIL_HORIZON_DAYS)).isoformat()
    with db.session() as c:
        for w in workouts:
            if not w.get("day") or not w.get("name"):
                continue
            if str(w["day"]) > horizon:
                rejected.append(w["day"])
                continue
            wid = f"coach:{_uuid.uuid4().hex[:10]}"
            db.upsert(c, "planned", "id", {
                "id": wid, "day": w["day"], "name": w["name"], "sport": w.get("sport") or "other",
                "duration_s": float(w["duration_min"]) * 60 if w.get("duration_min") else None,
                "distance_m": float(w["distance_km"]) * 1000 if w.get("distance_km") else None,
                "workout_id": None, "item_type": "coach", "description": w.get("description"),
                "planned_tss": float(w["tss"]) if w.get("tss") else None,
                "kind": w.get("kind") if w.get("kind") in ("session", "test", "race") else "session",
                "raw": _json.dumps(w),
            })
            ids.append(wid)
    out: dict[str, Any] = {"created": ids}
    if rejected:
        out["rejected_beyond_horizon"] = sorted(set(rejected))
        out["note"] = (f"Detailed sessions are limited to the next {DETAIL_HORIZON_DAYS} days (see coach/METHOD.md). "
                       "Describe later weeks with set_plan_weeks instead.")
    return out


@mcp.tool()
def update_planned_workouts(changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Edit coach-planned workouts on the app calendar. Each item: id (from get_plan / get_planned_workouts,
    'coach:...') plus any fields to change: day (move it), name, sport, duration_min, distance_km, tss,
    description."""
    done = []
    with db.session() as c:
        for ch in changes:
            wid = str(ch.get("id") or "")
            if not wid.startswith("coach:"):
                continue
            sets = {}
            for k in ("day", "name", "sport", "description", "kind"):
                if k in ch:
                    sets[k] = ch[k]
            if "duration_min" in ch:
                sets["duration_s"] = float(ch["duration_min"]) * 60 if ch["duration_min"] else None
            if "distance_km" in ch:
                sets["distance_m"] = float(ch["distance_km"]) * 1000 if ch["distance_km"] else None
            if "tss" in ch:
                sets["planned_tss"] = float(ch["tss"]) if ch["tss"] else None
            if sets:
                c.execute(f"UPDATE planned SET {', '.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), wid])
                done.append(wid)
    return {"updated": done}


@mcp.tool()
def set_plan_weeks(weeks: list[dict[str, Any]]) -> dict[str, Any]:
    """Write the season plan at week level (shown in the app calendar's week summary next to what was actually
    done). Each item: week (the Monday, YYYY-MM-DD), phase (Base/Build/Peak/Taper/Recovery/Race/Transition),
    week_type (load | recovery | test | taper | race | transition), block (e.g. "Base 1 - week 2/4"),
    focus (one line), hours, tss, optional swim_h, bike_h, run_h, strength_h, key_sessions (short text - only
    for the current/next block; leave empty for far-out weeks), notes. Existing weeks are overwritten.
    Cover the whole season through race week as an OUTLINE (see coach/METHOD.md); detailed sessions go in
    add_planned_workouts."""
    from datetime import date as _date

    saved = []
    with db.session() as c:
        for w in weeks:
            try:
                d = _date.fromisoformat(str(w.get("week")))
            except ValueError:
                continue
            monday = (d - timedelta(days=d.weekday())).isoformat()
            db.upsert(c, "plan_weeks", "week", {
                "week": monday, "phase": w.get("phase"), "focus": w.get("focus"),
                "week_type": w.get("week_type"), "block": w.get("block"),
                "hours": w.get("hours"), "tss": w.get("tss"),
                "swim_h": w.get("swim_h"), "bike_h": w.get("bike_h"), "run_h": w.get("run_h"),
                "strength_h": w.get("strength_h"), "key_sessions": w.get("key_sessions"),
                "notes": w.get("notes"), "updated_at": db.now_iso(),
            })
            saved.append(monday)
    return {"saved_weeks": len(saved), "first": min(saved) if saved else None, "last": max(saved) if saved else None}


@mcp.tool()
def get_plan(start: str | None = None, end: str | None = None) -> dict[str, Any]:
    """The training plan between two dates (default: this week + 3 weeks): week targets (plan_weeks) with what
    was actually done per week, and every planned workout (coach + Garmin) with ids for update/delete."""
    t = date.today()
    s = start or (t - timedelta(days=t.weekday())).isoformat()
    e = end or (date.fromisoformat(s) + timedelta(days=27)).isoformat()
    weeks = analytics.weekly(s, e)
    return {
        "weeks": [{k: w.get(k) for k in ("week", "plan", "tss", "duration_s", "count", "planned_sessions_s",
                                          "planned_sessions_tss", "ctl", "atl", "tsb")} for w in weeks],
        "detail_horizon": (date.today() + timedelta(days=DETAIL_HORIZON_DAYS)).isoformat(),
        "workouts": db.rows("SELECT id, day, name, sport, duration_s, distance_m, planned_tss, item_type, kind, description "
                            "FROM planned WHERE day BETWEEN ? AND ? ORDER BY day", (s, e)),
    }


@mcp.tool()
def delete_planned_workouts(ids: list[str] | None = None, start: str | None = None, end: str | None = None) -> dict[str, Any]:
    """Remove coach-planned workouts from the app's Calendar: by ids ('coach:...'), or every coach workout
    between start and end (YYYY-MM-DD, inclusive) - handy before re-planning a block. Garmin workouts are
    never touched here."""
    ids = list(ids or [])
    if start and end:
        ids += [r["id"] for r in db.rows("SELECT id FROM planned WHERE item_type='coach' AND day BETWEEN ? AND ?", (start, end))]
    ids = [i for i in ids if str(i).startswith("coach:")]
    with db.session() as c:
        for i in ids:
            c.execute("DELETE FROM planned WHERE id=?", (i,))
    return {"deleted": ids}


@mcp.tool()
def get_readiness(day: str | None = None) -> dict[str, Any]:
    """Rule-based readiness verdict (Rest / Recovery / Easy / Train / Go) with flags for a day (YYYY-MM-DD, default today)."""
    return analytics.assessment(day)


def _hourly(points: list, value_idx: int = 1) -> list[dict[str, Any]]:
    """Condense minute-level [ts_ms, value, ...] samples into hourly min/avg/max (local time)."""
    from datetime import datetime

    buckets: dict[int, list[float]] = {}
    for p in points or []:
        if not isinstance(p, list) or len(p) <= value_idx or p[value_idx] is None or p[value_idx] < 0:
            continue
        hour = datetime.fromtimestamp(p[0] / 1000).hour
        buckets.setdefault(hour, []).append(p[value_idx])
    return [{"hour": h, "min": min(v), "avg": round(sum(v) / len(v)), "max": max(v)} for h, v in sorted(buckets.items())]


@mcp.tool()
def get_day(day: str) -> dict[str, Any]:
    """Everything about one calendar day (YYYY-MM-DD): Garmin wellness row (sleep stages/score, HRV, RHR,
    stress, body battery, readiness, training status), readiness verdict, all sessions with TSS and HR zones,
    planned workouts, the athlete's check-in, and hourly heart-rate / stress / body-battery profiles."""
    with db.session(readonly=True) as c:
        hr = db.get_raw(c, day, "garmin.heart_rates") or {}
        st = db.get_raw(c, day, "garmin.stress") or {}
        sleep = db.get_raw(c, day, "garmin.sleep") or {}
    sleep_dto = sleep.get("dailySleepDTO") or {}
    return {
        "day": day,
        "daily": (db.rows("SELECT * FROM daily WHERE day=?", (day,)) or [None])[0],
        "readiness": analytics.assessment(day),
        "activities": [{k: v for k, v in a.items() if k != "raw"} for a in analytics.load_activities(day, day)],
        "planned": db.rows("SELECT day, name, sport, duration_s, distance_m FROM planned WHERE day=?", (day,)),
        "checkin": (db.rows("SELECT * FROM checkins WHERE day=?", (day,)) or [None])[0],
        "sleep_detail": {
            "score_feedback": sleep_dto.get("sleepScoreFeedback"),
            "insight": sleep_dto.get("sleepScoreInsight"),
            "scores": sleep_dto.get("sleepScores"),
        } if sleep_dto else None,
        "hourly_heart_rate": _hourly(hr.get("heartRateValues")),
        "hourly_stress": _hourly(st.get("stressValuesArray")),
        "hourly_body_battery": _hourly(st.get("bodyBatteryValuesArray"), 2),
    }


@mcp.tool()
def get_activity_detail(activity_id: int) -> dict[str, Any]:
    """One Garmin activity in depth: summary metrics, HR-zone times, training effect, the matching Strava
    entry, and per-lap splits (distance, time, pace/speed, HR, power, cadence, elevation). Activity ids come
    from get_activities / get_day (garmin_id)."""
    import json as _json

    from . import garmin_sync

    rows = db.rows("SELECT * FROM garmin_activities WHERE id=?", (activity_id,))
    if not rows:
        return {"error": f"No Garmin activity {activity_id} in the local database."}
    a = rows[0]
    raw = _json.loads(a.pop("raw") or "{}")
    with db.session(readonly=True) as c:
        splits = db.get_raw(c, a["day"], f"garmin.splits:{activity_id}")
    if not splits and garmin_sync.has_tokens():
        try:
            splits = garmin_sync.client().get_activity_splits(str(activity_id))
            with db.session() as c:
                db.put_raw(c, a["day"], f"garmin.splits:{activity_id}", splits or {})
        except Exception as e:  # offline or not logged in - return what we have
            splits = {"error": str(e)}
    laps = []
    for lap in (splits or {}).get("lapDTOs") or []:
        laps.append({k: lap.get(k) for k in (
            "lapIndex", "distance", "duration", "movingDuration", "averageSpeed", "averageHR", "maxHR",
            "averagePower", "normalizedPower", "averageRunCadence", "averageBikeCadence", "elevationGain",
            "intensityType", "averageSwolf", "numberOfActiveLengths") if lap.get(k) is not None})
    extra = {k: raw.get(k) for k in (
        "description", "trainingEffectLabel", "aerobicTrainingEffectMessage", "anaerobicTrainingEffectMessage",
        "avgStrideLength", "avgVerticalOscillation", "avgGroundContactTime", "maxPower", "max20MinPower",
        "trainingStressScore", "intensityFactor", "avgRespirationRate", "waterEstimated", "minTemperature",
        "maxTemperature", "locationName", "lapCount", "poolLength") if raw.get(k) is not None}
    th = analytics.thresholds()
    tss, method = analytics.activity_tss(a, th)
    return {
        "activity": a, "tss": tss, "tss_method": method, "extra": extra, "laps": laps,
        "strava": (db.rows("SELECT id, name, suffer_score, kudos, pr_count, achievement_count FROM strava_activities "
                           "WHERE garmin_id=?", (activity_id,)) or [None])[0],
    }


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
    """Planned workouts: from the Garmin Connect calendar (item_type workout etc., incl. Garmin Coach plans)
    and coach-planned sessions in the app (item_type 'coach', ids 'coach:...')."""
    t = date.today()
    return db.rows("SELECT id, day, name, sport, duration_s, distance_m, workout_id, item_type, description FROM planned "
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
    training_status/heart_rates/stress/body_comp/calendar/race_predictions/endurance_score/hill_score, and
    "garmin.splits:<activity_id>" for laps), view activities (unified), chat_messages. Max 500 rows."""
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
