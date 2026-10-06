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


def main() -> None:
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
