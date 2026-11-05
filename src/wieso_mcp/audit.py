"""Append-only JSONL audit log of every state-changing action."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def write(self, tool: str, **data: Any) -> dict[str, Any]:
        entry = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "tool": tool, **data}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return entry
