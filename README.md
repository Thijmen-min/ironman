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
takes a few minutes. After that the app re-syncs every 20 minutes while it is open.

### What gets stored (permanently, locally)

Garmin Connect is the source of truth, and HealthWatcher keeps a complete local copy in `data/healthwatcher.db`.
Nothing is ever deleted.
- **Daily health** (sleep stages and score, HRV, resting HR, stress, body battery, SpO2, respiration, readiness, training status and load, VO2max): fetched newest-first, 60 older days per sync, back to `HW_BACKFILL_DAYS` (3 years by default), until the full history is in.
- **Activities**: the complete history on the first sync, then a 14-day rolling window to catch late uploads and edits. Laps and splits are downloaded per activity.
- **Late watch syncs**: today and yesterday are re-fetched every sync; the last 7 days are re-checked every 6 hours.
- **Minute-level** heart rate, stress and body battery for the last 14 days of each sync (older curves stay once stored). Also stored: race predictions, endurance and hill score, the Garmin calendar, and weight.
- The untouched Garmin responses are stored too (`raw` table), so nothing is lost if the parsing improves later.

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
| Profile | Your goals and races (A/B/C), season plan (prep, base, build, peak, taper) worked back from the A-race, training start, availability, thresholds (these drive TSS), health and limitations, equipment, coaching preferences, and a change log of edits by you and by the coach |
| Coach | A markdown briefing of everything relevant, with one click to copy it into Claude |

## Claude as coach

**In the app:** click **Coach chat** in the top bar, or **Discuss with Claude** on a day, workout, week or a point
on the PMC chart. It runs a real Claude Code session (your installed `claude` CLI and its claude.ai login, so it
uses your **subscription**, not API billing) with full access to the data below. Read-only tools run freely.
Anything that writes to Garmin Connect, such as scheduling a workout, shows an Allow/Deny card first.
Conversations are saved and can be resumed. Every new chat starts with your **Profile** loaded into the coach's
instructions. The coach can also write to the app: it can update your profile (logged in the change log) and put
planned workouts on the Calendar (marked *Coach*). Pushing workouts to your watch still needs your approval.

**In the terminal:** `.mcp.json` registers two MCP servers for Claude Code in this folder:

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
