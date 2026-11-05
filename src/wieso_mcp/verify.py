"""Read-only verification report for an applied plan.

Reopens every plan target, compares what WISO shows with the plan, reads the Werbungskosten
overview and the red status marks of the navigation tree, takes one screenshot per target and
writes ``run-report.json`` plus ``run-report.md``. Dialogs are only ever left with *Abbrechen*;
nothing is confirmed or saved.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .ui.driver import DriverError

OVERVIEW_CARDS = ("EA[M]\\WK0000", "EA[F]\\WK0000")
_DATE = re.compile(r"^\d{2}\.\d{2}\.\d{4} ")


def _amount(value: Any) -> Decimal:
    s = str(value).replace("€", "").replace("\xa0", "").replace(" ", "").replace("–", "0").strip()
    if "," in s:  # German display format: 1.234,56
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("description") or "").strip(), str(_amount(row.get("amount", 0))))


def compare_rows(want: list[dict[str, Any]], got: list[dict[str, Any]]) -> dict[str, Any]:
    """Multiset comparison of (description, amount); amounts compared as decimals."""
    w, g = Counter(_key(r) for r in want), Counter(_key(r) for r in got)
    missing = sorted([list(k) for k in (w - g).elements()])
    extra = sorted([list(k) for k in (g - w).elements()])
    return {"status": "ok" if not missing and not extra else "mismatch", "missing": missing, "extra": extra}


def device_name(description: str) -> str:
    """'R13 REVIEW ... | 21.03.2025 Toshiba' -> 'Toshiba' (how the device is labelled in WISO)."""
    name = description.split("| ")[-1].strip()
    return _DATE.sub("", name).strip()


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3]


def _present(name: str, labels: list[str]) -> bool:
    """Device shown in WISO? Labels may be shortened or reworded: the first two words must match."""
    key = _words(name)[:2]
    return bool(key) and any(all(k in _words(label) for k in key) for label in labels)


def _check_target(drv: Any, t: dict[str, Any]) -> dict[str, Any]:
    if t["kind"] == "devices":
        labels = [e["label"] for e in drv.list_entries()]
        missing = [
            device_name(r["description"])
            for r in t["rows"]
            if not _present(device_name(r["description"]), labels)
        ]
        dropped = [device_name(r["description"]) for r in t.get("dropped", [])]
        still = [n for n in dropped if _present(n, labels)]
        status = "ok" if not missing and not still else "mismatch"
        return {"status": status, "missing": missing, "unexpected_present": still, "shown": labels}
    res = compare_rows(t["rows"], drv.table_rows())
    res["total_plan"] = str(sum((_amount(r["amount"]) for r in t["rows"]), Decimal("0.00")))
    return res


def verify_plan(drv: Any, plan: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """Check every target of `plan` in the open case; write the report into `out_dir`."""
    if drv.dialog_open():
        raise DriverError("a dialog is open in WISO - close it first (verify never discards your input)")
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "case": plan.get("case"),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "targets": [],
    }
    for i, t in enumerate(plan["targets"], 1):
        entry: dict[str, Any] = {"key": t["key"], "kind": t["kind"]}
        try:
            drv.leave_dialogs()
            drv.goto_section(t["section"])
            drv.open_card(t["card"])
            for var in t["rows_path"]:
                drv.open_row(var)
            entry.update(_check_target(drv, t))
            shot = f"{i:02d}-{re.sub(r'[^A-Za-z0-9]+', '-', t['key']).strip('-')}.png"
            drv.screenshot(out_dir / shot)
            entry["screenshot"] = shot
        except Exception as e:  # report and go on with the next target
            entry.update(status="error", error=f"{type(e).__name__}: {e}")
        report["targets"].append(entry)
    report["overview"] = {}
    for card in plan.get("overview_cards", OVERVIEW_CARDS):
        try:
            drv.leave_dialogs()
            drv.goto_section(plan.get("overview_section", "Arbeitnehmer"))
            drv.open_card(card)
            report["overview"][card] = {f["var"]: f["value"] for f in drv.list_fields() if f.get("value")}
        except Exception as e:
            report["overview"][card] = {"error": f"{type(e).__name__}: {e}"}
    try:
        drv.leave_dialogs()
        report["tree_errors"] = [
            m["label"] for m in drv.tree_status(only_problems=True) if m["status"] == "fehler"
        ]
    except Exception as e:
        report["tree_errors"] = []
        report["tree_status_error"] = f"{type(e).__name__}: {e}"
    drv.leave_dialogs()
    report["ok"] = all(t["status"] == "ok" for t in report["targets"]) and not report["tree_errors"]
    (out_dir / "run-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    (out_dir / "run-report.md").write_text(_markdown(report), "utf-8")
    return report


def _markdown(rep: dict[str, Any]) -> str:
    lines = [f"# Prüfbericht {rep['checked_at']}", "", f"Fall: `{rep['case']}`", ""]
    lines.append("**Alles stimmt.**" if rep["ok"] else "**Es gibt Abweichungen - siehe unten.**")
    lines += ["", "| Ziel | Ergebnis | Details | Screenshot |", "|---|---|---|---|"]
    for t in rep["targets"]:
        details = []
        if t.get("missing"):
            details.append(
                "fehlt: " + "; ".join(" ".join(m) if isinstance(m, list) else m for m in t["missing"])
            )
        if t.get("extra"):
            details.append("zusätzlich in WISO: " + "; ".join(" ".join(m) for m in t["extra"]))
        if t.get("unexpected_present"):
            details.append("sollte gelöscht sein: " + "; ".join(t["unexpected_present"]))
        if t.get("error"):
            details.append(t["error"])
        lines.append(
            f"| {t['key']} | {t['status'].upper()} | {'<br>'.join(details) or '-'} "
            f"| {t.get('screenshot', '-')} |"
        )
    lines += ["", "## Übersicht (Werbungskosten)", ""]
    for card, vals in rep["overview"].items():
        lines.append(f"- {card}: " + ", ".join(f"{k}={v}" for k, v in vals.items()))
    lines += ["", "## Rote Ausrufezeichen im Navigationsbaum", ""]
    lines += [f"- {x}" for x in rep["tree_errors"]] or ["- keine"]
    return "\n".join(lines) + "\n"
