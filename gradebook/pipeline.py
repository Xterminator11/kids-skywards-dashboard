"""One run: fetch grades from every source and save them to every store."""
from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from .config import Settings
from .models import GradeRecord
from .sources import GradeSource, LoginError
from .sources.skyward import SkywardSource
from .models import AssignmentRecord
from .storage import CsvAssignmentStore, CsvGradeStore, GradeStore

log = logging.getLogger(__name__)


def build_sources(settings: Settings) -> list[GradeSource]:
    return [SkywardSource(settings)]


def build_stores(settings: Settings) -> list[GradeStore]:
    # Add more stores here later (SQLite, Google Sheets, etc.).
    return [CsvGradeStore(settings.data_dir)]


def build_assignment_stores(settings: Settings) -> list[GradeStore]:
    return [CsvAssignmentStore(settings.data_dir)]


def refresh_dashboard(settings: Settings) -> None:
    """Rebuild data/site/index.html from the latest CSVs. A dashboard problem is
    logged but never fails the scrape."""
    try:
        from .dashboard import build_dashboard
        build_dashboard(settings.data_dir, state_dir=settings.state_dir)
    except Exception:
        log.exception("Could not rebuild the dashboard")


def run_once(
    settings: Settings,
    sources: Sequence[GradeSource] | None = None,
    stores: Sequence[GradeStore] | None = None,
    assignment_stores: Sequence[GradeStore] | None = None,
) -> list[GradeRecord]:
    sources = list(sources) if sources is not None else build_sources(settings)
    stores = list(stores) if stores is not None else build_stores(settings)
    assignment_stores = (
        list(assignment_stores) if assignment_stores is not None else build_assignment_stores(settings)
    )

    attempts = settings.max_retries + 1
    for attempt in range(1, attempts + 1):
        try:
            records: list[GradeRecord] = []
            for source in sources:
                records.extend(source.fetch())
            for store in stores:
                store.save(records)
            assignments: list[AssignmentRecord] = []
            for source in sources:
                assignments.extend(source.fetch_assignments())
            for store in assignment_stores:
                store.save(assignments)
            log.info("Run finished: saved %d grades and %d assignments", len(records), len(assignments))
            refresh_dashboard(settings)
            return records
        except LoginError:
            log.error("Skyward rejected the username/password; not retrying. Check .env.")
            raise
        except Exception:
            log.exception("Run failed (attempt %d of %d)", attempt, attempts)
            if attempt == attempts:
                raise
            time.sleep(settings.retry_delay_minutes * 60)
    return []
