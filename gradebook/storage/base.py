"""Interface for places grades get saved (CSV today; a database or sheet later)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from ..models import GradeRecord


class GradeStore(ABC):
    @abstractmethod
    def save(self, records: Sequence[GradeRecord]) -> None:
        """Persist one run's worth of grades."""
