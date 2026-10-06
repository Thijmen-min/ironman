# HealthWatcher

A local desktop dashboard that pulls **Garmin Connect** (sleep, HRV, resting HR, stress, body battery,
training readiness and status, VO2max, weight, activities, planned workouts) and **Strava** throughout the
day into a local SQLite database. It shows that data TrainingPeaks-style (calendar, Performance Management
Chart, weekly TSS, HR zones, wellness trends). The same data is exposed to **Claude** over MCP so it can act
as a well-informed coach.

Everything runs on your machine: data stays in `data/` and Garmin tokens stay in `~/.garminconnect`.

## Setup (Windows)

```powershell
winget install astral-sh.uv        # Python toolchain (restart the terminal afterwards)
uv sync                             # install dependencies
uv run hw shortcut                  # creates "HealthWatcher" on the desktop
```

Open the **HealthWatcher** shortcut, go to **Settings** and connect Garmin (MFA supported). The first sync
backfills 120 days, which takes a few minutes. After that the app re-syncs every 20 minutes while it is open.

Optional:
- **Sync while the app is closed:** `uv run hw install-task` (Windows Task Scheduler, every 30 min). Remove it with `uv run hw uninstall-task`.
- **Strava:** create an API app at <https://www.strava.com/settings/api> with callback domain `localhost`, copy `.env.example` to `.env`, fill in `STRAVA_CLIENT_ID`/`STRAVA_CLIENT_SECRET`, restart, then click *Connect Strava* in Settings.
- **Thresholds:** set `HW_LTHR` / `HW_FTP` in `.env` if Garmin's values are missing or wrong. They drive TSS.

## Views

| Tab | What it shows |
|---|---|
| Home | Today's readiness verdict and why, key tiles (form, sleep, HRV, RHR, body battery, readiness, stress, steps), minute-by-minute HR/stress/body battery, daily check-in, recent and planned sessions |
| Calendar | TrainingPeaks-style weeks with workout cards (planned/done/missed), daily metrics, week summary column (TSS, time, distance, CTL/ATL/TSB, per sport) |
| Dashboard | Performance Management Chart (Fitness/Fatigue/Form, with projection over planned workouts), weekly TSS by sport, sport summary, time in HR zones, wellness small multiples |
| Coach | A markdown briefing of everything relevant, with one click to copy it into Claude |

## Claude as coach

`.mcp.json` registers two MCP servers for Claude Code in this folder:

- `healthwatcher`: this database (briefing, readiness, daily metrics, activities, PMC, weekly summaries, check-ins, read-only SQL, sync)
- `garmin`: live Garmin Connect via [Taxuspt/garmin_mcp](https://github.com/Taxuspt/garmin_mcp) (110+ tools, including uploading and scheduling workouts to your watch)

```powershell
cd healthwatcher
claude
> How's my recovery this week, and what should tomorrow look like?
```

`CLAUDE.md` holds the coaching instructions (load progression, recovery rules, Ironman specifics, safety).

## CLI

```
uv run hw app | serve | sync | login | brief | sql "<SELECT>" | reextract | shortcut | install-task | uninstall-task | mcp
```
