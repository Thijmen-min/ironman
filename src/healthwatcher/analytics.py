"""Training-load model (TSS / CTL / ATL / TSB), recovery assessment and coach briefing."""

import os
import statistics
from datetime import date, datetime, timedelta
from typing import Any

from . import db
from .garmin_sync import pick

CTL_DAYS, ATL_DAYS = 42, 7

SPORT_GROUPS = ["Run", "Bike", "Swim", "Strength", "Walk/Hike", "Other"]
_SPORT_MAP = {
    "Run": ("run", "Run", "TrailRun", "VirtualRun"),
    "Bike": ("cycl", "bik", "Ride", "virtual_ride", "VirtualRide", "Velomobile", "Handcycle"),
    "Swim": ("swim", "Swim"),
    "Strength": ("strength", "WeightTraining", "Crossfit", "hiit", "HighIntensityIntervalTraining", "fitness_equipment"),
    "Walk/Hike": ("walk", "hik", "Walk", "Hike"),
}
# Used when a session has neither power nor heart rate (TSS per hour).
_DEFAULT_TSS_PER_H = {"Run": 60, "Bike": 50, "Swim": 55, "Strength": 40, "Walk/Hike": 25, "Other": 35}


def sport_group(sport: str | None) -> str:
    s = sport or ""
    for group, keys in _SPORT_MAP.items():
        if any(k.lower() in s.lower() for k in keys):
            return group
    return "Other"


# ---------------------------------------------------------------- thresholds


def _env_float(name: str) -> float | None:
    try:
        return float(os.getenv(name, ""))
    except ValueError:
        return None


def thresholds() -> dict[str, Any]:
    """Training thresholds. Precedence: Profile tab > .env > Garmin > estimate."""
    from . import profile as athlete

    pth = athlete.get()["thresholds"]
    prof = db.kv_get("garmin.profile") or {}
    lt = prof.get("lactate_threshold") or {}
    ftp_data = prof.get("ftp") or {}

    def first(*cands):
        for value, source in cands:
            if value not in (None, "", 0):
                return float(value), source
        return None, None

    max_hr_obs = db.rows(
        "SELECT max_hr FROM activities WHERE max_hr IS NOT NULL AND day >= date('now','-365 day') ORDER BY max_hr DESC LIMIT 5"
    )
    max_hr, max_src = first((pth.get("max_hr_run"), "profile"), (_env_float("HW_MAX_HR"), "env"),
                            (statistics.median([r["max_hr"] for r in max_hr_obs]) if max_hr_obs else None, "observed"))
    max_bike, _ = first((pth.get("max_hr_bike"), "profile"))
    lthr, lthr_src = first((pth.get("lthr_run"), "profile"), (_env_float("HW_LTHR"), "env"),
                           (pick(lt, "speed_and_heart_rate.heartRate", "heartRate", "lactateThresholdHeartRate"), "garmin"))
    if not lthr and max_hr:
        lthr, lthr_src = round(max_hr * 0.89), "estimated (89% of max HR)"
    if not lthr:
        lthr, lthr_src = 170.0, "default"
    lthr_bike, lthr_bike_src = first((pth.get("lthr_bike"), "profile"))
    if not lthr_bike and max_bike:
        lthr_bike, lthr_bike_src = round(max_bike * 0.89), "estimated (89% of bike max HR)"
    if not lthr_bike:
        lthr_bike, lthr_bike_src = lthr, "same as run"
    ftp, ftp_src = first((pth.get("ftp_w"), "profile"), (_env_float("HW_FTP"), "env"),
                         (pick(ftp_data, "functionalThresholdPower", "ftp"), "garmin"))
    rhr = db.rows("SELECT AVG(rhr) v FROM daily WHERE rhr IS NOT NULL AND day >= date('now','-30 day')")
    return {
        "lthr": lthr, "lthr_source": lthr_src,
        "lthr_bike": lthr_bike, "lthr_bike_source": lthr_bike_src,
        "ftp": ftp, "ftp_source": ftp_src,
        "max_hr": max_hr, "max_hr_source": max_src,
        "rhr_30d": round(rhr[0]["v"], 1) if rhr and rhr[0]["v"] else None,
        "sleep_target_h": _env_float("HW_SLEEP_TARGET_H") or 8.0,
    }


def activity_tss(a: dict[str, Any], th: dict[str, Any]) -> tuple[float, str]:
    secs = a.get("moving_s") or a.get("duration_s") or 0
    hours = secs / 3600
    group = sport_group(a.get("sport"))
    power = a.get("norm_power") or a.get("avg_power")
    if group == "Bike" and power and th.get("ftp"):
        intensity = power / th["ftp"]
        return round(hours * intensity * intensity * 100, 1), "power"
    lthr = th.get("lthr_bike") if group == "Bike" else th.get("lthr")
    if a.get("avg_hr") and lthr:
        intensity = min(a["avg_hr"] / lthr, 1.15)
        return round(hours * intensity * intensity * 100, 1), "hr"
    return round(hours * _DEFAULT_TSS_PER_H[group], 1), "duration"


# ---------------------------------------------------------------- loaders


def load_activities(start: str, end: str) -> list[dict[str, Any]]:
    th = thresholds()
    acts = db.rows(
        """SELECT a.*, g.hr_z1_s, g.hr_z2_s, g.hr_z3_s, g.hr_z4_s, g.hr_z5_s, g.avg_cadence
           FROM activities a LEFT JOIN garmin_activities g ON g.id = a.garmin_id
           WHERE a.day BETWEEN ? AND ? ORDER BY a.start_local""",
        (start, end),
    )
    for a in acts:
        a["tss"], a["tss_method"] = activity_tss(a, th)
        a["group"] = sport_group(a["sport"])
    return acts


def load_daily(start: str, end: str) -> dict[str, dict[str, Any]]:
    return {r["day"]: r for r in db.rows("SELECT * FROM daily WHERE day BETWEEN ? AND ? ORDER BY day", (start, end))}


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ---------------------------------------------------------------- PMC


def pmc(start: str, end: str, metric: str = "tss") -> list[dict[str, Any]]:
    """Performance Management Chart series. Warm-up begins 120 days before `start`."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    warm = s - timedelta(days=120)
    today = date.today()
    acts = load_activities(warm.isoformat(), min(e, today).isoformat())
    by_day: dict[str, float] = {}
    for a in acts:
        v = a["tss"] if metric == "tss" else (a.get("training_load") or a["tss"])
        by_day[a["day"]] = by_day.get(a["day"], 0) + v
    planned = {}
    if e > today:
        for p in db.rows("SELECT day, sport, duration_s, planned_tss FROM planned WHERE day > ? AND day <= ?", (today.isoformat(), end)):
            hours = (p["duration_s"] or 3600) / 3600
            planned[p["day"]] = planned.get(p["day"], 0) + (p["planned_tss"] or hours * _DEFAULT_TSS_PER_H[sport_group(p["sport"])])
    ctl = atl = 0.0
    out = []
    for d in _days(warm, e):
        ds = d.isoformat()
        future = d > today
        load = planned.get(ds, 0) if future else by_day.get(ds, 0)
        tsb = ctl - atl  # form = yesterday's fitness - yesterday's fatigue
        ctl += (load - ctl) / CTL_DAYS
        atl += (load - atl) / ATL_DAYS
        if d >= s:
            out.append({
                "day": ds, "tss": round(load, 1), "ctl": round(ctl, 1), "atl": round(atl, 1),
                "tsb": round(tsb, 1), "projected": future,
            })
    return out


def load_metrics(pmc_rows: list[dict[str, Any]]) -> dict[str, Any]:
    real = [r for r in pmc_rows if not r["projected"]]
    if not real:
        return {}
    last = real[-1]
    wk = real[-8] if len(real) >= 8 else real[0]
    last7 = sum(r["tss"] for r in real[-7:])
    last28 = sum(r["tss"] for r in real[-28:])
    return {
        "ctl": last["ctl"], "atl": last["atl"], "tsb": last["tsb"],
        "ramp_rate": round(last["ctl"] - wk["ctl"], 1),
        "tss_7d": round(last7), "tss_28d": round(last28),
        "acwr": round(last7 / (last28 / 4), 2) if last28 else None,
    }


def form_zone(tsb: float) -> str:
    if tsb > 25: return "Transition (detraining)"
    if tsb > 5: return "Fresh"
    if tsb > -10: return "Neutral"
    if tsb > -30: return "Optimal training"
    return "High risk (overreaching)"


# ---------------------------------------------------------------- recovery


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else None


def _sd(vals):
    vals = [v for v in vals if v is not None]
    return statistics.pstdev(vals) if len(vals) > 3 else None


def assessment(day: str | None = None) -> dict[str, Any]:
    """Rule-based readiness verdict + the flags behind it."""
    d = date.fromisoformat(day) if day else date.today()
    daily = load_daily((d - timedelta(days=90)).isoformat(), d.isoformat())
    today = daily.get(d.isoformat()) or {}
    yday = daily.get((d - timedelta(days=1)).isoformat()) or {}
    hist = [v for k, v in daily.items() if k < d.isoformat()]
    hist30 = hist[-30:]
    lm = load_metrics(pmc((d - timedelta(days=30)).isoformat(), d.isoformat()))
    checkin = (db.rows("SELECT * FROM checkins WHERE day=?", (d.isoformat(),)) or [{}])[0]
    th = thresholds()
    flags: list[dict[str, str]] = []

    def flag(level, metric, msg):
        flags.append({"level": level, "metric": metric, "message": msg})

    hrv = today.get("hrv_last_night")
    if hrv:
        lo, hi = today.get("hrv_baseline_low"), today.get("hrv_baseline_high")
        if not lo:
            m, sd = _mean(h.get("hrv_last_night") for h in hist[-60:]), _sd(h.get("hrv_last_night") for h in hist[-60:])
            lo, hi = (m - sd, m + sd) if m and sd else (None, None)
        if lo and hrv < lo:
            flag("serious" if hrv < lo * 0.9 else "warning", "HRV", f"HRV {hrv:.0f} ms is below your baseline ({lo:.0f}-{hi:.0f})")
        elif lo:
            flag("good", "HRV", f"HRV {hrv:.0f} ms within/above baseline ({lo:.0f}-{hi:.0f})")
    rhr, rhr_m = today.get("rhr"), _mean(h.get("rhr") for h in hist30)
    if rhr and rhr_m:
        delta = rhr - rhr_m
        if delta >= 5:
            flag("serious", "Resting HR", f"Resting HR {rhr} is {delta:+.0f} bpm vs 30-day avg - possible fatigue/illness")
        elif delta >= 3:
            flag("warning", "Resting HR", f"Resting HR {rhr} is {delta:+.0f} bpm vs 30-day avg")
        else:
            flag("good", "Resting HR", f"Resting HR {rhr} ({delta:+.0f} vs 30-day avg)")
    sleep_h = (today.get("sleep_s") or 0) / 3600
    if sleep_h:
        score = today.get("sleep_score")
        if sleep_h < 6 or (score and score < 60):
            flag("warning", "Sleep", f"Short/poor sleep: {sleep_h:.1f} h, score {score or '-'}")
        else:
            flag("good", "Sleep", f"Slept {sleep_h:.1f} h, score {score or '-'}")
        week = [h.get("sleep_s") for h in hist[-6:]] + [today.get("sleep_s")]
        debt = sum(th["sleep_target_h"] - (s or 0) / 3600 for s in week if s)
        if debt > 5:
            flag("warning", "Sleep debt", f"~{debt:.0f} h sleep debt over the last 7 nights")
    bb = today.get("bb_wake") or today.get("bb_high")
    if bb is not None:
        if bb < 30:
            flag("serious", "Body Battery", f"Woke with Body Battery {bb}")
        elif bb < 50:
            flag("warning", "Body Battery", f"Woke with Body Battery {bb}")
    if yday.get("avg_stress") and yday["avg_stress"] >= 40:
        flag("warning", "Stress", f"High average stress yesterday ({yday['avg_stress']})")
    if lm:
        if lm["tsb"] < -30:
            flag("critical", "Form", f"Form (TSB) {lm['tsb']:.0f} - deep fatigue, overreaching risk")
        elif lm["tsb"] < -20:
            flag("warning", "Form", f"Form (TSB) {lm['tsb']:.0f} - carrying significant fatigue")
        if lm.get("acwr") and lm["acwr"] > 1.5:
            flag("serious", "Load spike", f"Acute:chronic ratio {lm['acwr']} - load rising too fast (>1.5)")
        elif lm.get("acwr") and lm["acwr"] > 1.3:
            flag("warning", "Load spike", f"Acute:chronic ratio {lm['acwr']} (>1.3)")
        if lm["ramp_rate"] > 8:
            flag("warning", "Ramp rate", f"Fitness ramping +{lm['ramp_rate']} CTL/week (>8 is aggressive)")
    if checkin.get("illness"):
        flag("critical", "Illness", "You logged feeling ill")
    if checkin.get("injury"):
        flag("critical", "Injury", f"Injury logged: {checkin['injury']}")
    if (checkin.get("soreness") or 0) >= 4:
        flag("warning", "Soreness", f"Soreness {checkin['soreness']}/5")

    has_data = bool(today or hist or (lm and lm.get("tss_28d")))
    if not has_data:
        return {
            "day": d.isoformat(), "verdict": "No data", "advice": "Connect Garmin and wait for the first sync.",
            "flags": [], "garmin_readiness": None, "garmin_readiness_level": None, "load": lm, "form_zone": None,
        }
    n_crit = sum(f["level"] == "critical" for f in flags)
    n_serious = sum(f["level"] == "serious" for f in flags)
    n_warn = sum(f["level"] == "warning" for f in flags)
    if n_crit or n_serious >= 2:
        verdict, advice = "Rest", "Take a rest day or very light mobility. Re-assess tomorrow."
    elif n_serious or n_warn >= 3:
        verdict, advice = "Recovery", "Short, easy Z1-Z2 only (<45 min) or rest. No intensity."
    elif n_warn >= 1:
        verdict, advice = "Easy / moderate", "Aerobic Z2 is fine; postpone hard intervals unless you feel great."
    elif lm and lm["tsb"] > -10:
        verdict, advice = "Go", "Recovered - a good day for a key session (intervals, tempo, long effort)."
    else:
        verdict, advice = "Train", "Normal training. Hard session OK if it is planned."
    return {
        "day": d.isoformat(), "verdict": verdict, "advice": advice, "flags": flags,
        "garmin_readiness": today.get("readiness"), "garmin_readiness_level": today.get("readiness_level"),
        "load": lm, "form_zone": form_zone(lm["tsb"]) if lm else None,
    }


# ---------------------------------------------------------------- weekly


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weekly(start: str, end: str) -> list[dict[str, Any]]:
    s, e = week_start(date.fromisoformat(start)), date.fromisoformat(end)
    acts = load_activities(s.isoformat(), e.isoformat())
    p = {r["day"]: r for r in pmc(s.isoformat(), (week_start(e) + timedelta(days=6)).isoformat())}
    daily = load_daily(s.isoformat(), e.isoformat())
    weeks: dict[str, dict[str, Any]] = {}
    for d in _days(s, week_start(e)):
        if d.weekday() == 0:
            end_day = min(d + timedelta(days=6), date.today()).isoformat()
            last = p.get(end_day, {})
            weeks[d.isoformat()] = {
                "week": d.isoformat(), "tss": 0.0, "duration_s": 0.0, "distance_m": 0.0, "count": 0,
                "by_sport": {g: {"tss": 0.0, "duration_s": 0.0, "distance_m": 0.0, "count": 0} for g in SPORT_GROUPS},
                "zones_s": [0.0] * 5,
                "ctl": last.get("ctl"), "atl": last.get("atl"), "tsb": last.get("tsb"),
            }
    for a in acts:
        w = weeks.get(week_start(date.fromisoformat(a["day"])).isoformat())
        if not w:
            continue
        for tgt in (w, w["by_sport"][a["group"]]):
            tgt["tss"] += a["tss"]
            tgt["duration_s"] += a["duration_s"] or 0
            tgt["distance_m"] += a["distance_m"] or 0
            tgt["count"] += 1
        for i in range(5):
            w["zones_s"][i] += a.get(f"hr_z{i + 1}_s") or 0
    plans = {r["week"]: r for r in db.rows("SELECT * FROM plan_weeks WHERE week BETWEEN ? AND ?", (s.isoformat(), e.isoformat()))}
    for p in db.rows("SELECT day, sport, duration_s, planned_tss FROM planned WHERE day BETWEEN ? AND ?",
                     (s.isoformat(), (week_start(e) + timedelta(days=6)).isoformat())):
        w = weeks.get(week_start(date.fromisoformat(p["day"])).isoformat())
        if w is not None:
            hours = (p["duration_s"] or 0) / 3600
            w["planned_sessions_s"] = w.get("planned_sessions_s", 0) + (p["duration_s"] or 0)
            w["planned_sessions_tss"] = round(w.get("planned_sessions_tss", 0) + (p["planned_tss"] or hours * _DEFAULT_TSS_PER_H[sport_group(p["sport"])]))
    for wk, w in weeks.items():
        w["plan"] = plans.get(wk)
        days = [daily.get((date.fromisoformat(wk) + timedelta(days=i)).isoformat()) or {} for i in range(7)]
        w["sleep_h_avg"] = _round(_mean((x.get("sleep_s") or 0) / 3600 or None for x in days), 1)
        w["hrv_avg"] = _round(_mean(x.get("hrv_last_night") for x in days))
        w["rhr_avg"] = _round(_mean(x.get("rhr") for x in days))
        w["tss"] = round(w["tss"])
    return list(weeks.values())


def _round(v, n=0):
    return None if v is None else round(v, n) if n else round(v)


# ---------------------------------------------------------------- briefing


def _fmt_dur(s):
    if not s:
        return "-"
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}"


def _km(m):
    return f"{m / 1000:.1f}" if m else "-"


def briefing(days: int = 14) -> str:
    """Markdown snapshot of everything relevant for coaching decisions."""
    today = date.today()
    t = today.isoformat()
    th = thresholds()
    prof = db.kv_get("garmin.profile") or {}
    a = assessment()
    lm = a["load"] or {}
    daily = load_daily((today - timedelta(days=90)).isoformat(), t)
    latest = next((daily[k] for k in sorted(daily, reverse=True) if daily[k].get("vo2max")), {})
    weight = next((daily[k]["weight_kg"] for k in sorted(daily, reverse=True) if daily[k].get("weight_kg")), None)
    from . import profile as athlete

    out = [f"# Athlete briefing - {t}", "", athlete.to_markdown(), ""]
    out += [
        "## Measured (Garmin) & thresholds in use",
        f"- Name: {prof.get('name') or '-'}; units: {prof.get('units') or '-'}",
        f"- LTHR {th['lthr']} bpm ({th['lthr_source']}); FTP {th['ftp'] or 'unknown'} W; max HR {th['max_hr'] or '-'}; 30d resting HR {th['rhr_30d'] or '-'}",
        f"- VO2max {latest.get('vo2max') or '-'} (cycling {latest.get('vo2max_cycling') or '-'}); weight {weight or '-'} kg",
        f"- Garmin training status: {latest.get('training_status') or '-'}; load balance: {latest.get('load_balance_feedback') or '-'}",
        "",
        "## Today's assessment",
        f"**{a['verdict']}** - {a['advice']}",
        f"- Garmin training readiness: {a['garmin_readiness'] or '-'} ({a['garmin_readiness_level'] or '-'})",
    ]
    out += [f"- [{f['level']}] {f['metric']}: {f['message']}" for f in a["flags"]]
    out += [
        "",
        "## Training load (TSS-based PMC)",
        f"- Fitness CTL {lm.get('ctl')}, Fatigue ATL {lm.get('atl')}, Form TSB {lm.get('tsb')} -> {a['form_zone']}",
        f"- Ramp rate {lm.get('ramp_rate')} CTL/wk; TSS last 7d {lm.get('tss_7d')}, last 28d {lm.get('tss_28d')}; ACWR {lm.get('acwr')}",
        "",
        f"## Last {days} days",
        "| Day | Sleep h | Score | HRV | RHR | BB wake | Stress | Readiness | TSS | Sessions |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    acts = load_activities((today - timedelta(days=days)).isoformat(), t)
    for d in _days(today - timedelta(days=days - 1), today):
        ds = d.isoformat()
        r = daily.get(ds, {})
        dacts = [x for x in acts if x["day"] == ds]
        out.append(
            f"| {ds} {d.strftime('%a')} | {(r.get('sleep_s') or 0) / 3600:.1f} | {r.get('sleep_score') or '-'} | "
            f"{r.get('hrv_last_night') or '-'} | {r.get('rhr') or '-'} | {r.get('bb_wake') or '-'} | "
            f"{r.get('avg_stress') or '-'} | {r.get('readiness') or '-'} | {round(sum(x['tss'] for x in dacts)) or '-'} | "
            f"{', '.join(x['group'] for x in dacts) or '-'} |"
        )
    out += ["", "## Weekly summary (last 8 weeks)",
            "| Week | TSS | Time | km | Sessions | CTL | TSB | Sleep avg | HRV avg | RHR avg |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for w in weekly((today - timedelta(weeks=7)).isoformat(), t):
        out.append(
            f"| {w['week']} | {w['tss']} | {_fmt_dur(w['duration_s'])} | {_km(w['distance_m'])} | {w['count']} | "
            f"{w['ctl']} | {w['tsb']} | {w['sleep_h_avg'] or '-'} | {w['hrv_avg'] or '-'} | {w['rhr_avg'] or '-'} |"
        )
    out += ["", "## Recent sessions (21 days)",
            "| Date | Sport | Name | Time | km | Avg HR | Power | TSS | Garmin load | Aer/Ana TE | Source |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in reversed(load_activities((today - timedelta(days=21)).isoformat(), t)):
        out.append(
            f"| {x['start_local']} | {x['sport']} | {x['name']} | {_fmt_dur(x['duration_s'])} | {_km(x['distance_m'])} | "
            f"{_round(x['avg_hr']) or '-'} | {_round(x['norm_power'] or x['avg_power']) or '-'} | {round(x['tss'])} ({x['tss_method']}) | "
            f"{_round(x['training_load']) or '-'} | {x['aerobic_te'] or '-'}/{x['anaerobic_te'] or '-'} | "
            f"{x['source']}{'+strava' if x['source'] == 'garmin' and x['strava_id'] else ''} |"
        )
    planned = db.rows("SELECT * FROM planned WHERE day >= ? AND day <= ? ORDER BY day", (t, (today + timedelta(days=14)).isoformat()))
    out += ["", "## Planned (next 14 days, Garmin calendar)"]
    out += [f"- {p['day']}: {p['sport'] or ''} - {p['name']} ({_fmt_dur(p['duration_s'])})" for p in planned] or ["- nothing scheduled"]
    checks = db.rows("SELECT * FROM checkins WHERE day >= ? ORDER BY day", ((today - timedelta(days=days)).isoformat(),))
    out += ["", "## Subjective check-ins"]
    out += [
        f"- {c['day']}: energy {c['energy'] or '-'}/5, soreness {c['soreness'] or '-'}/5, mood {c['mood'] or '-'}/5, "
        f"motivation {c['motivation'] or '-'}/5{', ILL' if c['illness'] else ''}"
        f"{', injury: ' + c['injury'] if c['injury'] else ''}{' - ' + c['notes'] if c['notes'] else ''}"
        for c in checks
    ] or ["- none logged"]
    h90 = list(daily.values())
    out += [
        "", "## 90-day baselines",
        f"- HRV mean {_round(_mean(r.get('hrv_last_night') for r in h90))}, RHR mean {_round(_mean(r.get('rhr') for r in h90), 1)}, "
        f"sleep mean {_round(_mean((r.get('sleep_s') or 0) / 3600 or None for r in h90), 1)} h, "
        f"sleep score mean {_round(_mean(r.get('sleep_score') for r in h90))}, stress mean {_round(_mean(r.get('avg_stress') for r in h90))}",
        "",
        f"_Last Garmin sync: {db.kv_get('garmin.last_sync') or 'never'}; last Strava sync: {db.kv_get('strava.last_sync') or 'never'}_",
    ]
    return "\n".join(out)
