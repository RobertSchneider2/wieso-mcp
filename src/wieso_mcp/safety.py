"""Hard safety rails: never submit, never type secrets, only write to allowed case files."""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

# No override exists for these - by design (spec: "never submit").
_SEND = re.compile(
    r"abgeben|abgabe|versend|versand|senden|send|übermitt|uebermitt|authentifiz|signier|"
    r"debug|zertifikat.*import",
    re.IGNORECASE,
)
_SECRET = re.compile(r"passw|kennwort|\bpin\b|pin_|_pin|pinedit|zertifikat", re.IGNORECASE)


class Blocked(PermissionError):
    """The requested UI action is forbidden by the safety rails."""


class SafetyGuard:
    def __init__(self, workdir: Path, backup_dir: Path) -> None:
        self.workdir = Path(workdir).resolve()
        self.backup_dir = Path(backup_dir)
        self._backed_up: set[Path] = set()

    def check_invoke(self, name: str, automation_id: str) -> None:
        text = f"{name} {automation_id}"
        if _SEND.search(text):
            raise Blocked(f"blocked control (submission/auth/debug): {name or automation_id!r}")

    def check_set(self, name: str, automation_id: str) -> None:
        if _SECRET.search(f"{name} {automation_id}"):
            raise Blocked(f"refusing to type into secret field {name or automation_id!r}")
        self.check_invoke(name, automation_id)

    def check_case(self, path: Path) -> None:
        resolved = Path(path).resolve()
        if resolved.is_relative_to(self.workdir):
            return
        if os.environ.get("WIESO_MCP_ALLOW_ORIGINAL") == "1":
            return
        raise Blocked(
            f"{resolved} is outside the working directory {self.workdir}; "
            "use prepare_working_copy or set WIESO_MCP_ALLOW_ORIGINAL=1"
        )

    def ensure_backup(self, path: Path) -> Path | None:
        resolved = Path(path).resolve()
        if resolved in self._backed_up or not resolved.is_file():
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        dest = self.backup_dir / f"{resolved.name}.{datetime.now():%Y%m%d_%H%M%S_%f}"
        shutil.copy2(resolved, dest)
        self._backed_up.add(resolved)
        return dest
