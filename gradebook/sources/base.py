"""Interface for anything that can produce grades (Skyward today; others later)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import AssignmentRecord, GradeRecord


class SourceError(RuntimeError):
    """Raised when a source cannot log in or read grades."""


class LoginError(SourceError):
    """Credentials were rejected. Not retried, to avoid locking the account."""


class GradeSource(ABC):
    name: str = "source"

    @abstractmethod
    def fetch(self) -> list[GradeRecord]:
        """Return the current grades for every student on the account."""

    def fetch_assignments(self) -> list[AssignmentRecord]:
        """Assignments read during the last fetch(). Sources without them return []."""
        return []
