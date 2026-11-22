"""Keeps the container alive and runs the pipeline on a cron schedule."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings
from .pipeline import refresh_dashboard, run_once

log = logging.getLogger(__name__)


def _job(settings: Settings) -> None:
    try:
        run_once(settings)
    except Exception:
        # Already logged in run_once; keep the scheduler alive for tomorrow.
        log.error("Scheduled run gave up after retries")


def start(settings: Settings) -> None:
    settings.require_credentials()
    tz = ZoneInfo(settings.timezone)
    scheduler = BlockingScheduler(timezone=tz)
    trigger = CronTrigger.from_crontab(settings.schedule_cron, timezone=tz)
    scheduler.add_job(
        _job, trigger, args=[settings], id="gradebook",
        max_instances=1, coalesce=True, misfire_grace_time=3600,
    )

    # Make sure the dashboard page exists (and shows the last check) as soon as we start.
    refresh_dashboard(settings)

    if settings.run_on_start:
        log.info("RUN_ON_START is set: running now")
        _job(settings)

    next_run = trigger.get_next_fire_time(None, datetime.now(tz))
    log.info("Scheduler started (%s, %s). Next run: %s", settings.schedule_cron, settings.timezone, next_run)
    scheduler.start()
