"""Desktop app: runs the local server in-process and shows it in a native window."""

import logging
import threading
import time

import httpx
import uvicorn

from .config import DATA_DIR, HOST, PORT

URL = f"http://localhost:{PORT}/"


def _server_up() -> bool:
    try:
        return httpx.get(f"{URL}api/status", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def _no_console_windows() -> None:
    """The app runs under pythonw (no console). On Windows every console program it starts (the
    claude CLI behind the coach chat, MCP servers, uvx) would then pop up its own terminal window.
    Start them all with CREATE_NO_WINDOW instead; their children inherit the hidden console."""
    import subprocess
    import sys

    if sys.platform != "win32" or getattr(subprocess.Popen.__init__, "_hw_patched", False):
        return
    original = subprocess.Popen.__init__

    def init(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    init._hw_patched = True
    subprocess.Popen.__init__ = init


def main() -> None:
    _no_console_windows()
    logging.basicConfig(
        filename=DATA_DIR / "app.log", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = None
    if not _server_up():
        from .server import app

        server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", log_config=None))
        threading.Thread(target=server.run, daemon=True, name="uvicorn").start()
        for _ in range(100):
            if _server_up():
                break
            time.sleep(0.1)

    import webview

    webview.create_window(
        "HealthWatcher", URL, width=1480, height=940, min_size=(900, 600),
        background_color="#f4f5f7", text_select=True,
    )
    webview.start(private_mode=False)
    if server:
        server.should_exit = True


if __name__ == "__main__":
    main()
