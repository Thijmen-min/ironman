"""Athlete profile: slow-changing facts, goals and season plan shared by the UI and the coach."""

import copy
import json
import math
import uuid
from datetime import date, timedelta
from typing import Any

from . import db

GOAL_TYPES = {
    "ironman": "Ironman (full)",
    "half_ironman": "70.3 / half Ironman",
    "olympic_tri": "Olympic triathlon",
    "sprint_tri": "Sprint triathlon",
    "marathon": "Marathon",
    "half_marathon": "Half marathon",
    "10k": "10K",
    "5k": "5K",
    "bike_event": "Cycling event",
    "swim_event": "Swim event",
    "other": "Other",
}
# (taper, peak, build) weeks before the race; everything earlier is base.
_PHASE_WEEKS = {
    "ironman": (3, 6, 12), "half_ironman": (2, 5, 10), "marathon": (3, 5, 10), "half_marathon": (1, 4, 8),
    "olympic_tri": (1, 4, 8), "sprint_tri": (1, 3, 6), "10k": (1, 3, 6), "5k": (1, 3, 6),
    "bike_event": (1, 4, 8), "swim_event": (1, 3, 6), "other": (1, 4, 8),
}

EMPTY: dict[str, Any] = {
    "name": "", "birth_date": "", "sex": "", "height_cm": None, "weight_kg": None, "language": "",
    "schedule": "", "background": "",
    "training_start": "", "hours_now": None, "hours_max": None, "availability": "",
    "goals": [],
    "thresholds": {"ftp_w": None, "lthr_run": None, "lthr_bike": None, "max_hr_run": None, "max_hr_bike": None,
                   "rhr": None, "swim_100m_pace": "", "run_threshold_pace": ""},
    "health": {"current": "", "history": "", "medical": ""},
    "equipment": "", "coach_style": "", "notes": "",
    "updated_at": None, "updated_by": None,
}


def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def get() -> dict[str, Any]:
    return _merge(EMPTY, db.kv_get("athlete.profile") or {})


def save(data: dict[str, Any], by: str = "you", reason: str = "", merge: bool = False) -> dict[str, Any]:
    """Replace (or deep-merge) the profile and record the change in profile_history."""
    current = get()
    new = _merge(current, data) if merge else _merge(EMPTY, data)
    for g in new.get("goals") or []:
        if not g.get("id"):
            g["id"] = uuid.uuid4().hex[:8]
    new["updated_at"] = db.now_iso()
    new["updated_by"] = by
    db.kv_set("athlete.profile", new)
    changed = sorted(k for k in set(current) | set(new)
                     if k not in ("updated_at", "updated_by") and current.get(k) != new.get(k))
    if changed:
        with db.session() as c:
            c.execute("INSERT INTO profile_history(ts, by, fields, reason, snapshot) VALUES (?,?,?,?,?)",
                      (db.now_iso(), by, ", ".join(changed), reason, json.dumps(current)))
    return new


def history(limit: int = 30) -> list[dict[str, Any]]:
    return db.rows("SELECT ts, by, fields, reason FROM profile_history ORDER BY ts DESC LIMIT ?", (limit,))


def age(p: dict[str, Any]) -> int | None:
    try:
        b = date.fromisoformat(p.get("birth_date") or "")
    except ValueError:
        return None
    t = date.today()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def _parse(d: str | None) -> date | None:
    try:
        return date.fromisoformat(d) if d else None
    except ValueError:
        return None


def a_race(p: dict[str, Any]) -> dict[str, Any] | None:
    """The next upcoming goal, A-priority first."""
    today = date.today()
    upcoming = [g for g in p.get("goals") or [] if _parse(g.get("date")) and _parse(g["date"]) >= today
                and g.get("status") != "done"]
    if not upcoming:
        return None
    return sorted(upcoming, key=lambda g: (g.get("priority") or "C", g["date"]))[0]


def season(p: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Phase plan (prep/base/build/peak/taper) working back from the A-race."""
    p = p or get()
    race = a_race(p)
    if not race:
        return None
    today = date.today()
    rd = date.fromisoformat(race["date"])
    taper, peak, build = _PHASE_WEEKS.get(race.get("type") or "other", _PHASE_WEEKS["other"])
    taper_start = rd - timedelta(weeks=taper)
    peak_start = taper_start - timedelta(weeks=peak)
    build_start = peak_start - timedelta(weeks=build)
    start = _parse(p.get("training_start")) or min(today, build_start)
    base_start = min(start, build_start)
    phases = []
    if today < start:
        phases.append({"name": "Preparation", "start": today.isoformat(), "end": (start - timedelta(days=1)).isoformat()})
    for name, a, b in (("Base", base_start, build_start), ("Build", build_start, peak_start),
                       ("Peak", peak_start, taper_start), ("Taper", taper_start, rd)):
        if b > a:
            phases.append({"name": name, "start": a.isoformat(), "end": (b - timedelta(days=1)).isoformat()})
    current = next((ph for ph in phases if ph["start"] <= today.isoformat() <= ph["end"]), None)
    out = {
        "race": race, "days_to_race": (rd - today).days, "weeks_to_race": math.ceil((rd - today).days / 7),
        "training_start": start.isoformat(), "phases": phases,
        "phase": current["name"] if current else ("Race week" if (rd - today).days <= 7 else None),
    }
    if current:
        ps = date.fromisoformat(current["start"])
        pe = date.fromisoformat(current["end"])
        out["phase_week"] = (today - ps).days // 7 + 1
        out["phase_weeks"] = math.ceil(((pe - ps).days + 1) / 7)
    if today >= start:
        out["training_week"] = (today - start).days // 7 + 1
    return out


def _v(x: Any, unit: str = "") -> str:
    return f"{x}{unit}" if x not in (None, "") else "-"


def to_markdown(p: dict[str, Any] | None = None) -> str:
    """Compact profile for the coach's system prompt and the briefing."""
    p = p or get()
    if not any(p.get(k) for k in ("name", "goals", "training_start", "notes", "schedule")):
        return "## Athlete profile\n(The athlete has not filled in their profile yet - ask about goals and suggest the Profile tab.)"
    s = season(p)
    th, he = p["thresholds"], p["health"]
    lines = [
        f"## Athlete profile (Profile tab; last updated {p.get('updated_at') or '-'} by {p.get('updated_by') or '-'})",
        f"- {p.get('name') or 'Athlete'}, age {_v(age(p))}, {_v(p.get('sex'))}, {_v(p.get('height_cm'), ' cm')}, "
        f"{_v(p.get('weight_kg'), ' kg')}; preferred language: {_v(p.get('language'))}",
    ]
    if p.get("schedule"):
        lines.append(f"- Weekly life schedule: {p['schedule']}")
    if p.get("background"):
        lines.append(f"- Background: {p['background']}")
    lines += ["", "### Goals"]
    for g in sorted(p.get("goals") or [], key=lambda g: g.get("date") or "9999"):
        d = _parse(g.get("date"))
        away = f", {math.ceil((d - date.today()).days / 7)} weeks away" if d and d >= date.today() else ""
        lines.append(f"- [{g.get('priority') or '-'}] {g.get('name')} - {GOAL_TYPES.get(g.get('type'), g.get('type') or '')}, "
                     f"{g.get('date') or 'date tbc'}{away}; target: {g.get('target') or '-'}; status: {g.get('status') or '-'}"
                     f"{'; ' + g['notes'] if g.get('notes') else ''}")
    if not p.get("goals"):
        lines.append("- none set")
    lines += ["", "### Season plan"]
    if s:
        lines.append(f"- A-race: {s['race']['name']} on {s['race']['date']} ({s['weeks_to_race']} weeks / {s['days_to_race']} days away)")
        lines.append(f"- Structured training starts {s['training_start']}"
                     + (f" (training week {s['training_week']})" if s.get("training_week") else ""))
        lines.append(f"- Current phase: {s.get('phase') or '-'}"
                     + (f" (week {s['phase_week']} of {s['phase_weeks']})" if s.get("phase_week") else ""))
        lines.append("- Phases: " + "; ".join(f"{ph['name']} {ph['start']}..{ph['end']}" for ph in s["phases"]))
    lines.append(f"- Hours/week now {_v(p.get('hours_now'))}, max {_v(p.get('hours_max'))}")
    if p.get("availability"):
        lines.append(f"- Availability: {p['availability']}")
    lines += ["", "### Thresholds (athlete-provided; override Garmin)",
              f"- FTP {_v(th.get('ftp_w'), ' W')}; LTHR run {_v(th.get('lthr_run'))} / bike {_v(th.get('lthr_bike'))}; "
              f"max HR run {_v(th.get('max_hr_run'))} / bike {_v(th.get('max_hr_bike'))}; RHR {_v(th.get('rhr'))}; "
              f"swim 100 m pace {_v(th.get('swim_100m_pace'))}; run threshold pace {_v(th.get('run_threshold_pace'))}"]
    lines += ["", "### Health & limitations",
              f"- Current: {he.get('current') or 'none reported'}",
              f"- History: {he.get('history') or '-'}",
              f"- Medical: {he.get('medical') or '-'}"]
    if p.get("equipment"):
        lines += ["", f"### Equipment\n{p['equipment']}"]
    if p.get("coach_style"):
        lines += ["", f"### Coaching preferences\n{p['coach_style']}"]
    if p.get("notes"):
        lines += ["", f"### Notes\n{p['notes']}"]
    return "\n".join(lines)
