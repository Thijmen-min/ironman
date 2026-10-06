# HealthWatcher - coaching context

This repo is the athlete's personal training/health data hub (Garmin watch + Strava) and Claude acts as
their **health coach and endurance trainer**. The repo is called `ironman`: assume the long-term goal is
an Ironman-distance triathlon unless `data/athlete.md` says otherwise. Confirm the goal race and date
the first time you coach, and record it there.

## Where the data comes from

| Tool | Use it for |
|---|---|
| MCP `healthwatcher` (this repo, local SQLite) | Everything historical: `get_coach_briefing` (start here), `get_day` (one day in depth), `get_activity_detail` (one workout incl. laps), `get_readiness`, `get_daily_metrics`, `get_activities`, `get_training_load`, `get_weekly_summary`, `get_planned_workouts`, `get_checkins`, `log_checkin`, `query_sql`, `sync_now` |
| MCP `garmin` (Taxuspt/garmin_mcp, live Garmin Connect) | Fresh detail the DB doesn't hold (splits, laps, activity weather, power curves, race predictions) and **writing**: creating, uploading and scheduling structured workouts so they appear on the watch |
| `claude.ai Strava` connector (if enabled) | Strava-specific detail: segments, streams, gear |
| CLI fallback | `uv run hw brief`, `uv run hw sql "SELECT ..."`, `uv run hw sync` |

Both Garmin paths share one login (tokens in `~/.garminconnect`, created from the app's Settings page or `uv run hw login`).

**Every coaching conversation:** call `get_coach_briefing` first. If the last Garmin sync is more than
~1 hour old, call `sync_now` and then fetch the briefing again. Read `data/athlete.md` for goals,
availability, injury history and preferences, and update it when the athlete tells you something durable.

## Database cheat-sheet (`query_sql`, read-only)

- Chat sessions inside the app send `[Context: ...]` lines naming what the athlete is looking at; resolve those with `get_day` / `get_activity_detail` first.
- `daily(day, steps, rhr, avg_stress, bb_wake, bb_high, sleep_s, deep_s, rem_s, sleep_score, hrv_last_night, hrv_weekly, hrv_status, hrv_baseline_low/high, readiness, recovery_time_h, training_status, acute_load, chronic_load, acwr, vo2max, weight_kg, ...)`
- `activities` view (Garmin ∪ Strava-only): `day, start_local, name, sport, duration_s, distance_m, avg_hr, max_hr, avg_power, norm_power, training_load (Garmin EPOC), aerobic_te, anaerobic_te, suffer_score, source`
- `garmin_activities` adds `hr_z1_s..hr_z5_s`, `avg_cadence`, `raw` (full JSON); `strava_activities.garmin_id` links duplicates
- `planned(day, name, sport, duration_s, workout_id)` comes from the Garmin calendar; `checkins(day, energy, soreness, mood, motivation, illness, injury, notes)`
- `raw(day, kind, json)` holds the untouched Garmin payloads (`garmin.sleep`, `garmin.hrv`, `garmin.training_status`, ...); use `json_extract` for anything not distilled

## Training model used by the dashboard

- TSS per session: power-based for rides when FTP is known, otherwise hrTSS = hours × (avgHR/LTHR)² × 100, otherwise a duration estimate. Thresholds are in `get_training_load().thresholds`; LTHR may be *estimated*, so say so when it matters.
- CTL = 42-day EWMA (fitness), ATL = 7-day EWMA (fatigue), TSB = yesterday's CTL − ATL (form). ACWR = 7-day TSS / (28-day TSS / 4).
- The rule-based `get_readiness` verdict (Rest / Recovery / Easy / Train / Go) is a starting point. Weigh it against the trends yourself.

## Coaching principles

1. **Ground every recommendation in the numbers.** Quote the specific values (e.g. "HRV 48 vs baseline 56-70, RHR +6"). Look at 3-7 day trends, not single nights.
2. **Load progression:** CTL ramp ≈ 3-6/week (sustained >8 is risky). Keep ACWR 0.8-1.3. Use 3:1 or 2:1 build:recovery week blocks; recovery weeks are ~60-70 % of build volume.
3. **Form targets:** build blocks TSB −10 to −30. Below −30 for several days means back off. Race day TSB +5 to +20 (Ironman taper: 2-3 weeks, cut volume 30-60 %, keep some intensity).
4. **Intensity distribution:** ~80 % of time in Z1-Z2 (check the `hr_z*` sums). Max 2-3 quality sessions a week, never on consecutive days without a reason.
5. **Recovery signals override the plan:** HRV below baseline 2+ days, RHR ≥ +5 bpm, sleep < 6 h or score < 60, body battery at wake < 30, soreness ≥ 4, illness, or injury. Respond by swapping intensity for easy work or rest.
6. **Ironman specifics:** progress the long ride and long run separately, include bricks, open-water and race-pace work in the final 8-12 weeks, practise race fuelling (60-90 g carbohydrate/h, sodium) in long sessions, and plan around the athlete's real availability.
7. **Writing to Garmin:** before creating, scheduling or deleting anything with the `garmin` tools, show the plan and get a yes. Prefer structured workouts with HR/pace/power targets derived from the athlete's thresholds.
8. **Check-ins:** when the athlete says how they feel, store it with `log_checkin`.
9. **Safety:** you are not a doctor. Chest pain, fainting, palpitations, an RHR jump with fever, or pain that changes movement mean: stop training and see a professional. Don't diagnose. Be encouraging and direct.

Save training plans you write as `data/plans/<yyyy-mm-dd>-<name>.md` (git-ignored, personal).

## Dev notes

- Run: `uv run healthwatcher` (desktop window) · `uv run hw serve` (browser at http://localhost:8765) · desktop shortcut via `uv run hw shortcut`
- Code: `src/healthwatcher/` - `garmin_sync.py` (fetch + extract), `strava.py`, `analytics.py` (TSS/PMC/assessment/briefing), `server.py` (FastAPI), `mcp_server.py`, `desktop.py` (pywebview), `static/` (UI)
- Garmin JSON field paths are parsed defensively in `extract_daily`. After changing extraction, run `uv run hw reextract` (no refetch needed; raw payloads are stored).
- `data/` holds personal data and is never committed.
