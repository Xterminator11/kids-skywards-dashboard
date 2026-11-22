"""Saves records as CSV.

Each run writes, for grades (and the same pattern for assignments):
  - data/snapshots/grades_YYYY-MM-DD.csv   that day's full gradebook
  - data/grades_latest.csv                 always the most recent run
  - data/grades_history.csv                every run appended, for trends over time
"""
from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..models import AssignmentRecord, GradeRecord
from .base import GradeStore


class CsvStore(GradeStore):
    """Writes any record type that has field_names() / to_row() / scraped_at."""

    prefix = "records"
    record_type: Any = GradeRecord

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.snapshot_dir = self.data_dir / "snapshots"
        self.latest_path = self.data_dir / f"{self.prefix}_latest.csv"
        self.history_path = self.data_dir / f"{self.prefix}_history.csv"

    def save(self, records: Sequence[Any]) -> None:
        if not records:
            return
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        day = records[0].scraped_at.strftime("%Y-%m-%d")
        rows = [r.to_row() for r in records]

        self._write_atomic(self.snapshot_dir / f"{self.prefix}_{day}.csv", rows)
        self._write_atomic(self.latest_path, rows)
        self._append(self.history_path, rows)

    def _write_atomic(self, path: Path, rows: list[dict[str, str]]) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.record_type.field_names())
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)

    def _append(self, path: Path, rows: list[dict[str, str]]) -> None:
        new_file = not path.exists() or path.stat().st_size == 0
        if not new_file:
            self._upgrade_header(path)
        with path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.record_type.field_names())
            if new_file:
                writer.writeheader()
            writer.writerows(rows)


    def _upgrade_header(self, path: Path) -> None:
        """If a new column was added since the file was started, rewrite the history
        with the new header (old rows get blanks), so appended rows line up."""
        fields = self.record_type.field_names()
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames == fields:
                return
            old = list(reader)
        self._write_atomic(path, [{k: row.get(k) or "" for k in fields} for row in old])


class CsvGradeStore(CsvStore):
    prefix = "grades"
    record_type = GradeRecord


class CsvAssignmentStore(CsvStore):
    prefix = "assignments"
    record_type = AssignmentRecord
