"""Local web server: JSON API + static TrainingPeaks-style UI + background sync."""

import json
import logging
import threading
from datetime import date, datetime, timedelta
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import analytics, chat, db, garmin_sync, strava
from . import profile as athlete
from .config import PROJECT_ROOT, STATIC_DIR, SYNC_INTERVAL_MIN

log = logging.getLogger(__name__)
app = FastAPI(title="HealthWatcher")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
_sync_thread: threading.Thread | None = None
scheduler = BackgroundScheduler(daemon=True)


def run_sync() -> dict[str, Any]:
    g = garmin_sync.sync()
    s = strava.sync() if strava.connected() else {"status": "not_connected"}
    with db.session() as c:
        strava.match_garmin(c)
    # While older history is still being backfilled, come back soon instead of in 20 minutes.
    if g.get("status") == "ok" and (db.kv_get("garmin.history_left") or 0) > 0 and scheduler.running:
        scheduler.add_job(sync_in_background, "date", run_date=datetime.now() + timedelta(minutes=2),
                          id="backfill", replace_existing=True)
    return {"garmin": g, "strava": s}


def sync_in_background() -> bool:
    global _sync_thread
    if _sync_thread and _sync_thread.is_alive():
        return False
    _sync_thread = threading.Thread(target=run_sync, daemon=True, name="sync")
    _sync_thread.start()
    return True


@app.on_event("startup")
def _startup() -> None:
    db.init()
    scheduler.add_job(sync_in_background, "interval", minutes=SYNC_INTERVAL_MIN, id="sync",
                      next_run_time=datetime.now() + timedelta(seconds=3), coalesce=True, max_instances=1)
    scheduler.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    scheduler.shutdown(wait=False)
    await chat.shutdown()


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    # Version the static assets by their mtime so the desktop webview never runs stale JS/CSS after an update.
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for f in STATIC_DIR.iterdir():
        if f.suffix in (".js", ".css"):
            html = html.replace(f"/static/{f.name}\"", f"/static/{f.name}?v={int(f.stat().st_mtime)}\"")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- status & auth


@app.get("/api/status")
def status() -> dict[str, Any]:
    last_log = db.rows("SELECT * FROM sync_log ORDER BY ts DESC LIMIT 8")
    counts = db.rows(
        "SELECT (SELECT COUNT(*) FROM daily) days, (SELECT MIN(day) FROM daily) first_day, "
        "(SELECT COUNT(*) FROM garmin_activities) garmin_acts, (SELECT COUNT(*) FROM strava_activities) strava_acts"
    )[0]
    return {
        "garmin": {
            "has_tokens": garmin_sync.has_tokens(),
            "last_sync": db.kv_get("garmin.last_sync"),
            "history_left": db.kv_get("garmin.history_left") or 0,
            "profile_name": (db.kv_get("garmin.profile") or {}).get("name"),
        },
        "strava": {
            "configured": strava.configured(),
            "connected": strava.connected(),
            "athlete": (db.kv_get("strava.athlete") or {}).get("firstname"),
            "last_sync": db.kv_get("strava.last_sync"),
        },
        "sync": {**garmin_sync.STATE, "busy": bool(_sync_thread and _sync_thread.is_alive()),
                 "interval_min": SYNC_INTERVAL_MIN},
        "counts": counts,
        "log": last_log,
        "thresholds": analytics.thresholds(),
        "project_root": str(PROJECT_ROOT),
    }


@app.post("/api/sync")
def trigger_sync() -> dict[str, Any]:
    return {"started": sync_in_background()}


@app.post("/api/garmin/login")
def garmin_login(email: str = Body(...), password: str = Body(...)) -> dict[str, Any]:
    try:
        result = garmin_sync.start_login(email, password)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    if result == "ok":
        sync_in_background()
    return {"status": result}


@app.post("/api/garmin/mfa")
def garmin_mfa(code: str = Body(..., embed=True)) -> dict[str, Any]:
    try:
        garmin_sync.finish_login(code)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    sync_in_background()
    return {"status": "ok"}


@app.post("/api/garmin/logout")
def garmin_logout() -> dict[str, Any]:
    garmin_sync.logout()
    return {"status": "ok"}


@app.get("/strava/connect")
def strava_connect():
    if not strava.configured():
        raise HTTPException(400, "Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env first.")
    return RedirectResponse(strava.authorize_url())


@app.get("/strava/callback")
def strava_callback(code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return RedirectResponse("/#settings?strava=denied")
    try:
        strava.exchange_code(code, state)
    except Exception as e:
        return HTMLResponse(f"<p>Strava connection failed: {e}</p><a href='/'>Back</a>", status_code=400)
    sync_in_background()
    return RedirectResponse("/#settings?strava=connected")


@app.post("/api/strava/disconnect")
def strava_disconnect() -> dict[str, Any]:
    strava.disconnect()
    return {"status": "ok"}


# ---------------------------------------------------------------- data


def _range(start: str | None, end: str | None, default_days: int) -> tuple[str, str]:
    e = date.fromisoformat(end) if end else date.today()
    s = date.fromisoformat(start) if start else e - timedelta(days=default_days)
    return s.isoformat(), e.isoformat()


def _clean_activity(a: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in a.items() if k != "raw"}


@app.get("/api/calendar")
def calendar(start: str | None = None, end: str | None = None) -> dict[str, Any]:
    s, e = _range(start, end, 27)
    acts = analytics.load_activities(s, e)
    planned = db.rows("SELECT id, day, name, sport, duration_s, distance_m, item_type, description, planned_tss, kind FROM planned WHERE day BETWEEN ? AND ?", (s, e))
    daily = analytics.load_daily(s, e)
    checkins = {r["day"]: r for r in db.rows("SELECT * FROM checkins WHERE day BETWEEN ? AND ?", (s, e))}
    for p in planned:
        p["group"] = analytics.sport_group(p["sport"])
    days = []
    for d in analytics._days(date.fromisoformat(s), date.fromisoformat(e)):
        ds = d.isoformat()
        r = daily.get(ds, {})
        days.append({
            "day": ds,
            "activities": [_clean_activity(a) for a in acts if a["day"] == ds],
            "planned": [p for p in planned if p["day"] == ds],
            "metrics": {k: r.get(k) for k in (
                "sleep_s", "sleep_score", "hrv_last_night", "hrv_status", "rhr", "bb_wake", "bb_high",
                "readiness", "avg_stress", "steps", "weight_kg")},
            "checkin": checkins.get(ds),
        })
    return {"days": days, "weeks": analytics.weekly(s, e)}


@app.get("/api/dashboard")
def dashboard(start: str | None = None, end: str | None = None, metric: str = "tss") -> dict[str, Any]:
    s, e = _range(start, end, 90)
    pmc_end = (date.fromisoformat(e) + timedelta(days=14)).isoformat() if e >= date.today().isoformat() else e
    p = analytics.pmc(s, pmc_end, metric)
    daily = list(analytics.load_daily(s, e).values())
    weeks = analytics.weekly(s, e)
    acts = analytics.load_activities(s, e)
    zones = [sum(w["zones_s"][i] for w in weeks) for i in range(5)]
    sports = {g: {"tss": 0.0, "duration_s": 0.0, "distance_m": 0.0, "count": 0} for g in analytics.SPORT_GROUPS}
    for a in acts:
        sp = sports[a["group"]]
        sp["tss"] += a["tss"]
        sp["duration_s"] += a["duration_s"] or 0
        sp["distance_m"] += a["distance_m"] or 0
        sp["count"] += 1
    return {
        "range": {"start": s, "end": e}, "pmc": p, "load": analytics.load_metrics(p),
        "weeks": weeks, "daily": daily, "zones_s": zones, "sports": sports,
        "assessment": analytics.assessment(),
    }


@app.get("/api/today")
def today(day: str | None = None) -> dict[str, Any]:
    d = day or date.today().isoformat()
    with db.session() as c:
        hr = db.get_raw(c, d, "garmin.heart_rates") or {}
        st = db.get_raw(c, d, "garmin.stress") or {}
    series = {
        "hr": [[t, v] for t, v in (hr.get("heartRateValues") or []) if v is not None],
        "stress": [[t, v] for t, v in (st.get("stressValuesArray") or []) if v is not None and v >= 0],
        "body_battery": [[x[0], x[2]] for x in (st.get("bodyBatteryValuesArray") or []) if len(x) > 2 and x[2] is not None],
    }
    return {
        "day": d,
        "assessment": analytics.assessment(d),
        "daily": (db.rows("SELECT * FROM daily WHERE day=?", (d,)) or [{}])[0],
        "activities": [_clean_activity(a) for a in analytics.load_activities(d, d)],
        "intraday": series,
    }


@app.get("/api/activity/{source}/{aid}")
def activity(source: str, aid: int) -> dict[str, Any]:
    table = {"garmin": "garmin_activities", "strava": "strava_activities"}.get(source)
    if not table:
        raise HTTPException(404)
    rows = db.rows(f"SELECT * FROM {table} WHERE id=?", (aid,))
    if not rows:
        raise HTTPException(404)
    a = rows[0]
    raw = json.loads(a.pop("raw") or "{}")
    return {"activity": a, "raw": raw}


@app.get("/api/briefing", response_class=PlainTextResponse)
def briefing(days: int = 14) -> str:
    return analytics.briefing(days)


@app.get("/api/checkin")
def get_checkin(day: str | None = None) -> dict[str, Any]:
    d = day or date.today().isoformat()
    return (db.rows("SELECT * FROM checkins WHERE day=?", (d,)) or [{"day": d}])[0]


@app.post("/api/checkin")
def save_checkin(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    allowed = ("day", "energy", "soreness", "mood", "motivation", "illness", "injury", "notes")
    row = {k: payload.get(k) for k in allowed}
    row["day"] = row["day"] or date.today().isoformat()
    row["updated_at"] = db.now_iso()
    with db.session() as c:
        db.upsert(c, "checkins", "day", row)
    return row


# ---------------------------------------------------------------- coach chat


@app.get("/api/chat/status")
def chat_status() -> dict[str, Any]:
    return {"cli": chat.claude_cli(), "models": chat.MODELS, "efforts": chat.EFFORTS, "defaults": chat.defaults()}


@app.post("/api/chat/settings")
async def chat_settings(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Change the default model/effort, and the given conversation's (applies from its next message)."""
    d = chat.set_defaults(payload.get("model"), payload.get("effort"))
    cid = payload.get("conversation_id")
    if cid:
        conv = chat.get_conversation(cid, "")
        await conv.set_model(d["model"], d["effort"])
    return d


@app.get("/api/chat/conversations")
def chat_conversations() -> list[dict[str, Any]]:
    return chat.conversations()


@app.get("/api/chat/conversations/{cid}")
def chat_history(cid: str) -> list[dict[str, Any]]:
    return chat.history(cid)


@app.delete("/api/chat/conversations/{cid}")
async def chat_delete(cid: str) -> dict[str, Any]:
    await chat.delete(cid)
    return {"status": "ok"}


@app.post("/api/chat/send")
async def chat_send(payload: dict[str, Any] = Body(...)) -> StreamingResponse:
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "Empty message")

    async def events():
        async for ev in chat.send(payload.get("conversation_id"), message, payload.get("context"),
                                  payload.get("model"), payload.get("effort")):
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/chat/permission")
def chat_permission(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    ok = chat.answer_permission(payload["conversation_id"], payload["id"], bool(payload.get("allow")))
    return {"status": "ok" if ok else "expired"}


@app.post("/api/chat/interrupt")
async def chat_interrupt(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    await chat.interrupt(payload["conversation_id"])
    return {"status": "ok"}


# ---------------------------------------------------------------- athlete profile


@app.get("/api/profile")
def get_profile() -> dict[str, Any]:
    p = athlete.get()
    return {"profile": p, "season": athlete.season(p), "age": athlete.age(p),
            "goal_types": athlete.GOAL_TYPES, "thresholds_in_use": analytics.thresholds(),
            "latest_weight": (db.rows("SELECT weight_kg FROM daily WHERE weight_kg IS NOT NULL ORDER BY day DESC LIMIT 1") or [{}])[0].get("weight_kg")}


@app.put("/api/profile")
def put_profile(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    allowed = set(athlete.EMPTY) - {"updated_at", "updated_by"}
    p = athlete.save({k: v for k, v in payload.items() if k in allowed}, by="you", reason="edited in the app")
    return {"profile": p, "season": athlete.season(p)}


@app.get("/api/profile/history")
def profile_history() -> list[dict[str, Any]]:
    return athlete.history()


@app.delete("/api/planned/{pid}")
def delete_planned(pid: str) -> dict[str, Any]:
    if not pid.startswith("coach:"):
        raise HTTPException(400, "Only coach-planned workouts can be removed here; Garmin ones live in Garmin Connect.")
    with db.session() as c:
        c.execute("DELETE FROM planned WHERE id=?", (pid,))
    return {"status": "ok"}
