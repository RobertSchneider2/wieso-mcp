"""Drive WISO Steuer 2026 through Windows UI Automation - background-safe, guarded, verified.

Mechanics (see docs/uia-findings.md):
* tree sections: posted mouse click (Qt ignores UIA Invoke on tree items) - no focus change
* page cards / sub-dialog rows / OK / Abbrechen / Speichern: UIA Invoke
* fields and table cells: UIA Value pattern, always read back
* never global keystrokes; every invoke and write passes SafetyGuard
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from ..safety import SafetyGuard

Rect = tuple[int, int, int, int]
_DLG = "zWinDialog."
_ROW_BUTTONS = ("ID_BTNSUBWIN", "rsEuroTableEdit_Button")
_DIALOG_BUTTONS = "rsCentralDialogButtonWidget"
_FIELD_KINDS = ("Edit", "ComboBox", "CheckBox", "RadioButton")


class DriverError(RuntimeError):
    pass


@dataclass
class Ctl:
    kind: str
    name: str
    automation_id: str
    value: Callable[[], str | None]
    enabled: bool
    rect: Rect
    invoke: Callable[[], None]
    set_value: Callable[[str], None]
    select: Callable[[], None] | None = None
    is_selected: Callable[[], bool] | None = None
    toggle: Callable[[], None] | None = None
    is_checked: Callable[[], bool] | None = None
    collapse: Callable[[], None] | None = None
    is_expanded: Callable[[], bool] | None = None


@dataclass
class TableCtl:
    rows: Callable[[], list[list[str]]]
    set_cell: Callable[[int, int, str], None]
    cell_rect: Callable[[int, int], Rect]
    headers: Callable[[], list[str]] = lambda: ["Datum", "Bezeichnung", "Betrag", "Gerundet"]

    def col(self, name: str) -> int:
        h = self.headers()
        return h.index(name) if name in h else -1

    def amount_col(self) -> int:
        """Amount column: 'Betrag' in most tables, 'Aufwendungen' e.g. in Reparatur und Reinigung."""
        a = self.col("Betrag")
        return a if a >= 0 else self.col("Aufwendungen")


@dataclass
class MessageBox:
    text: str
    buttons: dict[str, Callable[[], None]]


class WisoWindow(Protocol):
    def title(self) -> str: ...
    def controls(self) -> list[Ctl]: ...
    def tables(self) -> list[TableCtl]: ...
    def message_box(self) -> MessageBox | None: ...
    def post_click(self, rect: Rect) -> None: ...
    def post_double_click(self, rect: Rect) -> None: ...
    def post_text(self, text: str) -> None: ...
    def post_key(self, key: str) -> None: ...
    def is_foreground(self) -> bool: ...
    def close_popups(self) -> int: ...
    def screenshot(self, path: str) -> None: ...
    def tree_rect(self) -> Rect | None: ...
    def capture(self) -> Any: ...
    def opened_path(self) -> Path | None: ...
    def combo_options(self, automation_id: str) -> list[str]: ...
    def combo_select(self, automation_id: str, option: str) -> None: ...


def format_amount(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01'))}".replace(".", ",")


def parse_amount_text(text: str | None) -> Decimal | None:
    if not text:
        return None
    s = text.replace("€", "").replace("\xa0", "").replace(" ", "").replace("–", "0").replace("—", "0")
    s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def format_date(date: str) -> str:
    """Accept ISO (2025-04-10) or German (10.04.2025); return WISO's TT.MM.JJJJ."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", date.strip())
    if m:
        return f"{m[3]}.{m[2]}.{m[1]}"
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", date.strip()):
        return date.strip()
    raise DriverError(f"unsupported date format: {date!r}")


def _var(ctl: Ctl) -> str:
    return ctl.automation_id.split(_DLG)[-1]


_ENTRY = re.compile(r"^(\d+)\) (.+)$")


def classify_status(rgb: tuple[int, int, int]) -> str:
    """Map the colour of a navigation status symbol to its meaning (sampled from WISO 2026)."""
    r, g, b = rgb[:3]
    if r > 150 and g < 120 and b < 70:
        return "fehler"  # red triangle
    if r > 200 and g > 170 and b < 120:
        return "hinweis"  # yellow circle
    if g > r + 60 and g > b + 60:
        return "ok"  # green check
    if b > r + 80 and b > g + 30 and max(rgb[:3]) - min(rgb[:3]) > 120:
        return "finanzamt"  # blue: data from the tax office
    return "leer"


def _same_cell(shown: str, value: str) -> bool:
    """A table cell shows the written value (text equal, or the same amount in WISO's formatting)."""
    if shown.strip() == value.strip():
        return True
    a, b = parse_amount_text(shown.replace("%", "")), parse_amount_text(value.replace("%", ""))
    return a is not None and a == b


_CASE_ARG = re.compile(r'"([^"]+\.steuer\d{4})"|(\S+\.steuer\d{4})', re.IGNORECASE)


def case_from_cmdline(cmd: str | None) -> Path | None:
    """The case file WISO was started with (last ``*.steuerNNNN`` argument), or None."""
    hits = _CASE_ARG.findall(cmd or "")
    return Path(hits[-1][0] or hits[-1][1]) if hits else None


def _same_file(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _mid_y(r: Rect) -> int:
    return (r[1] + r[3]) // 2


class WisoDriver:
    def __init__(
        self,
        attach: Callable[[], WisoWindow | None],
        launch: Callable[[Path], None],
        guard: SafetyGuard,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 120.0,
        settle: float = 1.5,
        known_cases: Callable[[], list[Path]] | None = None,
    ) -> None:
        self._attach = attach
        self._known_cases: Callable[[], list[Path]] = known_cases or (lambda: [])
        self._launch = launch
        self.guard = guard
        self._sleep = sleep
        self.timeout = timeout
        self.settle = settle
        self.current_case: Path | None = None
        self._last_row: str | None = None

    # ---------------------------------------------------------------- basics
    def _win(self) -> WisoWindow:
        w = self._attach()
        if w is None:
            raise DriverError("WISO Steuer 2026 is not running - use open_case")
        return w

    def _wait(self, pred: Callable[[], bool], what: str) -> None:
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            if pred():
                return
            self._sleep(0.5)
        raise DriverError(f"timeout waiting for {what}")

    def _invoke(self, ctl: Ctl) -> None:
        self.guard.check_invoke(ctl.name, ctl.automation_id)
        ctl.invoke()
        self._sleep(self.settle)

    def state(self) -> str:
        w = self._attach()
        if w is None:
            return "none"
        if w.message_box() is not None:
            return "modal"
        return "case_open" if " - WISO Steuer" in w.title() else "start"

    # ---------------------------------------------------------------- case
    def open_case(self, path: Path) -> None:
        path = Path(path)
        self.guard.check_case(path)
        self.current_case = None
        prefix = f"{path.stem} - WISO Steuer"
        w = self._attach()
        if w is not None and " - WISO Steuer" in w.title() and not w.title().startswith(prefix):
            raise DriverError(f"another case is open in WISO: {w.title()!r} - close it first")
        if w is not None and w.title().startswith(prefix):
            self._check_same_file(w, path)
        else:
            self._launch(path)

            def ready() -> bool:
                win = self._attach()
                return win is not None and win.title().startswith(prefix)

            self._wait(ready, f"WISO window {prefix!r}")
        self.current_case = path
        self.dismiss_blockers()

    def _check_same_file(self, w: WisoWindow, path: Path) -> None:
        """The window title only shows the file name: make sure WISO has *this* file open."""
        opened = w.opened_path()
        if opened is not None:
            if not _same_file(opened, path):
                raise DriverError(f"WISO has {opened} open (same file name as {path}) - close it first")
            return
        others = [p for p in self._known_cases() if p.name.lower() == path.name.lower()]
        others = [p for p in others if not _same_file(p, path)]
        if others:
            raise DriverError(
                f"cannot verify which file WISO has open: other cases with the same file name exist "
                f"({', '.join(map(str, others))}). Close WISO and call open_case again, or give the "
                "working copy a unique name"
            )

    def dismiss_blockers(self) -> list[str]:
        w = self._win()
        done = []
        for c in w.controls():
            if c.kind == "Button" and c.name == "Abbrechen" and "btsBelegabrufAssistent" in c.automation_id:
                self._invoke(c)
                done.append("belegabruf_assistent")
                self._sleep(1.0)
                # WISO asks "Assistenten abbrechen?" (sometimes stacked) - confirm each;
                # the user can fetch the certificates later with their own ELSTER login
                for _ in range(5):
                    box = w.message_box()
                    if box is None or "Assistent" not in box.text or "Ja" not in box.buttons:
                        break
                    box.buttons["Ja"]()
                    self._sleep(0.8)
                break
        if w.close_popups():
            done.append("popups")
        return done

    # ---------------------------------------------------------------- navigation
    def goto_section(self, label: str) -> None:
        self.guard.check_invoke(label, "")
        w = self._win()
        items = [c for c in w.controls() if c.kind == "TreeItem"]
        if not any(c.name == label for c in items):
            # start page ("Meine Steuererklärung") shows no data tree - switch to "Daten erfassen"
            theme = next(
                (
                    c
                    for c in w.controls()
                    if c.name == "Daten erfassen" and "rsNaviThemeButton" in c.automation_id
                ),
                None,
            )
            if theme is not None:
                w.post_click(theme.rect)
                self._sleep(self.settle * 2)
                items = [c for c in w.controls() if c.kind == "TreeItem"]
        hit = next((c for c in items if c.name == label), None)
        if hit is None and items:
            # the tree is virtualised: an expanded section can push later sections out of view.
            # Collapse every expanded top-level section (UIA ExpandCollapse, no mouse) and look again.
            left = min(c.rect[0] for c in items)
            for top in [c for c in items if c.rect[0] == left]:
                if top.collapse is not None and (top.is_expanded is None or top.is_expanded()):
                    top.collapse()
                    self._sleep(0.4)
            items = [c for c in w.controls() if c.kind == "TreeItem"]
            hit = next((c for c in items if c.name == label), None)
        if hit is None:
            raise DriverError(f"section {label!r} not found; available: {[c.name for c in items]}")
        w.post_click(hit.rect)
        self._sleep(self.settle * 2)

    def nav_cards(self) -> list[dict[str, str]]:
        return [
            {"path": c.automation_id.split("navilistButton")[-1], "label": c.name}
            for c in self._win().controls()
            if c.kind == "Button" and "navilistButton" in c.automation_id
        ]

    def open_card(self, path: str) -> None:
        btns = [c for c in self._win().controls() if c.kind == "Button"]
        hit = next((c for c in btns if c.automation_id.endswith("navilistButton" + path)), None)
        hit = hit or next((c for c in btns if c.automation_id.endswith(path)), None)
        if hit is None:
            available = ", ".join(d["path"] for d in self.nav_cards())
            raise DriverError(f"card {path} not found; available: {available}")
        self._invoke(hit)
        self._sleep(self.settle)

    def open_row(self, var: str) -> None:
        target = self._field(var)
        y = _mid_y(target.rect)
        btns = [
            c
            for c in self._win().controls()
            if c.kind == "Button" and any(k in c.automation_id for k in _ROW_BUTTONS)
        ]
        best = min(btns, key=lambda c: abs(_mid_y(c.rect) - y), default=None)
        if best is None or abs(_mid_y(best.rect) - y) > 15:
            raise DriverError(f"no detail button next to {var}")
        self._invoke(best)
        self._last_row = var

    # ---------------------------------------------------------------- fields
    def _dialog_ctls(self) -> list[Ctl]:
        return [
            c
            for c in self._win().controls()
            if _DLG in c.automation_id and "infoButton" not in c.automation_id and c.kind in _FIELD_KINDS
        ]

    def _field(self, var: str) -> Ctl:
        hit = next((c for c in self._dialog_ctls() if _var(c) == var), None)
        if hit is None:
            raise DriverError(f"field {var!r} not in the current dialog")
        return hit

    def list_fields(self) -> list[dict[str, Any]]:
        out = []
        for c in self._dialog_ctls():
            v = c.value()
            amt = parse_amount_text(v) if v and "€" in v else None
            out.append(
                {
                    "var": _var(c),
                    "label": c.name,
                    "kind": c.kind,
                    "value": v,
                    "amount": None if amt is None else str(amt),
                    "enabled": c.enabled,
                }
            )
        return out

    def read_field(self, var: str) -> str | None:
        return self._field(var).value()

    def _before_write(self) -> None:
        if self.current_case is None:
            raise DriverError("no case opened through the driver")
        self.guard.check_case(self.current_case)
        self.guard.ensure_backup(self.current_case)

    def set_field(self, var: str, value: str) -> dict[str, Any]:
        ctl = self._field(var)
        self.guard.check_set(ctl.name, ctl.automation_id)
        if not ctl.enabled:
            raise DriverError(f"{var} is read-only (computed or entered in a sub-dialog - try open_row)")
        self._before_write()
        old = ctl.value()
        ctl.set_value(value)
        self._sleep(0.3)
        now = self._field(var).value()
        num = parse_amount_text(now.replace("%", "") if now else None)
        same_number = num is not None and num == parse_amount_text(value.replace("%", ""))
        if now != value and not same_number:
            raise DriverError(f"verify failed for {var}: wrote {value!r}, read {now!r}")
        return {"var": var, "old": old, "new": value}

    def set_combo(self, var: str, option: str) -> dict[str, Any]:
        """Pick one entry of a dropdown (Qt combo box), verified by read-back.

        WISO's combos ignore the UIA Value pattern, and SelectionItem on their list items
        reports success without committing. They do honour ExpandCollapse + keyboard, so the
        window adapter expands the popup and walks to the wanted entry with arrow keys.
        """
        ctl = self._field(var)
        if ctl.kind != "ComboBox":
            raise DriverError(f"{var} is not a dropdown (kind: {ctl.kind})")
        self.guard.check_set(ctl.name, ctl.automation_id)
        if not ctl.enabled:
            raise DriverError(f"{var} is read-only")
        self._before_write()
        old = ctl.value()
        win = self._win()
        options = win.combo_options(ctl.automation_id)
        hit = _match_option(option, options)
        if hit is None:
            raise DriverError(f"{var} has no option {option!r} (options: {options})")
        win.combo_select(ctl.automation_id, hit)
        now: str | None = None
        for _ in range(6):  # WISO re-renders the dialog block after a combo change
            self._sleep(self.settle)
            now = self._field(var).value()
            if (now or "").strip() == hit.strip():
                break
        if (now or "").strip() != hit.strip():
            raise DriverError(f"verify failed for {var}: selected {hit!r}, read {now!r}")
        return {"var": var, "old": old, "selected": hit}

    # ---------------------------------------------------------------- tables
    def _table(self) -> TableCtl:
        tables = self._win().tables()
        if not tables:
            raise DriverError("no amount table in the current dialog (open it with open_row)")
        return tables[0]

    @staticmethod
    def _row_dict(t: TableCtl, i: int, r: list[str]) -> dict[str, Any] | None:
        d, b, a = t.col("Datum"), t.col("Bezeichnung"), t.amount_col()
        amt = parse_amount_text(r[a] if 0 <= a < len(r) else "")
        desc = r[b] if 0 <= b < len(r) else ""
        if not desc and not amt:
            return None
        return {"index": i, "date": r[d] if d >= 0 else "", "description": desc, "amount": str(amt or 0)}

    def table_rows(self) -> list[dict[str, Any]]:
        t = self._table()
        out = []
        for i, r in enumerate(t.rows()):
            x = self._row_dict(t, i, r)
            if x:
                out.append(x)
        return out

    def _named_button(self, name: str) -> Ctl:
        btn = next((c for c in self._win().controls() if c.kind == "Button" and c.name == name), None)
        if btn is None:
            raise DriverError(f"no {name!r} button in this dialog")
        return btn

    def clear_table(self, reopen: bool = True) -> list[dict[str, Any]]:
        """Delete all rows of the open table ('Alle Einträge löschen'); returns the removed rows."""
        removed = self.table_rows()
        if not removed:
            return []
        self._before_write()
        self._invoke(self._named_button("Alle Einträge löschen"))
        self._sleep(0.8)
        box = self._win().message_box()
        if box is not None:
            if "lösch" not in box.text.lower() or "Ja" not in box.buttons:
                raise DriverError(f"unexpected question while clearing: {box.text!r}")
            box.buttons["Ja"]()
            self._sleep(0.8)
        left = self.table_rows()
        if left:
            raise DriverError(f"table still has rows after clearing: {left}")
        if reopen and self._last_row:
            # after clearing WISO stops appending empty rows until the dialog is confirmed and reopened
            self.ok()
            self.open_row(self._last_row)
            self._sleep(self.settle)
        return removed

    def set_radio(self, var: str, option: str) -> dict[str, str]:
        radios: list[Ctl] = []
        hit = None
        for _ in range(12):  # follow-up questions appear a moment after a field commit
            radios = [
                c for c in self._dialog_ctls() if c.kind == "RadioButton" and _radio_group(_var(c)) == var
            ]
            hit = next((c for c in radios if c.name == option), None)
            if hit is not None:
                break
            self._sleep(0.5)
        if hit is None or hit.select is None:
            raise DriverError(f"radio {var} has no option {option!r} (options: {[c.name for c in radios]})")
        self.guard.check_set(hit.name, hit.automation_id)
        self._before_write()
        hit.select()
        check = hit.is_selected
        for _ in range(8):  # WISO re-renders the question block; re-read until the state is visible
            self._sleep(0.5)
            if check is None or check():
                break
            fresh = [
                c for c in self._dialog_ctls() if c.kind == "RadioButton" and _radio_group(_var(c)) == var
            ]
            again = next((c for c in fresh if c.name == option), None)
            if again is not None and again.is_selected is not None and again is not hit:
                check = again.is_selected
        else:
            raise DriverError(f"radio {var}={option} not selected after write")
        return {"var": var, "selected": option}

    def new_entry(self) -> None:
        """Start a new entry in a list dialog (devices, household services, ...)."""
        self._invoke(self._named_button("Eintrag hinzufügen"))
        self._sleep(self.settle)

    def tree_status(self, only_problems: bool = False) -> list[dict[str, str]]:
        """Status symbol next to every visible navigation entry, read from a background screenshot."""
        w = self._win()
        tree = w.tree_rect()
        if tree is None:
            raise DriverError("navigation tree not visible")
        img = w.capture()
        out = []
        for c in w.controls():
            if c.kind != "TreeItem" or c.name.startswith(" ") or not c.name.strip():
                continue
            y = _mid_y(c.rect)
            if not tree[1] <= y <= tree[3]:
                continue
            best = (0, (250, 250, 250))
            for x in range(max(c.rect[0], tree[2] - 130), tree[2]):
                px = img.getpixel((x, y))[:3]
                sat = max(px) - min(px)
                if sat > best[0]:
                    best = (sat, px)
            status = classify_status(best[1]) if best[0] > 60 else "leer"
            if not only_problems or status in ("fehler", "hinweis"):
                out.append({"label": c.name.strip(), "status": status})
        if only_problems:
            out = [e for e in out if e["status"] == "fehler"] + [e for e in out if e["status"] == "hinweis"]
        return out

    def list_entries(self) -> list[dict[str, Any]]:
        """Numbered entries of list dialogs as shown in the navigation tree ('2) Toshiba ...')."""
        out = []
        for c in self._win().controls():
            if c.kind != "TreeItem" or c.name.startswith(" "):
                continue  # padded names are cells of the list table itself
            m = _ENTRY.match(c.name.strip())
            if m:
                out.append({"index": int(m.group(1)), "label": m.group(2)})
        return out

    def open_list_entry(self, text: str) -> dict[str, str]:
        """Open the list entry whose navigation label contains `text` (must be unique)."""
        w = self._win()
        hits = [
            c
            for c in w.controls()
            if c.kind == "TreeItem"
            and not c.name.startswith(" ")
            and _ENTRY.match(c.name.strip())
            and text.lower() in c.name.lower()
        ]
        if not hits:
            raise DriverError(f"no list entry contains {text!r}: {[e['label'] for e in self.list_entries()]}")
        if len(hits) > 1:
            raise DriverError(f"{text!r} is ambiguous: {[c.name.strip() for c in hits]}")
        w.post_click(hits[0].rect)  # posted to WISO's own window - no real mouse
        self._sleep(self.settle)
        return {"opened": hits[0].name.strip()}

    def delete_entry(self) -> dict[str, bool]:
        """Delete the open list entry (trash button), confirming only WISO's delete question."""
        w = self._win()
        unnamed = sorted(
            (
                c
                for c in w.controls()
                if c.kind == "Button"
                and not c.name
                and c.automation_id.endswith(_DIALOG_BUTTONS + ".rsPushButton")
            ),
            key=lambda c: c.rect[0],
        )
        if len(unnamed) < 2:
            raise DriverError("no delete button in this dialog (open a list entry first)")
        self._before_write()
        w.post_click(unnamed[1].rect)  # [bookmark, trash, assistant]
        self._sleep(0.8)
        box = w.message_box()
        if box is None:
            raise DriverError("WISO did not ask to confirm the deletion - nothing deleted")
        if "lösch" not in box.text.lower() or "Ja" not in box.buttons:
            for answer in ("Nein", "Abbrechen"):
                if answer in box.buttons:
                    box.buttons[answer]()
                    break
            raise DriverError(f"unexpected question instead of delete confirmation: {box.text!r}")
        box.buttons["Ja"]()
        self._sleep(self.settle)
        return {"deleted": True}

    def toggle_checkbox(self, var: str, checked: bool) -> dict[str, Any]:
        cb = next((c for c in self._dialog_ctls() if c.kind == "CheckBox" and _var(c) == var), None)
        if cb is None or cb.toggle is None or cb.is_checked is None:
            raise DriverError(f"no checkbox {var!r} in the current dialog")
        self.guard.check_set(cb.name, cb.automation_id)
        if cb.is_checked() != checked:
            self._before_write()
            cb.toggle()
            for _ in range(6):
                self._sleep(0.3)
                if cb.is_checked() == checked:
                    break
            else:
                raise DriverError(f"checkbox {var} did not change to {checked}")
        return {"var": var, "checked": checked}

    def table_cells(self) -> dict[str, Any]:
        """Raw view of the open table: column headers and all cell texts."""
        t = self._table()
        return {"headers": t.headers(), "rows": t.rows()}

    def set_table_cell(self, row: int, column: str, value: str) -> dict[str, Any]:
        """Write one cell of the open table, addressed by row index and column header (verified)."""
        t = self._table()
        c = t.col(column)
        if c < 0:
            raise DriverError(f"no column {column!r} (columns: {t.headers()})")
        rows = t.rows()
        if not 0 <= row < len(rows):
            raise DriverError(f"row {row} out of range ({len(rows)} rows)")
        self._before_write()
        old = rows[row][c]
        t.set_cell(row, c, value)
        self._sleep(0.3)
        new = t.rows()[row][c]
        if not _same_cell(new, value):
            raise DriverError(
                f"value not accepted in {column!r} row {row}: shows {new!r} "
                "(drop-down cells cannot be set in the background)"
            )
        return {"row": row, "column": column, "old": old, "new": new}

    def add_table_row(
        self, description: str, amount: Decimal, date: str | None = None, date_column: bool = False
    ) -> int:
        """Append one row. By default the date is prefixed to the description (works in the background).
        date_column=True fills WISO's date column - only possible while WISO is the foreground window."""
        wiso_date = format_date(date) if date else None
        if wiso_date and not date_column:
            description = f"{wiso_date} {description}"
        self.guard.check_set(description, "")
        if wiso_date and date_column and not self._win().is_foreground():
            raise DriverError(
                "the date column only accepts input while WISO is the foreground window - "
                "bring WISO to the front or omit date_column"
            )
        t = self._table()
        dcol, bcol, acol = t.col("Datum"), t.col("Bezeichnung"), t.amount_col()
        if bcol < 0 or acol < 0:
            raise DriverError(f"table has no Bezeichnung/Betrag columns: {t.headers()}")
        if wiso_date and date_column and dcol < 0:
            raise DriverError("this table has no date column - omit date_column")
        self._before_write()
        rows = t.rows()
        idx = next((i for i, r in enumerate(rows) if self._row_dict(t, i, r) is None), None)
        if idx is None:
            # e.g. Berufsverbände: WISO offers no further empty row via UIA; reopening the dialog was tried
            # and loses descriptions of earlier rows - so refuse instead of risking silent data loss
            raise DriverError("table has no empty row (this table does not append rows) - combine entries")
        t.set_cell(idx, bcol, description)
        t.set_cell(idx, acol, format_amount(amount))
        self._sleep(0.3)
        if t.rows()[idx][bcol] != description:
            # some tables (Berufsverbände) only keep the description once the amount made the row real
            t.set_cell(idx, bcol, description)
            self._sleep(0.3)
        if wiso_date and date_column:
            # the date column only accepts typed input: open its editor, post keys to WISO's own window.
            # No ESCAPE afterwards - outside an editor it would trigger the dialog's "Abbrechen".
            w = self._win()
            w.post_double_click(t.cell_rect(idx, dcol))
            self._sleep(0.8)
            w.post_text(wiso_date.replace(".", ""))
            w.post_key("ENTER")
            self._sleep(0.8)
        row = t.rows()[idx]
        shown_date = wiso_date[:6] if (wiso_date and date_column) else None  # WISO displays DD.MM.
        if (
            row[bcol] != description
            or parse_amount_text(row[acol]) != amount
            or (shown_date and row[dcol] != shown_date)
        ):
            raise DriverError(f"verify failed for table row {idx}: {row}")
        return idx

    # ---------------------------------------------------------------- commit
    def _dialog_button(self, name: str) -> Ctl:
        hit = next(
            (
                c
                for c in self._win().controls()
                if c.kind == "Button" and c.name == name and _DIALOG_BUTTONS in c.automation_id
            ),
            None,
        )
        if hit is None:
            raise DriverError(f"no {name!r} button - is a dialog open?")
        return hit

    def ok(self) -> dict[str, Any]:
        """Commit the current dialog. Plausibility hints are acknowledged with 'Nicht jetzt' and returned."""
        w = self._win()
        before = [t.rows() for t in w.tables()]
        self._invoke(self._dialog_button("OK"))
        box = w.message_box()
        if box is None:
            self._sleep(0.5)
            after = [t.rows() for t in w.tables()]
            if before and after == before:
                raise DriverError(
                    "dialog still open after OK - WISO did not accept it (required field empty?)"
                )
            return {"hint": None}
        if "Nicht jetzt" in box.buttons and "Hinweise" in box.text:
            self.guard.check_invoke("Nicht jetzt", "")
            box.buttons["Nicht jetzt"]()
            self._sleep(self.settle)
            return {"hint": box.text}
        raise DriverError(f"WISO asks: {box.text!r} (buttons {list(box.buttons)}) - answer in WISO")

    def cancel(self) -> None:
        self._invoke(self._dialog_button("Abbrechen"))
        box = self._win().message_box()
        if box is None:
            return
        if "Ja" not in box.buttons:
            raise DriverError(f"unexpected question on cancel: {box.text!r}")
        self.guard.check_invoke("Ja", "")
        box.buttons["Ja"]()
        self._sleep(self.settle)

    def dialog_open(self) -> bool:
        """True while a dialog (with OK/Abbrechen) is shown - e.g. one the user is editing."""
        try:
            self._dialog_button("Abbrechen")
        except DriverError:
            return False
        return True

    def leave_dialogs(self, max_levels: int = 6) -> int:
        """Cancel (discard) open dialog levels until a navigation page is shown. Returns levels closed."""
        n = 0
        self.dismiss_blockers()
        for _ in range(max_levels):
            try:
                self._dialog_button("Abbrechen")
            except DriverError:
                break
            self.cancel()
            n += 1
        return n

    def save(self) -> None:
        if self.current_case is None:
            raise DriverError("no case opened through the driver")
        self.guard.check_case(self.current_case)
        w = self._win()
        btn = next((c for c in w.controls() if c.kind == "Button" and c.name == "Speichern"), None)
        if btn is None:
            raise DriverError("Speichern button not found")
        self._invoke(btn)

    def screenshot(self, path: Path) -> Path:
        self._win().screenshot(str(path))
        return Path(path)


# ====================================================================== real adapter
def _radio_group(var: str) -> str:
    """Radio ids repeat their group name: 'g.g' or 'g.Mann.g.Mann' -> 'g' / 'g.Mann'."""
    parts = var.split(".")
    half = len(parts) // 2
    if len(parts) % 2 == 0 and parts[:half] == parts[half:]:
        return ".".join(parts[:half])
    return parts[0]


def _match_option(option: str, options: list[str]) -> str | None:
    """Fuzzy-pick one entry of a dropdown: exact (case-insensitive), then prefix, then substring."""
    want = option.strip().lower()
    if not want:
        return None
    for o in options:
        if o.strip().lower() == want:
            return o
    for o in options:
        if o.strip().lower().startswith(want):
            return o
    for o in options:
        if want in o.strip().lower():
            return o
    return None


def _is_wiso_table(automation_id: str, class_name: str) -> bool:
    """WISO grids are rsTableView widgets: usually the id suffix, sometimes (te12_...) only the class."""
    return automation_id.endswith("rsTableView") or class_name == "rsTableView"


class PywinautoWindow:  # pragma: no cover - exercised by real-life tests (-m wiso)
    """WisoWindow backed by the live WISO main window (pywinauto, UIA backend)."""

    KINDS = frozenset({"Button", "Edit", "CheckBox", "RadioButton", "ComboBox", "TreeItem"})

    def __init__(self, wrapper: Any) -> None:
        self.w = wrapper

    def title(self) -> str:
        return str(self.w.window_text())

    def opened_path(self) -> Path | None:
        """Case file from the WISO process's command line (None if WISO was started without one)."""
        try:
            pid = int(self.w.process_id())
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        return case_from_cmdline(out.strip())

    @staticmethod
    def _value_of(el: Any) -> Callable[[], str | None]:
        def get() -> str | None:
            try:
                return str(el.iface_value.CurrentValue)
            except Exception:
                try:
                    return str(el.window_text())
                except Exception:
                    return None

        return get

    @staticmethod
    def _invoker(el: Any) -> Callable[[], None]:
        def invoke() -> None:
            if not hasattr(el, "invoke"):  # never fall back to real mouse clicks (user may be working)
                raise DriverError(f"control {el.element_info.name!r} has no Invoke pattern")
            el.invoke()

        return invoke

    @staticmethod
    def _setter(el: Any) -> Callable[[str], None]:
        def set_value(v: str) -> None:
            el.iface_value.SetValue(v)

        return set_value

    def controls(self) -> list[Ctl]:
        out = []
        for el in self.w.descendants():
            info = el.element_info
            if info.control_type not in self.KINDS:
                continue
            r = info.rectangle
            out.append(
                Ctl(
                    kind=info.control_type,
                    name=info.name or "",
                    automation_id=info.automation_id or "",
                    value=self._value_of(el),
                    enabled=bool(info.enabled),
                    rect=(r.left, r.top, r.right, r.bottom),
                    invoke=self._invoker(el),
                    set_value=self._setter(el),
                    select=self._selector(el) if info.control_type == "RadioButton" else None,
                    is_selected=self._is_selected(el) if info.control_type == "RadioButton" else None,
                    toggle=self._toggler(el) if info.control_type == "CheckBox" else None,
                    is_checked=self._checked(el) if info.control_type == "CheckBox" else None,
                    collapse=self._collapser(el) if info.control_type == "TreeItem" else None,
                    is_expanded=self._expanded(el) if info.control_type == "TreeItem" else None,
                )
            )
        return out

    @staticmethod
    def _collapser(el: Any) -> Callable[[], None]:
        def collapse() -> None:  # ExpandCollapse pattern - no mouse
            el.iface_expand_collapse.Collapse()

        return collapse

    @staticmethod
    def _expanded(el: Any) -> Callable[[], bool]:
        def expanded() -> bool:
            try:
                return int(el.iface_expand_collapse.CurrentExpandCollapseState) == 1
            except Exception:
                return False

        return expanded

    @staticmethod
    def _toggler(el: Any) -> Callable[[], None]:
        def toggle() -> None:  # Toggle pattern - no mouse
            el.iface_toggle.Toggle()

        return toggle

    @staticmethod
    def _checked(el: Any) -> Callable[[], bool]:
        def checked() -> bool:
            return int(el.iface_toggle.CurrentToggleState) == 1

        return checked

    @staticmethod
    def _is_selected(el: Any) -> Callable[[], bool]:
        def is_selected() -> bool:
            return bool(el.iface_selection_item.CurrentIsSelected)

        return is_selected

    @staticmethod
    def _selector(el: Any) -> Callable[[], None]:
        def select() -> None:  # SelectionItem pattern - no mouse, works in the background
            el.iface_selection_item.Select()

        return select

    def _combo(self, automation_id: str) -> Any:
        for c in self.w.descendants(control_type="ComboBox"):
            if (c.element_info.automation_id or "") == automation_id:
                return c
        raise DriverError(f"combo {automation_id!r} not found in the current window")

    @staticmethod
    def _combo_popup() -> Rect:
        """The dropdown list is its own top-level window (Qt), not a child of the dialog."""
        from pywinauto import Desktop

        for w in Desktop(backend="uia").windows(class_name="QComboBoxPrivateContainer"):
            r = w.rectangle()
            return (r.left, r.top, r.right, r.bottom)
        raise DriverError("dropdown did not open (no QComboBoxPrivateContainer)")

    def _combo_items(self, popup: Rect) -> list[Any]:
        """Entry elements: they hang off the main window, so filter them by the popup's vertical span."""
        return [
            it
            for it in self.w.descendants(control_type="ListItem")
            if popup[1] <= it.rectangle().top <= popup[3]
        ]

    def combo_options(self, automation_id: str) -> list[str]:
        """Expand the dropdown, read its entries, close it again."""
        el = self._combo(automation_id)
        el.expand()
        time.sleep(0.6)
        try:
            return [it.window_text() for it in self._combo_items(self._combo_popup())]
        finally:
            try:
                el.collapse()
            except Exception:  # noqa: BLE001 - closing is best effort
                pass

    def combo_select(self, automation_id: str, option: str) -> None:
        """Walk the open dropdown with arrow keys; WISO commits on ENTER."""
        from pywinauto.keyboard import send_keys

        el = self._combo(automation_id)
        el.expand()
        time.sleep(0.6)
        items = [it.window_text() for it in self._combo_items(self._combo_popup())]
        try:
            current = str(el.iface_value.CurrentValue)
        except Exception:  # noqa: BLE001 - unreadable means "start at the top"
            current = ""
        start = items.index(current) if current in items else 0
        target = items.index(option) if option in items else start
        el.set_focus()
        time.sleep(0.2)
        key = "{DOWN}" if target >= start else "{UP}"
        for _ in range(abs(target - start)):
            send_keys(key)
            time.sleep(0.1)
        send_keys("{ENTER}")
        time.sleep(0.8)

    def tables(self) -> list[TableCtl]:
        from pywinauto.uia_defines import IUIA
        uia = IUIA().UIA_dll
        out = []
        for t in self.w.descendants(control_type="Table"):
            if not _is_wiso_table(t.element_info.automation_id or "", t.element_info.class_name or ""):
                continue
            grid = t.element_info.element.GetCurrentPattern(uia.UIA_GridPatternId).QueryInterface(
                uia.IUIAutomationGridPattern
            )

            def rows(grid: Any = grid) -> list[list[str]]:
                return [
                    [grid.GetItem(r, c).CurrentName for c in range(grid.CurrentColumnCount)]
                    for r in range(grid.CurrentRowCount)
                ]

            def set_cell(r: int, c: int, text: str, grid: Any = grid) -> None:
                pat = grid.GetItem(r, c).GetCurrentPattern(uia.UIA_ValuePatternId)
                pat.QueryInterface(uia.IUIAutomationValuePattern).SetValue(text)

            def cell_rect(r: int, c: int, grid: Any = grid) -> Rect:
                b = grid.GetItem(r, c).CurrentBoundingRectangle
                return (b.left, b.top, b.right, b.bottom)

            def headers(el: Any = t.element_info.element) -> list[str]:
                tp = el.GetCurrentPattern(uia.UIA_TablePatternId).QueryInterface(
                    uia.IUIAutomationTablePattern
                )
                hs = tp.GetCurrentColumnHeaders()
                return [hs.GetElement(i).CurrentName for i in range(hs.Length)]

            out.append(TableCtl(rows=rows, set_cell=set_cell, cell_rect=cell_rect, headers=headers))
        return out

    def message_box(self) -> MessageBox | None:
        holders = [self.w] + [
            c
            for c in self.w.children()
            if (c.element_info.automation_id or "").endswith("btsBelegabrufAssistent")
        ]
        for c in (child for h in holders for child in h.children()):
            if (c.element_info.automation_id or "").endswith("BtsMessageBox"):
                text = " ".join(t.element_info.name for t in c.descendants(control_type="Text"))
                buttons = {b.element_info.name: b.invoke for b in c.descendants(control_type="Button")}
                return MessageBox(text, buttons)
        return None

    def post_click(self, rect: Rect) -> None:
        self._post_mouse(rect, ((0x200, 0), (0x201, 1), (0x202, 0)))

    def _post_mouse(self, rect: Rect, msgs: tuple[tuple[int, int], ...]) -> None:
        import ctypes
        from ctypes import wintypes

        u32 = ctypes.windll.user32  # type: ignore[attr-defined]
        pt = wintypes.POINT((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        u32.ScreenToClient(self.w.handle, ctypes.byref(pt))
        lp = (pt.y << 16) | (pt.x & 0xFFFF)
        for msg, wp in msgs:
            u32.PostMessageW(self.w.handle, msg, wp, lp)
            time.sleep(0.05)

    def is_foreground(self) -> bool:
        import ctypes

        return bool(ctypes.windll.user32.GetForegroundWindow() == self.w.handle)  # type: ignore[attr-defined]

    def post_double_click(self, rect: Rect) -> None:
        self._post_mouse(rect, ((0x200, 0), (0x201, 1), (0x202, 0), (0x203, 1), (0x202, 0)))

    def post_text(self, text: str) -> None:
        import ctypes

        for ch in text:  # WM_CHAR to WISO's own window - never to the foreground app
            ctypes.windll.user32.PostMessageW(self.w.handle, 0x0102, ord(ch), 1)  # type: ignore[attr-defined]
            time.sleep(0.05)

    def post_key(self, key: str) -> None:
        import ctypes

        vk = {"ENTER": 0x0D, "TAB": 0x09}[key]  # deliberately no ESCAPE (= dialog cancel)
        u32 = ctypes.windll.user32  # type: ignore[attr-defined]
        u32.PostMessageW(self.w.handle, 0x0100, vk, 1)
        if key == "ENTER":
            u32.PostMessageW(self.w.handle, 0x0102, vk, 1)
        u32.PostMessageW(self.w.handle, 0x0101, vk, 0xC0000001)

    def close_popups(self) -> int:
        from pywinauto import Desktop

        n = 0
        for c in self.w.children():
            if (c.element_info.automation_id or "").endswith("VideoDialog-Popup"):
                c.close()
                n += 1
        for top in Desktop(backend="uia").windows(process=self.w.element_info.process_id):
            if top.element_info.class_name == "BTS::FormViewer":
                top.close()
                n += 1
        return n

    def tree_rect(self) -> Rect | None:
        trees = [t for t in self.w.descendants(control_type="Tree") if t.element_info.rectangle.left < 1200]
        if not trees:
            return None
        r = max(trees, key=lambda t: t.element_info.rectangle.height()).element_info.rectangle
        return (r.left, r.top, r.right, r.bottom)

    def capture(self) -> Any:
        """Background screenshot as an object with getpixel((screen_x, screen_y))."""
        import ctypes
        import tempfile
        from ctypes import wintypes

        from PIL import Image

        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "wiso.png")
            self.screenshot(path)
            img = Image.open(path).convert("RGB")
            img.load()
        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(self.w.handle, ctypes.byref(r))  # type: ignore[attr-defined]
        left, top = r.left, r.top

        class _Shifted:
            def getpixel(self, xy: tuple[int, int]) -> Any:
                x, y = xy[0] - left, xy[1] - top
                if 0 <= x < img.width and 0 <= y < img.height:
                    return img.getpixel((x, y))
                return (250, 250, 250)

        return _Shifted()

    def screenshot(self, path: str) -> None:
        import ctypes
        from ctypes import wintypes

        from PIL import Image

        u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32  # type: ignore[attr-defined]
        hwnd = self.w.handle
        r = wintypes.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        hdc = u32.GetWindowDC(hwnd)
        mdc = g32.CreateCompatibleDC(hdc)
        bmp = g32.CreateCompatibleBitmap(hdc, w, h)
        g32.SelectObject(mdc, bmp)
        u32.PrintWindow(hwnd, mdc, 2)
        header = (ctypes.c_uint32 * 10)(40, w, (-h) & 0xFFFFFFFF, 1 | (32 << 16), 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        g32.GetDIBits(mdc, bmp, 0, h, buf, header, 0)
        Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1).save(path)
        g32.DeleteObject(bmp)
        g32.DeleteDC(mdc)
        u32.ReleaseDC(hwnd, hdc)


def attach_real() -> PywinautoWindow | None:  # pragma: no cover - real-life only
    from pywinauto import Desktop

    wins = Desktop(backend="uia").windows(class_name="rsWspMainWindow")
    return PywinautoWindow(wins[0]) if wins else None


def launcher(exe: Path) -> Callable[[Path], None]:  # pragma: no cover - real-life only
    def launch(path: Path) -> None:
        subprocess.Popen([str(exe), str(path)], cwd=str(exe.parent))

    return launch
