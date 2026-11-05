"""Read the reviewed bank-export CSV and aggregate it into WISO entry proposals."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

REQUIRED = (
    "ID",
    "Datum",
    "Empfänger",
    "Verwendungszweck",
    "Betrag",
    "Kategorie",
    "Label",
    "Für Abschluss bestätigt",
)
INCOME_CATEGORIES = frozenset({"Einkünfte", "Lohn/Gehalt"})


class ExportError(ValueError):
    """The CSV is not a usable bank export."""


@dataclass(frozen=True)
class Booking:
    id: int
    date: str
    payee: str
    purpose: str
    amount: Decimal
    category: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "date": self.date,
            "payee": self.payee,
            "purpose": self.purpose,
            "amount": str(self.amount),
            "category": self.category,
            "label": self.label,
        }


@dataclass
class Proposal:
    category: str
    label: str
    total: Decimal
    items: list[Booking] = field(default_factory=list)
    target: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "label": self.label,
            "total": str(self.total),
            "items": [b.to_dict() for b in self.items],
            "target": self.target,
        }


def parse_amount(raw: str) -> Decimal:
    s = raw.strip().replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})*(,\d+)?|-?\d+,\d+", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ExportError(f"ungültiger Betrag: {raw!r}") from exc


_YEAR_COL = re.compile(r"^Im Jahr (\d{4})$")


def load_export(path: Path, allow_review: bool = False, tax_year: int | None = None) -> list[Booking]:
    """Confirmed bookings of the export's tax year ('Im Jahr NNNN' column; checked against tax_year)."""
    path = Path(path)
    if "_review_" in path.name and not allow_review:
        raise ExportError("review export (nicht abgeschlossen) - nur mit allow_review=True verwenden")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        year_cols = [c for c in (reader.fieldnames or []) if _YEAR_COL.match(c)]
        if not year_cols:
            missing.append("Im Jahr <Steuerjahr>")
        if missing:
            raise ExportError(f"fehlende Spalten: {', '.join(missing)}")
        year_col = year_cols[0]
        export_year = int(year_col[-4:])
        if tax_year is not None and export_year != tax_year:
            raise ExportError(f"Export ist für {export_year}, WISO-Fall ist Steuerjahr {tax_year}")
        rows = []
        for r in reader:
            if r[year_col].strip() != "1" or r["Für Abschluss bestätigt"].strip() != "1":
                continue
            rows.append(
                Booking(
                    int(r["ID"]),
                    r["Datum"],
                    r["Empfänger"],
                    r["Verwendungszweck"],
                    parse_amount(r["Betrag"]),
                    r["Kategorie"].strip(),
                    (r["Label"] or "").strip(),
                )
            )
    return rows


def summarize(bookings: list[Booking]) -> list[Proposal]:
    groups: dict[tuple[str, str], Proposal] = {}
    for b in bookings:
        p = groups.setdefault((b.category, b.label), Proposal(b.category, b.label, Decimal("0")))
        p.items.append(b)
    for p in groups.values():
        s = sum((b.amount for b in p.items), Decimal("0"))
        p.total = s if p.category in INCOME_CATEGORIES else -s
    return sorted(groups.values(), key=lambda p: (p.category, p.label))
