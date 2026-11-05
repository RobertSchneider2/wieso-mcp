"""Create the private per-tax-year data folder (gitignored ``steuer/<year>/``).

Usage: ``python -m wieso_mcp.yearfolder 2026 [--root steuer]``. Existing files are never overwritten.
"""

from __future__ import annotations

import argparse
from pathlib import Path

SUBDIRS = ("wiso", "belege", "plan", "notizen", "runs", "archiv")

README = """# Steuerjahr {year} (WISO Steuer {program})

Privat – nie committen. Ablauf: `docs/jahresablauf.md`.
Übergabe aus dem Vorjahr: `../{prev}/README.md`, Abschnitt **Für nächstes Jahr**.

## Ordner

| Ordner | Inhalt |
|---|---|
| `wiso/` | Arbeitskopie `…-MCP.steuer{year}` (Real-Test-Kopie: `fixtures/private/probe.steuer{year}`) |
| `belege/` | Rechnungen, Bescheinigungen (PDF) |
| `plan/` | Bank-Export, `plan-{year}.json`, `Belege-{year}.xlsx`, Review |
| `notizen/` | offene Punkte, Entscheidungen, Analysen |
| `runs/` | Prüfberichte (`verify_plan`) |
| `archiv/` | automatische Sicherungen, Audit-Log |

## Status

- [ ] Vorjahresdaten in WISO übernommen
- [ ] Bescheinigungen abgerufen (Lohnsteuer, Steuerbescheinigungen der Banken)
- [ ] Bank-Export geprüft und abgeschlossen
- [ ] Eingaben gemacht, Prüfbericht ohne Fehler
- [ ] Abgegeben am: … · Erstattung/Nachzahlung laut WISO: …
- [ ] Bescheid erhalten am: … · Abweichungen: … · Einspruchsfrist bis: …

## Für nächstes Jahr

- …
"""


def init_year(root: Path, tax_year: int) -> Path:
    """Create ``root/<tax_year>`` with the standard sub-folders and a README; keep anything that exists."""
    year_dir = Path(root) / str(tax_year)
    for sub in SUBDIRS:
        (year_dir / sub).mkdir(parents=True, exist_ok=True)
    readme = year_dir / "README.md"
    if not readme.exists():
        text = README.format(year=tax_year, program=tax_year + 1, prev=tax_year - 1)
        readme.write_text(text, "utf-8")
    return year_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tax_year", type=int)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2] / "steuer")
    args = ap.parse_args(argv)
    print(init_year(args.root, args.tax_year))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
