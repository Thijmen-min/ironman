"""SQLite storage. Raw API payloads are kept verbatim; typed tables are derived."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw (
    day TEXT NOT NULL,           -- YYYY-MM-DD (or '-' for undated payloads)
    kind TEXT NOT NULL,          -- e.g. 'garmin.summary', 'garmin.sleep'
    fetched_at TEXT NOT NULL,
    json TEXT,
    PRIMARY KEY (day, kind)
);

-- One row per calendar day, distilled from Garmin.
CREATE TABLE IF NOT EXISTS daily (
    day TEXT PRIMARY KEY,
    steps INTEGER, distance_m REAL, floors REAL,
    total_kcal REAL, active_kcal REAL,
    intensity_mod_min INTEGER, intensity_vig_min INTEGER,
    rhr INTEGER, min_hr INTEGER, max_hr INTEGER,
    avg_stress INTEGER, max_stress INTEGER, stress_high_min INTEGER, rest_stress_min INTEGER,
    bb_high INTEGER, bb_low INTEGER, bb_charged INTEGER, bb_drained INTEGER, bb_wake INTEGER, bb_latest INTEGER,
    spo2_avg REAL, resp_avg REAL,
    sleep_s INTEGER, deep_s INTEGER, light_s INTEGER, rem_s INTEGER, awake_s INTEGER,
    sleep_score INTEGER, sleep_quality TEXT, sleep_start TEXT, sleep_end TEXT,
    sleep_stress REAL, sleep_resp REAL, sleep_spo2 REAL, sleep_bb_change INTEGER,
    hrv_last_night REAL, hrv_weekly REAL, hrv_5min_high REAL, hrv_status TEXT,
    hrv_baseline_low REAL, hrv_baseline_high REAL,
    readiness INTEGER, readiness_level TEXT, readiness_feedback TEXT, recovery_time_h REAL,
    training_status TEXT, acute_load REAL, chronic_load REAL, acwr REAL, acwr_status TEXT,
    load_aerobic_low REAL, load_aerobic_high REAL, load_anaerobic REAL, load_balance_feedback TEXT,
    vo2max REAL, vo2max_cycling REAL, fitness_age REAL,
    weight_kg REAL, body_fat_pct REAL, muscle_mass_kg REAL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS garmin_activities (
    id INTEGER PRIMARY KEY,
    day TEXT, start_local TEXT, start_utc TEXT,
    name TEXT, sport TEXT,
    duration_s REAL, moving_s REAL, distance_m REAL, elev_gain_m REAL,
    avg_hr REAL, max_hr REAL, avg_speed_ms REAL, avg_power REAL, norm_power REAL,
    avg_cadence REAL, calories REAL,
    training_load REAL, aerobic_te REAL, anaerobic_te REAL, te_label TEXT, vo2max REAL,
    hr_z1_s REAL, hr_z2_s REAL, hr_z3_s REAL, hr_z4_s REAL, hr_z5_s REAL,
    raw TEXT
);

CREATE TABLE IF NOT EXISTS strava_activities (
    id INTEGER PRIMARY KEY,
    day TEXT, start_local TEXT, start_utc TEXT,
    name TEXT, sport TEXT,
    duration_s REAL, moving_s REAL, distance_m REAL, elev_gain_m REAL,
    avg_hr REAL, max_hr REAL, avg_speed_ms REAL, avg_power REAL, weighted_power REAL,
    kilojoules REAL, suffer_score REAL, kudos INTEGER, pr_count INTEGER, achievement_count INTEGER,
    device_name TEXT, gear_id TEXT,
    garmin_id INTEGER,          -- matched garmin_activities.id, if the same session
    raw TEXT
);

-- Planned / scheduled workouts from the Garmin Connect calendar (incl. Garmin Coach plans).
CREATE TABLE IF NOT EXISTS planned (
    id TEXT PRIMARY KEY,
    day TEXT, name TEXT, sport TEXT,
    duration_s REAL, distance_m REAL,
    workout_id INTEGER, item_type TEXT,
    raw TEXT
);

-- Subjective daily check-in (the stuff no watch can measure).
CREATE TABLE IF NOT EXISTS checkins (
    day TEXT PRIMARY KEY,
    energy INTEGER,      -- 1..5
    soreness INTEGER,    -- 1..5 (5 = very sore)
    mood INTEGER,        -- 1..5
    motivation INTEGER,  -- 1..5
    illness INTEGER,     -- 0/1
    injury TEXT,
    notes TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);

-- Coach chat (embedded Claude Code sessions)
CREATE TABLE IF NOT EXISTS chat_conversations (
    id TEXT PRIMARY KEY,
    sdk_session_id TEXT,
    title TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,
    role TEXT,          -- user | assistant | tool | error
    content TEXT,       -- markdown text, or JSON for tool rows
    context TEXT,       -- what the user was looking at (day, activity, ...)
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_chat_conv ON chat_messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS sync_log (
    ts TEXT, source TEXT, status TEXT, message TEXT
);

-- Unified activity list: Garmin sessions enriched with Strava, plus Strava-only sessions.
DROP VIEW IF EXISTS activities;
CREATE VIEW activities AS
SELECT
    'garmin' AS source, g.id AS garmin_id, s.id AS strava_id,
    g.day, g.start_local, g.name, g.sport, g.duration_s, g.moving_s, g.distance_m, g.elev_gain_m,
    g.avg_hr, g.max_hr, g.avg_speed_ms, g.avg_power, g.norm_power, g.calories,
    g.training_load, g.aerobic_te, g.anaerobic_te, g.te_label, g.vo2max,
    s.suffer_score, s.kudos, s.pr_count
FROM garmin_activities g
LEFT JOIN strava_activities s ON s.garmin_id = g.id
UNION ALL
SELECT
    'strava', NULL, s.id,
    s.day, s.start_local, s.name, s.sport, s.duration_s, s.moving_s, s.distance_m, s.elev_gain_m,
    s.avg_hr, s.max_hr, s.avg_speed_ms, s.avg_power, s.weighted_power, s.kilojoules * 0.239 * 4,
    NULL, NULL, NULL, NULL, NULL,
    s.suffer_score, s.kudos, s.pr_count
FROM strava_activities s
WHERE s.garmin_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_ga_day ON garmin_activities(day);
CREATE INDEX IF NOT EXISTS idx_sa_day ON strava_activities(day);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, timeout=30)
    else:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def session(readonly: bool = False) -> Iterator[sqlite3.Connection]:
    conn = connect(readonly)
    try:
        yield conn
        if not readonly:
            conn.commit()
    finally:
        conn.close()


def init() -> None:
    with session() as c:
        c.executescript(SCHEMA)


def put_raw(c: sqlite3.Connection, day: str, kind: str, data: Any) -> None:
    c.execute(
        "INSERT OR REPLACE INTO raw(day, kind, fetched_at, json) VALUES (?,?,?,?)",
        (day, kind, now_iso(), json.dumps(data) if data is not None else None),
    )


def get_raw(c: sqlite3.Connection, day: str, kind: str) -> Any:
    row = c.execute("SELECT json FROM raw WHERE day=? AND kind=?", (day, kind)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def upsert(c: sqlite3.Connection, table: str, key: str, row: dict[str, Any]) -> None:
    cols = list(row)
    updates = ", ".join(f"{k}=excluded.{k}" for k in cols if k != key)
    c.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT({key}) DO UPDATE SET {updates}",
        [row[k] for k in cols],
    )


def kv_get(key: str, default: Any = None) -> Any:
    with session() as c:
        row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def kv_set(key: str, value: Any) -> None:
    with session() as c:
        c.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?,?)", (key, json.dumps(value)))


def log(source: str, status: str, message: str) -> None:
    with session() as c:
        c.execute("INSERT INTO sync_log VALUES (?,?,?,?)", (now_iso(), source, status, message[:2000]))
        c.execute("DELETE FROM sync_log WHERE rowid NOT IN (SELECT rowid FROM sync_log ORDER BY ts DESC LIMIT 500)")


def rows(sql: str, params: tuple | list = (), readonly: bool = False) -> list[dict[str, Any]]:
    with session(readonly) as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]
