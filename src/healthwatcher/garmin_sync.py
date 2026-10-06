"""Pull data from Garmin Connect into the local database."""

import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from . import db
from .config import BACKFILL_DAYS, DATA_DIR, GARMIN_TOKENS, INTRADAY_DAYS

log = logging.getLogger(__name__)

CALL_PAUSE_S = 0.35  # be polite to Garmin; avoids 429s during backfill

STATE: dict[str, Any] = {"running": False, "phase": "", "done": 0, "total": 0}
_lock = threading.Lock()
_api: Garmin | None = None
_pending_login: Garmin | None = None  # holds a login waiting for its MFA code


class NotAuthenticated(Exception):
    pass


# ---------------------------------------------------------------- auth


def has_tokens() -> bool:
    p = Path(GARMIN_TOKENS)
    return (p / "garmin_tokens.json").exists() if p.is_dir() or not p.suffix else p.exists()


def client() -> Garmin:
    """Return a logged-in client, resuming from saved tokens."""
    global _api
    if _api is not None:
        return _api
    if not has_tokens():
        raise NotAuthenticated("No Garmin tokens yet - log in from the app (Settings).")
    api = Garmin()
    try:
        api.login(GARMIN_TOKENS)
    except GarminConnectAuthenticationError as e:
        raise NotAuthenticated(str(e)) from e
    _api = api
    return api


def start_login(email: str, password: str) -> str:
    """Begin a credential login. Returns 'ok' or 'needs_mfa'."""
    global _pending_login, _api
    os.makedirs(GARMIN_TOKENS, exist_ok=True)
    api = Garmin(email, password, return_on_mfa=True)
    status, _ = api.login()
    if status == "needs_mfa":
        _pending_login = api
        return "needs_mfa"
    api.client.dump(GARMIN_TOKENS)
    _api = None
    client()
    return "ok"


def finish_login(code: str) -> str:
    global _pending_login, _api
    if _pending_login is None:
        raise NotAuthenticated("No login in progress.")
    api = _pending_login
    api.resume_login(None, code.strip())
    api.client.dump(GARMIN_TOKENS)
    _pending_login = None
    _api = api
    return "ok"


def logout() -> None:
    global _api
    _api = None
    f = Path(GARMIN_TOKENS) / "garmin_tokens.json"
    if f.exists():
        f.unlink()


# ---------------------------------------------------------------- helpers


def pick(d: Any, *paths: str, default: Any = None) -> Any:
    """First non-None value among dotted paths, e.g. pick(x, 'a.b', 'c')."""
    for path in paths:
        cur = d
        for part in path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                cur = None
            if cur is None:
                break
        if cur is not None:
            return cur
    return default


def _primary_device_entry(m: Any) -> dict:
    """Garmin keys some metrics by device id; take the primary device's entry."""
    if not isinstance(m, dict) or not m:
        return {}
    vals = [v for v in m.values() if isinstance(v, dict)]
    for v in vals:
        if v.get("primaryTrainingDevice"):
            return v
    return vals[0] if vals else {}


def _ts_local(ms: Any) -> str | None:
    if not ms:
        return None
    # Garmin "Local" timestamps are epoch-ms of the local wall clock.
    return datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _call(fn: Callable, *args: Any) -> Any:
    try:
        return fn(*args)
    except GarminConnectTooManyRequestsError:
        raise
    except GarminConnectAuthenticationError as e:
        raise NotAuthenticated(str(e)) from e
    except Exception as e:  # missing data for a day is normal (404 / empty)
        log.debug("%s%s failed: %s", fn.__name__, args, e)
        return None
    finally:
        time.sleep(CALL_PAUSE_S)


# ---------------------------------------------------------------- extraction


def extract_daily(c, day: str) -> dict[str, Any]:
    s = db.get_raw(c, day, "garmin.summary") or {}
    sl = db.get_raw(c, day, "garmin.sleep") or {}
    hrv = db.get_raw(c, day, "garmin.hrv") or {}
    rd = db.get_raw(c, day, "garmin.readiness")
    ts = db.get_raw(c, day, "garmin.training_status") or {}

    sleep = sl.get("dailySleepDTO") or {}
    hs = hrv.get("hrvSummary") or {}
    if isinstance(rd, list) and rd:
        rd = max(rd, key=lambda r: r.get("timestamp") or "")
    rd = rd if isinstance(rd, dict) else {}
    status = _primary_device_entry(pick(ts, "mostRecentTrainingStatus.latestTrainingStatusData"))
    acute = status.get("acuteTrainingLoadDTO") or {}
    balance = _primary_device_entry(
        pick(ts, "mostRecentTrainingLoadBalance.metricsTrainingLoadBalanceDTOMap")
    )
    rec_min = pick(rd, "recoveryTime")

    return {
        "day": day,
        "steps": s.get("totalSteps"),
        "distance_m": s.get("totalDistanceMeters"),
        "floors": s.get("floorsAscended"),
        "total_kcal": s.get("totalKilocalories"),
        "active_kcal": s.get("activeKilocalories"),
        "intensity_mod_min": s.get("moderateIntensityMinutes"),
        "intensity_vig_min": s.get("vigorousIntensityMinutes"),
        "rhr": pick(s, "restingHeartRate") or pick(sl, "restingHeartRate"),
        "min_hr": s.get("minHeartRate"),
        "max_hr": s.get("maxHeartRate"),
        "avg_stress": s.get("averageStressLevel") if (s.get("averageStressLevel") or -1) >= 0 else None,
        "max_stress": s.get("maxStressLevel") if (s.get("maxStressLevel") or -1) >= 0 else None,
        "stress_high_min": round(s["highStressDuration"] / 60) if s.get("highStressDuration") else None,
        "rest_stress_min": round(s["restStressDuration"] / 60) if s.get("restStressDuration") else None,
        "bb_high": s.get("bodyBatteryHighestValue"),
        "bb_low": s.get("bodyBatteryLowestValue"),
        "bb_charged": s.get("bodyBatteryChargedValue"),
        "bb_drained": s.get("bodyBatteryDrainedValue"),
        "bb_wake": s.get("bodyBatteryAtWakeTime"),
        "bb_latest": s.get("bodyBatteryMostRecentValue"),
        "spo2_avg": s.get("averageSpo2"),
        "resp_avg": s.get("avgWakingRespirationValue"),
        "sleep_s": sleep.get("sleepTimeSeconds"),
        "deep_s": sleep.get("deepSleepSeconds"),
        "light_s": sleep.get("lightSleepSeconds"),
        "rem_s": sleep.get("remSleepSeconds"),
        "awake_s": sleep.get("awakeSleepSeconds"),
        "sleep_score": pick(sleep, "sleepScores.overall.value"),
        "sleep_quality": pick(sleep, "sleepScores.overall.qualifierKey"),
        "sleep_start": _ts_local(sleep.get("sleepStartTimestampLocal")),
        "sleep_end": _ts_local(sleep.get("sleepEndTimestampLocal")),
        "sleep_stress": sleep.get("avgSleepStress"),
        "sleep_resp": sleep.get("averageRespirationValue"),
        "sleep_spo2": sleep.get("averageSpO2Value"),
        "sleep_bb_change": sl.get("bodyBatteryChange"),
        "hrv_last_night": hs.get("lastNightAvg") or sl.get("avgOvernightHrv"),
        "hrv_weekly": hs.get("weeklyAvg"),
        "hrv_5min_high": hs.get("lastNight5MinHigh"),
        "hrv_status": hs.get("status") or sl.get("hrvStatus"),
        "hrv_baseline_low": pick(hs, "baseline.balancedLow"),
        "hrv_baseline_high": pick(hs, "baseline.balancedUpper"),
        "readiness": rd.get("score"),
        "readiness_level": rd.get("level"),
        "readiness_feedback": rd.get("feedbackShort"),
        "recovery_time_h": round(rec_min / 60, 1) if isinstance(rec_min, (int, float)) else None,
        "training_status": status.get("trainingStatusFeedbackPhrase"),
        "acute_load": acute.get("dailyTrainingLoadAcute"),
        "chronic_load": acute.get("dailyTrainingLoadChronic"),
        "acwr": acute.get("dailyAcuteChronicWorkloadRatio"),
        "acwr_status": acute.get("acwrStatus"),
        "load_aerobic_low": balance.get("monthlyLoadAerobicLow"),
        "load_aerobic_high": balance.get("monthlyLoadAerobicHigh"),
        "load_anaerobic": balance.get("monthlyLoadAnaerobic"),
        "load_balance_feedback": balance.get("trainingBalanceFeedbackPhrase"),
        "vo2max": pick(ts, "mostRecentVO2Max.generic.vo2MaxPreciseValue", "mostRecentVO2Max.generic.vo2MaxValue"),
        "vo2max_cycling": pick(ts, "mostRecentVO2Max.cycling.vo2MaxPreciseValue", "mostRecentVO2Max.cycling.vo2MaxValue"),
        "fitness_age": pick(ts, "mostRecentVO2Max.generic.fitnessAge"),
        "updated_at": db.now_iso(),
    }


def activity_row(a: dict[str, Any]) -> dict[str, Any]:
    start_local = a.get("startTimeLocal") or ""
    return {
        "id": a.get("activityId"),
        "day": start_local[:10],
        "start_local": start_local[:16],
        "start_utc": (a.get("startTimeGMT") or "")[:19],
        "name": a.get("activityName"),
        "sport": pick(a, "activityType.typeKey"),
        "duration_s": a.get("duration"),
        "moving_s": a.get("movingDuration"),
        "distance_m": a.get("distance"),
        "elev_gain_m": a.get("elevationGain"),
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "avg_speed_ms": a.get("averageSpeed"),
        "avg_power": a.get("avgPower"),
        "norm_power": a.get("normPower"),
        "avg_cadence": pick(a, "averageRunningCadenceInStepsPerMinute", "averageBikingCadenceInRevPerMinute"),
        "calories": a.get("calories"),
        "training_load": a.get("activityTrainingLoad"),
        "aerobic_te": a.get("aerobicTrainingEffect"),
        "anaerobic_te": a.get("anaerobicTrainingEffect"),
        "te_label": a.get("trainingEffectLabel"),
        "vo2max": a.get("vO2MaxValue"),
        "hr_z1_s": a.get("hrTimeInZone_1"),
        "hr_z2_s": a.get("hrTimeInZone_2"),
        "hr_z3_s": a.get("hrTimeInZone_3"),
        "hr_z4_s": a.get("hrTimeInZone_4"),
        "hr_z5_s": a.get("hrTimeInZone_5"),
        "raw": json.dumps(a),
    }


def reextract_all() -> int:
    """Rebuild typed tables from stored raw payloads (after parser changes)."""
    with db.session() as c:
        days = [r[0] for r in c.execute("SELECT DISTINCT day FROM raw WHERE kind LIKE 'garmin.%' AND day != '-'")]
        for d in days:
            row = extract_daily(c, d)
            if any(v is not None for k, v in row.items() if k not in ("day", "updated_at")):
                db.upsert(c, "daily", "day", row)
        _apply_body_comp(c)
    return len(days)


def _apply_body_comp(c) -> None:
    for r in c.execute("SELECT json FROM raw WHERE kind='garmin.body_comp'").fetchall():
        data = json.loads(r[0]) if r[0] else {}
        for w in data.get("dateWeightList") or []:
            d = w.get("calendarDate")
            if not d or not w.get("weight"):
                continue
            c.execute("INSERT OR IGNORE INTO daily(day) VALUES (?)", (d,))
            c.execute(
                "UPDATE daily SET weight_kg=?, body_fat_pct=?, muscle_mass_kg=? WHERE day=?",
                (
                    round(w["weight"] / 1000, 2),
                    w.get("bodyFat"),
                    round(w["muscleMass"] / 1000, 2) if w.get("muscleMass") else None,
                    d,
                ),
            )


# ---------------------------------------------------------------- sync


class _FileLock:
    """Cross-process lock so the app and the scheduled task never sync at once."""

    path = DATA_DIR / "sync.lock"

    def __enter__(self):
        if self.path.exists() and time.time() - self.path.stat().st_mtime < 1800:
            raise RuntimeError("Another sync is already running.")
        self.path.write_text(str(os.getpid()))
        return self

    def touch(self):
        self.path.touch()

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def _days_needing_sync(c, today: date, backfill_days: int) -> list[str]:
    """Days never fetched, or last fetched before they were 'final' (noon the next day)."""
    have = {
        r[0]: r[1]
        for r in c.execute(
            "SELECT day, MIN(fetched_at) FROM raw WHERE kind IN ('garmin.summary','garmin.sleep') GROUP BY day"
        )
    }
    out = []
    for i in range(backfill_days, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        final_at = datetime.combine(d + timedelta(days=1), datetime.min.time()) + timedelta(hours=12)
        if ds not in have or datetime.fromisoformat(have[ds]) < final_at:
            out.append(ds)
    return out


def sync(backfill_days: int | None = None, progress: Callable[[], None] | None = None) -> dict[str, Any]:
    """Incremental sync. First run backfills; later runs only touch non-final days."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy"}
    backfill_days = BACKFILL_DAYS if backfill_days is None else backfill_days
    STATE.update(running=True, phase="login", done=0, total=0, error=None)
    started = time.time()
    try:
        with _FileLock() as flock:
            api = client()
            today = date.today()
            with db.session() as c:
                days = _days_needing_sync(c, today, backfill_days)
            intraday_from = (today - timedelta(days=INTRADAY_DAYS)).isoformat()
            STATE.update(phase="days", total=len(days) + 3)

            for ds in days:
                fetched = {
                    "garmin.summary": _call(api.get_user_summary, ds),
                    "garmin.sleep": _call(api.get_sleep_data, ds),
                    "garmin.hrv": _call(api.get_hrv_data, ds),
                    "garmin.readiness": _call(api.get_training_readiness, ds),
                    "garmin.training_status": _call(api.get_training_status, ds),
                }
                if ds >= intraday_from:
                    fetched["garmin.heart_rates"] = _call(api.get_heart_rates, ds)
                    fetched["garmin.stress"] = _call(api.get_stress_data, ds)
                with db.session() as c:
                    for kind, data in fetched.items():
                        if data is not None or kind in ("garmin.summary", "garmin.sleep"):
                            db.put_raw(c, ds, kind, data)
                    db.upsert(c, "daily", "day", extract_daily(c, ds))
                STATE["done"] += 1
                flock.touch()
                if progress:
                    progress()

            # Activities
            STATE["phase"] = "activities"
            last = db.kv_get("garmin.activities_synced")
            act_from = (
                (date.fromisoformat(last) - timedelta(days=3)).isoformat()
                if last
                else (today - timedelta(days=max(backfill_days, 365))).isoformat()
            )
            acts = _call(api.get_activities_by_date, act_from, today.isoformat()) or []
            with db.session() as c:
                for a in acts:
                    if a.get("activityId"):
                        db.upsert(c, "garmin_activities", "id", activity_row(a))
            db.kv_set("garmin.activities_synced", today.isoformat())
            STATE["done"] += 1

            # Body composition / weight
            STATE["phase"] = "body"
            bc_from = (today - timedelta(days=backfill_days if not last else 30)).isoformat()
            bc = _call(api.get_body_composition, bc_from, today.isoformat())
            with db.session() as c:
                if bc is not None:
                    db.put_raw(c, bc_from, "garmin.body_comp", bc)
                _apply_body_comp(c)
            STATE["done"] += 1

            # Calendar: planned workouts (last month .. next 2 months)
            STATE["phase"] = "calendar"
            sync_calendar(api, today)
            STATE["done"] += 1

            if not db.kv_get("garmin.profile"):
                prof = {
                    "name": api.get_full_name(),
                    "units": api.get_unit_system(),
                    "settings": _call(api.get_userprofile_settings),
                    "hr_zones": _call(api.get_heart_rate_zones),
                    "lactate_threshold": _call(api.get_lactate_threshold),
                    "ftp": _call(api.get_cycling_ftp),
                }
                db.kv_set("garmin.profile", prof)

        msg = f"{len(days)} days, {len(acts)} activities in {time.time() - started:.0f}s"
        db.kv_set("garmin.last_sync", db.now_iso())
        db.log("garmin", "ok", msg)
        return {"status": "ok", "message": msg}
    except NotAuthenticated as e:
        global _api
        _api = None
        db.log("garmin", "auth", str(e))
        STATE["error"] = "auth"
        return {"status": "auth", "message": str(e)}
    except GarminConnectTooManyRequestsError as e:
        db.log("garmin", "rate_limited", str(e))
        STATE["error"] = "Garmin rate limit hit - will continue on the next sync."
        return {"status": "rate_limited", "message": str(e)}
    except Exception as e:
        log.exception("Garmin sync failed")
        db.log("garmin", "error", repr(e))
        STATE["error"] = repr(e)
        return {"status": "error", "message": repr(e)}
    finally:
        STATE.update(running=False, phase="")
        _lock.release()


def sync_calendar(api: Garmin, today: date) -> None:
    months = set()
    for offset in (-31, 0, 31, 62):
        d = today + timedelta(days=offset)
        months.add((d.year, d.month))
    with db.session() as c:
        for y, m in sorted(months):
            cal = _call(api.get_scheduled_workouts, y, m)
            if not cal:
                continue
            db.put_raw(c, f"{y}-{m:02d}-01", "garmin.calendar", cal)
            ids = []
            for item in cal.get("calendarItems") or []:
                if item.get("itemType") in ("activity", "weight", "steps", "healthMetric"):
                    continue
                if not item.get("date"):
                    continue
                pid = f"{item.get('itemType')}:{item.get('id')}"
                ids.append(pid)
                db.upsert(c, "planned", "id", {
                    "id": pid,
                    "day": item["date"],
                    "name": item.get("title"),
                    "sport": item.get("sportTypeKey"),
                    "duration_s": item.get("duration") or item.get("estimatedDurationInSecs"),
                    "distance_m": item.get("distance") or item.get("estimatedDistanceInMeters"),
                    "workout_id": item.get("workoutId"),
                    "item_type": item.get("itemType"),
                    "raw": json.dumps(item),
                })
            # Drop items that were removed from this month in Garmin Connect.
            month_prefix = f"{y}-{m:02d}-%"
            q = "DELETE FROM planned WHERE day LIKE ?"
            if ids:
                q += f" AND id NOT IN ({','.join('?' * len(ids))})"
            c.execute(q, [month_prefix, *ids])
