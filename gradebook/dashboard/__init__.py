"""Family dashboard: rule-based metrics written into one static HTML page."""
from .build import build_dashboard, build_payload
from .rules import Rules

__all__ = ["Rules", "build_dashboard", "build_payload"]
