from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class WorkflowPauseRequired(RuntimeError):
    reason: str
    payload: dict[str, Any]

    def __str__(self) -> str:
        return self.reason
