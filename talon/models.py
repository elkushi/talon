"""Result model shared by every check."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    OK = "ok"      # nothing to do
    WARN = "warn"  # needs fixing, not urgent
    FAIL = "fail"  # hurts indexing / users / security now
    INFO = "info"  # not evaluated (baseline saved, RDAP unavailable) - never a problem


ICON: dict[Status, str] = {
    Status.OK: "✅",
    Status.WARN: "⚠️",
    Status.FAIL: "❌",
    Status.INFO: "ℹ️",
}

# Sort order inside the report: worst first.
SEVERITY: dict[Status, int] = {Status.FAIL: 0, Status.WARN: 1, Status.INFO: 2, Status.OK: 3}


@dataclass
class CheckResult:
    check: str           # "redirects", "robots", ...
    domain: str          # site name ("example.com") or registrable domain for dns
    status: Status
    summary_ru: str      # one short Russian line for the талон
    details: dict = field(default_factory=dict)
    changed: bool = False  # True if this differs from the previous run's state

    @property
    def icon(self) -> str:
        return ICON[self.status]

    def as_dict(self) -> dict:
        return {
            "check": self.check,
            "domain": self.domain,
            "status": str(self.status),
            "summary_ru": self.summary_ru,
            "details": self.details,
            "changed": self.changed,
        }


def worst(results: list[CheckResult]) -> Status:
    """Worst status in a list; OK for an empty list."""
    if not results:
        return Status.OK
    return min((r.status for r in results), key=lambda s: SEVERITY[s])
