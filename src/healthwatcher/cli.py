"""Command line: `uv run hw <command>`."""

import argparse
import getpass
import json
import subprocess
import sys
from pathlib import Path

from .config import PORT, PROJECT_ROOT

TASK_NAME = "HealthWatcher Sync"


def _pythonw() -> Path:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def cmd_app(_):
    from .desktop import main

    main()


def cmd_serve(_):
    import uvicorn

    from .config import HOST
    from .server import app

    print(f"HealthWatcher on http://localhost:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


def cmd_sync(args):
    import httpx

    # If the app is running, let it do the work (avoids two syncs fighting).
    try:
        r = httpx.post(f"http://localhost:{PORT}/api/sync", timeout=3)
        if r.status_code == 200:
            print("App is running - sync triggered there.")
            return
    except httpx.HTTPError:
        pass
    from . import db, garmin_sync, strava

    db.init()
    print(json.dumps(garmin_sync.sync(backfill_days=args.days), indent=2))
    if strava.connected():
        print(json.dumps(strava.sync(), indent=2))


def cmd_login(_):
    from garminconnect import Garmin

    from . import db
    from .config import GARMIN_TOKENS

    db.init()
    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password (hidden): ")
    Path(GARMIN_TOKENS).mkdir(parents=True, exist_ok=True)
    api = Garmin(email, password, prompt_mfa=lambda: input("MFA code: ").strip())
    api.login(GARMIN_TOKENS)
    print(f"Logged in as {api.get_full_name()}. Tokens saved to {GARMIN_TOKENS}")


def cmd_brief(args):
    from . import analytics, db

    db.init()
    sys.stdout.reconfigure(encoding="utf-8")
    print(analytics.briefing(args.days))


def cmd_sql(args):
    from . import db

    sys.stdout.reconfigure(encoding="utf-8")
    for row in db.rows(args.query, readonly=True)[: args.limit]:
        print(json.dumps(row, default=str))


def cmd_reextract(_):
    from . import db, garmin_sync, strava

    db.init()
    n = garmin_sync.reextract_all()
    with db.session() as c:
        m = strava.match_garmin(c)
    print(f"Re-extracted {n} days; {m} Strava activities matched.")


def make_icon() -> Path:
    from PIL import Image, ImageDraw

    path = PROJECT_ROOT / "assets" / "healthwatcher.ico"
    path.parent.mkdir(exist_ok=True)
    s = 256
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, s - 8, s - 8), radius=56, fill=(19, 41, 75, 255))
    pts = [(40, 140), (88, 140), (108, 92), (136, 190), (160, 70), (182, 140), (216, 140)]
    d.line(pts, fill=(255, 255, 255, 255), width=18, joint="curve")
    for x, y in (pts[0], pts[-1]):
        d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(255, 255, 255, 255))
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return path


def cmd_shortcut(_):
    icon = make_icon()
    ps = f"""
$desktop = [Environment]::GetFolderPath('Desktop')
$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'HealthWatcher.lnk'))
$s.TargetPath = '{_pythonw()}'
$s.Arguments = '-m healthwatcher.desktop'
$s.WorkingDirectory = '{PROJECT_ROOT}'
$s.IconLocation = '{icon},0'
$s.Description = 'HealthWatcher - Garmin + Strava training dashboard'
$s.Save()
Write-Output (Join-Path $desktop 'HealthWatcher.lnk')
"""
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    print(out.stdout.strip() or out.stderr.strip())


def cmd_install_task(args):
    tr = f'"{_pythonw()}" -m healthwatcher.cli sync'
    out = subprocess.run(
        ["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", str(args.every), "/TN", TASK_NAME, "/TR", tr],
        capture_output=True, text=True,
    )
    print(out.stdout.strip() or out.stderr.strip())


def cmd_uninstall_task(_):
    out = subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], capture_output=True, text=True)
    print(out.stdout.strip() or out.stderr.strip())


def cmd_mcp(_):
    from .mcp_server import main

    main()


def main() -> None:
    p = argparse.ArgumentParser(prog="hw", description="HealthWatcher - Garmin + Strava coach data")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("app", help="open the desktop app").set_defaults(fn=cmd_app)
    sub.add_parser("serve", help="run the web server only (browser at localhost)").set_defaults(fn=cmd_serve)
    sp = sub.add_parser("sync", help="sync Garmin + Strava now")
    sp.add_argument("--days", type=int, default=None, help="backfill window (default HW_BACKFILL_DAYS)")
    sp.set_defaults(fn=cmd_sync)
    sub.add_parser("login", help="log in to Garmin Connect in the terminal").set_defaults(fn=cmd_login)
    sp = sub.add_parser("brief", help="print the coach briefing (markdown)")
    sp.add_argument("--days", type=int, default=14)
    sp.set_defaults(fn=cmd_brief)
    sp = sub.add_parser("sql", help="run a read-only SQL query")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=200)
    sp.set_defaults(fn=cmd_sql)
    sub.add_parser("reextract", help="rebuild tables from stored raw payloads").set_defaults(fn=cmd_reextract)
    sub.add_parser("shortcut", help="create the desktop shortcut").set_defaults(fn=cmd_shortcut)
    sp = sub.add_parser("install-task", help="sync in the background even when the app is closed")
    sp.add_argument("--every", type=int, default=30, help="minutes between syncs")
    sp.set_defaults(fn=cmd_install_task)
    sub.add_parser("uninstall-task", help="remove the background sync task").set_defaults(fn=cmd_uninstall_task)
    sub.add_parser("mcp", help="run the MCP server (stdio) for Claude").set_defaults(fn=cmd_mcp)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
