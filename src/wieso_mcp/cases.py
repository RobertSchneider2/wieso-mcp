"""Read WISO's recent-files list (btsdatei.xml) into Case objects."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_KIND_BY_MODE = {"1": "einkommensteuer", "2": "lohnsteuerermaessigung", "65536": "vorerfassung"}


class CaseFileError(ValueError):
    """btsdatei.xml exists but cannot be parsed."""


@dataclass(frozen=True)
class Case:
    path: Path
    filename: str
    tax_year: int | None
    persons: str
    status: str
    kind: str
    last_opened: str

    @property
    def submitted(self) -> bool:
        return self.status.strip().lower() != "noch nicht abgegeben"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        d["submitted"] = self.submitted
        return d


def _text(entry: ET.Element, tag: str) -> str:
    el = entry.find(tag)
    return (el.text or "").strip() if el is not None else ""


def load_cases(path: Path, tax_year: int | None = None) -> list[Case]:
    if not path.is_file():
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise CaseFileError(f"cannot parse {path}: {exc}") from exc
    cases: list[Case] = []
    for e in root.findall("btsDateiXmlEntry"):
        year_txt = _text(e, "steuerjahr")
        year = int(year_txt) if year_txt.isdigit() else None
        if tax_year is not None and year != tax_year:
            continue
        cases.append(
            Case(
                path=Path(_text(e, "filepath")),
                filename=_text(e, "filename"),
                tax_year=year,
                persons=_text(e, "person"),
                status=_text(e, "abgabeart"),
                kind=_KIND_BY_MODE.get(_text(e, "programmmode"), "unbekannt"),
                last_opened=_text(e, "lastopened"),
            )
        )
    return cases
