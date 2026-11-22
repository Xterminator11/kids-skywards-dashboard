"""Command line entry point.

    python -m gradebook run          scrape once now
    python -m gradebook schedule     run on SCHEDULE_CRON forever (used by Docker)
    python -m gradebook dashboard    rebuild data/site/index.html from the saved CSVs (no login)
    python -m gradebook serve        serve the dashboard with write-off buttons (port DASHBOARD_PORT, default 8787)
    python -m gradebook parse FILE   re-parse a saved gradebook HTML file and print CSV
    python -m gradebook parse-assignments FILE...
                                     re-parse saved assignment dialogs / gradebook pages
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings
from .models import AssignmentRecord, GradeRecord


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gradebook")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="scrape once now")
    sub.add_parser("schedule", help="run on the configured schedule")
    sub.add_parser("dashboard", help="rebuild the dashboard from the saved CSVs (no login)")
    sub.add_parser("alert-text", help="print today's family alert text (empty if nothing to say)")
    sv = sub.add_parser("serve", help="serve the dashboard on your home network")
    sv.add_argument("--port", type=int, default=None, help="default: DASHBOARD_PORT from .env, else 8787")
    p = sub.add_parser("parse", help="parse a saved gradebook HTML file")
    p.add_argument("file", type=Path)
    pa = sub.add_parser(
        "parse-assignments",
        help="parse saved assignment pages (data/raw/assignments_*.html or gradebook_*.html)",
    )
    pa.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "run":
        from .pipeline import run_once
        run_once(settings)
    elif args.command == "schedule":
        from .scheduler import start
        start(settings)
    elif args.command == "dashboard":
        from .dashboard import build_dashboard
        path = build_dashboard(settings.data_dir, state_dir=settings.state_dir)
        print(f"Dashboard written to {path.resolve()}")
    elif args.command == "alert-text":
        from .dashboard.alerts import alert_text
        print(alert_text(settings.data_dir, settings.state_dir))
    elif args.command == "serve":
        from .dashboard.server import serve
        port = args.port or int(os.getenv("DASHBOARD_PORT") or "8787")
        serve(settings.data_dir, settings.state_dir, port=port)
    elif args.command == "parse":
        from .sources.skyward_parser import parse_gradebook
        records = parse_gradebook(
            args.file.read_text(encoding="utf-8"), datetime.now(ZoneInfo(settings.timezone))
        )
        writer = csv.DictWriter(sys.stdout, fieldnames=GradeRecord.field_names())
        writer.writeheader()
        writer.writerows(r.to_row() for r in records)
    elif args.command == "parse-assignments":
        _parse_assignments(args.files, settings.timezone)
    return 0


def _parse_assignments(files: list[Path], timezone: str) -> None:
    """Print assignments from saved pages. Statuses use the date in each file name
    (the day it was scraped), so "not yet due" means what it meant on that day."""
    import re
    from datetime import date

    from .sources.skyward_assignments_parser import (
        merge_assignments,
        parse_assignment_dialog,
        parse_gradebook_assignments,
    )

    tz = ZoneInfo(timezone)
    dialog: list[AssignmentRecord] = []
    page: list[AssignmentRecord] = []
    for path in files:
        html = path.read_text(encoding="utf-8")
        m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})", path.name)
        when = (
            datetime.combine(date.fromisoformat(m.group(1)), datetime.min.time(), tz).replace(
                hour=int(m.group(2)), minute=int(m.group(3)))
            if m else datetime.now(tz)
        )
        if html.lstrip().startswith("<!-- gradebook-assignments"):
            dialog.extend(parse_assignment_dialog(html, when))
        else:
            page.extend(parse_gradebook_assignments(html, when))
    writer = csv.DictWriter(sys.stdout, fieldnames=AssignmentRecord.field_names())
    writer.writeheader()
    writer.writerows(r.to_row() for r in merge_assignments(dialog, page))


if __name__ == "__main__":
    raise SystemExit(main())
