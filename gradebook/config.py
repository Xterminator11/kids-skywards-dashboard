"""Settings, read from environment variables (and a .env file if present).

Credentials are never hardcoded: they come from SKYWARD_USERNAME / SKYWARD_PASSWORD.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    skyward_url: str
    skyward_username: str
    skyward_password: str
    data_dir: Path
    schedule_cron: str
    timezone: str
    run_on_start: bool
    save_raw_html: bool
    headless: bool
    max_retries: int
    retry_delay_minutes: float
    log_level: str
    fetch_assignments: bool = True
    state_dir: Path = Path("state")   # family choices kept across scrapes (write-offs)
    assignment_delay_seconds: float = 1.5

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> "Settings":
        if env_file:
            load_dotenv(env_file, override=False)
        return cls(
            skyward_url=os.getenv("SKYWARD_URL", "").strip(),
            skyward_username=os.getenv("SKYWARD_USERNAME", "").strip(),
            skyward_password=os.getenv("SKYWARD_PASSWORD", ""),
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            schedule_cron=os.getenv("SCHEDULE_CRON", "0 15 * * *"),
            timezone=os.getenv("TZ", "America/Chicago"),
            run_on_start=_bool(os.getenv("RUN_ON_START"), False),
            save_raw_html=_bool(os.getenv("SAVE_RAW_HTML"), True),
            headless=_bool(os.getenv("HEADLESS"), True),
            max_retries=int(os.getenv("MAX_RETRIES", "2")),
            retry_delay_minutes=float(os.getenv("RETRY_DELAY_MINUTES", "10")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            fetch_assignments=_bool(os.getenv("FETCH_ASSIGNMENTS"), True),
            assignment_delay_seconds=float(os.getenv("ASSIGNMENT_DELAY_SECONDS", "1.5")),
            state_dir=Path(os.getenv("STATE_DIR", "state")),
        )

    def require_credentials(self) -> None:
        missing = [
            name
            for name, value in (
                ("SKYWARD_URL", self.skyward_url),
                ("SKYWARD_USERNAME", self.skyward_username),
                ("SKYWARD_PASSWORD", self.skyward_password),
            )
            if not value
        ]
        if missing:
            raise SystemExit(f"Missing required settings: {', '.join(missing)} (set them in .env)")
