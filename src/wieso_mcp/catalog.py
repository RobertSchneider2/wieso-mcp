"""Read-only access to WISO's ELSTER field catalogue (ericfelder.db3, table Feldformate)."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_COLS = "Feldnummer, VZ, Drucktext, Beschreibung, Kontext, Format, Vordruck, Vordruckzeile, MaxLength"


@dataclass(frozen=True)
class FieldInfo:
    field_id: str
    vz: int
    label: str
    description: str
    context: str
    pattern: str
    form: str
    line: str
    max_length: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row(r: sqlite3.Row) -> FieldInfo:
    return FieldInfo(
        field_id=r[0],
        vz=int(r[1]),
        label=r[2] or "",
        description=r[3] or "",
        context=r[4] or "",
        pattern=r[5] or "",
        form=r[6] or "",
        line=str(r[7] or ""),
        max_length=r[8],
    )


class FieldCatalog:
    def __init__(self, db_path: Path) -> None:
        uri = f"{Path(db_path).resolve().as_uri()}?mode=ro&immutable=1"
        self._con = sqlite3.connect(uri, uri=True, check_same_thread=False)

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> FieldCatalog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def describe(self, field_id: str, vz: int = 2025) -> FieldInfo | None:
        r = self._con.execute(
            f"SELECT {_COLS} FROM Feldformate WHERE Feldnummer=? AND VZ=? LIMIT 1", (field_id, vz)
        ).fetchone()
        return _row(r) if r else None

    def search(self, text: str, vz: int = 2025, form: str | None = None, limit: int = 50) -> list[FieldInfo]:
        like = f"%{text.lower()}%"
        sql = (
            f"SELECT {_COLS} FROM Feldformate WHERE VZ=? AND "
            "(lower(Drucktext) LIKE ? OR lower(Beschreibung) LIKE ? OR lower(Kontext) LIKE ?)"
        )
        args: list[Any] = [vz, like, like, like]
        if form:
            sql += " AND Vordruck=?"
            args.append(form)
        sql += " GROUP BY Feldnummer ORDER BY Vordruck, Feldnummer LIMIT ?"
        args.append(limit)
        return [_row(r) for r in self._con.execute(sql, args)]

    def forms(self, vz: int = 2025) -> list[str]:
        rows = self._con.execute(
            "SELECT DISTINCT Vordruck FROM Feldformate WHERE VZ=? AND Vordruck<>'' ORDER BY Vordruck", (vz,)
        )
        return [r[0] for r in rows]
