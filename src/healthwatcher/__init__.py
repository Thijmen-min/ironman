"""HealthWatcher: local Garmin + Strava dashboard and coaching data store."""

__version__ = "0.1.0"


def main() -> None:
    from .cli import main as cli_main

    cli_main()
