"""Strava OAuth + activity sync, matched against Garmin sessions."""

import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from . import db
from .config import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REDIRECT_URI

API = "https://www.strava.com/api/v3"
SCOPES = "read,activity:read_all,profile:read_all"


def configured() -> bool:
    return bool(STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET)


def connected() -> bool:
    return bool(db.kv_get("strava.tokens"))


def authorize_url() -> str:
    state = secrets.token_urlsafe(16)
    db.kv_set("strava.oauth_state", state)
    return "https://www.strava.com/oauth/authorize?" + urlencode({
        "client_id": STRAVA_CLIENT_ID,
        "redirect_uri": STRAVA_REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": SCOPES,
        "state": state,
    })


def exchange_code(code: str, state: str) -> dict[str, Any]:
    if not state or state != db.kv_get("strava.oauth_state"):
        raise ValueError("OAuth state mismatch - please try connecting again.")
    r = httpx.post("https://www.strava.com/oauth/token", data={
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    }, timeout=30)
    r.raise_for_status()
    tok = r.json()
    db.kv_set("strava.tokens", {k: tok[k] for k in ("access_token", "refresh_token", "expires_at")})
    db.kv_set("strava.athlete", tok.get("athlete"))
    return tok.get("athlete") or {}


def disconnect() -> None:
    db.kv_set("strava.tokens", None)


def _token() -> str:
    tok = db.kv_get("strava.tokens")
    if not tok:
        raise RuntimeError("Strava not connected")
    if tok["expires_at"] - 300 < time.time():
        r = httpx.post("https://www.strava.com/oauth/token", data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
        }, timeout=30)
        r.raise_for_status()
        new = r.json()
        tok = {k: new[k] for k in ("access_token", "refresh_token", "expires_at")}
        db.kv_set("strava.tokens", tok)
    return tok["access_token"]


def _get(path: str, **params: Any) -> Any:
    r = httpx.get(f"{API}{path}", params=params, headers={"Authorization": f"Bearer {_token()}"}, timeout=30)
    r.raise_for_status()
    return r.json()


def _row(a: dict[str, Any]) -> dict[str, Any]:
    start_local = (a.get("start_date_local") or "").replace("T", " ").rstrip("Z")
    return {
        "id": a["id"],
        "day": start_local[:10],
        "start_local": start_local[:16],
        "start_utc": (a.get("start_date") or "").replace("T", " ").rstrip("Z")[:19],
        "name": a.get("name"),
        "sport": a.get("sport_type") or a.get("type"),
        "duration_s": a.get("elapsed_time"),
        "moving_s": a.get("moving_time"),
        "distance_m": a.get("distance"),
        "elev_gain_m": a.get("total_elevation_gain"),
        "avg_hr": a.get("average_heartrate"),
        "max_hr": a.get("max_heartrate"),
        "avg_speed_ms": a.get("average_speed"),
        "avg_power": a.get("average_watts"),
        "weighted_power": a.get("weighted_average_watts"),
        "kilojoules": a.get("kilojoules"),
        "suffer_score": a.get("suffer_score"),
        "kudos": a.get("kudos_count"),
        "pr_count": a.get("pr_count"),
        "achievement_count": a.get("achievement_count"),
        "device_name": a.get("device_name"),
        "gear_id": a.get("gear_id"),
        "raw": json.dumps(a),
    }


def match_garmin(c) -> int:
    """Link Strava activities to the Garmin activity of the same session (start within 3 min)."""
    garmin = [
        (r["id"], datetime.fromisoformat(r["start_utc"]), r["duration_s"] or 0)
        for r in c.execute("SELECT id, start_utc, duration_s FROM garmin_activities WHERE start_utc != ''")
    ]
    n = 0
    for s in c.execute("SELECT id, start_utc, duration_s FROM strava_activities").fetchall():
        if not s["start_utc"]:
            continue
        st = datetime.fromisoformat(s["start_utc"])
        best = None
        for gid, gt, gdur in garmin:
            dt = abs((gt - st).total_seconds())
            if dt <= 180 and (best is None or dt < best[1]):
                best = (gid, dt)
        c.execute("UPDATE strava_activities SET garmin_id=? WHERE id=?", (best[0] if best else None, s["id"]))
        n += bool(best)
    return n


def sync(backfill_days: int = 365) -> dict[str, Any]:
    if not connected():
        return {"status": "not_connected"}
    try:
        last = db.kv_get("strava.synced_until")
        after = int(last - 3 * 86400) if last else int(
            (datetime.now(timezone.utc) - timedelta(days=backfill_days)).timestamp()
        )
        got = 0
        page = 1
        with db.session() as c:
            while True:
                batch = _get("/athlete/activities", after=after, per_page=100, page=page)
                for a in batch:
                    db.upsert(c, "strava_activities", "id", _row(a))
                got += len(batch)
                if len(batch) < 100:
                    break
                page += 1
            matched = match_garmin(c)
        db.kv_set("strava.synced_until", time.time())
        db.kv_set("strava.last_sync", db.now_iso())
        msg = f"{got} activities fetched, {matched} matched to Garmin"
        db.log("strava", "ok", msg)
        return {"status": "ok", "message": msg}
    except httpx.HTTPStatusError as e:
        msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        db.log("strava", "error", msg)
        return {"status": "error", "message": msg}
    except Exception as e:
        db.log("strava", "error", repr(e))
        return {"status": "error", "message": repr(e)}
