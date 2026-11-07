"""In-memory stand-in for the WISO main window, used by unit tests of the driver."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .driver import Ctl, MessageBox, Rect, TableCtl


@dataclass
class FakeTable:
    rows: list[list[str]] = field(default_factory=lambda: [["", "", "0,00 €", "0,— €"]])
    reject_values: bool = False
    reject_dates: bool = False
    headers: list[str] = field(default_factory=lambda: ["Datum", "Bezeichnung", "Betrag", "Gerundet"])
    auto_append: bool = True  # False: like WISO's Berufsverbände table (new row only after reopening)
    drop_first_description: bool = False  # Berufsverbände: placeholder row ignores the first description

    def as_ctl(self) -> TableCtl:
        return TableCtl(
            rows=lambda: [list(r) for r in self.rows],
            set_cell=self._set,
            cell_rect=lambda r, c: (c * 100, r * 50, c * 100 + 90, r * 50 + 40),
            headers=lambda: list(self.headers),
        )

    def _col(self, name: str) -> int:
        return self.headers.index(name) if name in self.headers else -1

    def _empty_row(self) -> list[str]:
        blank = {"Anzahl": "1,00", "Datum": "", "Bezeichnung": "", "Gerundet": "0,— €"}
        return [blank.get(h, "0,00 €") for h in self.headers]

    def cell_at(self, rect: Rect) -> tuple[int, int]:
        return rect[1] // 50, rect[0] // 100

    def _set(self, r: int, c: int, text: str) -> None:
        if self.reject_values or c == self._col(
            "Datum"
        ):  # like WISO: the date column ignores the Value pattern
            return
        amount = c == self._col("Betrag") or self.headers[c].lower().endswith("betrag")
        if (
            self.drop_first_description
            and c == self._col("Bezeichnung")
            and self.rows[r][self._col("Betrag")] in ("0,00 €", "")
        ):
            return
        if amount:
            text = f"{text} €"
        self.rows[r][c] = text
        if (
            c == self._col("Betrag") and self.auto_append and r == len(self.rows) - 1
        ):  # WISO appends an empty row once the last row gets an amount
            self.rows.append(self._empty_row())


@dataclass
class FakeCombo:
    """Qt-style dropdown: the value only changes when the list entry is really picked."""

    options: list[str]
    current: str
    open: bool = False
    reject: bool = False  # the Value-pattern behaviour: reports success, commits nothing


class FakeWindow:
    def __init__(self, title: str = "probe - WISO Steuer 2026") -> None:
        self._title = title
        self.opened: Path | None = None  # full path of the open case (None: unknown)
        self.ctls: list[Ctl] = []
        self.table: FakeTable | None = None
        self.box: MessageBox | None = None
        self.clicks: list[Rect] = []
        self.invoked: list[str] = []
        self.popups_closed = 0
        self.on_click: Callable[[Rect], None] | None = None
        self.keys: list[str] = []
        self.table_visible = True  # False once a dialog with the table was confirmed
        self.selected: dict[str, str] = {}
        self.checked: dict[str, bool] = {}
        self.combos: dict[str, FakeCombo] = {}
        self.combo_picks: list[tuple[str, str]] = []
        self.tree: Rect | None = None
        self.image: Any = None
        self.foreground = False
        self._editing: tuple[int, int] | None = None
        self._typed = ""

    # --- builder helpers -------------------------------------------------
    def add(
        self,
        kind: str,
        name: str = "",
        auto_id: str = "",
        value: str | None = None,
        enabled: bool = True,
        rect: Rect = (0, 0, 10, 10),
        on_invoke: Callable[[], None] | None = None,
    ) -> Ctl:
        holder: dict[str, str | None] = {"v": value}

        def invoke() -> None:
            self.invoked.append(auto_id or name)
            if on_invoke:
                on_invoke()

        def set_value(v: str) -> None:
            holder["v"] = v

        ctl = Ctl(kind, name, auto_id, lambda: holder["v"], enabled, rect, invoke, set_value)
        if kind == "RadioButton":

            def select() -> None:
                self.selected[auto_id] = name

            ctl.select = select
            ctl.is_selected = lambda: self.selected.get(auto_id) == name
        if kind == "CheckBox":

            def toggle() -> None:
                self.checked[auto_id] = not self.checked.get(auto_id, False)

            ctl.toggle = toggle
            ctl.is_checked = lambda: self.checked.get(auto_id, False)
        self.ctls.append(ctl)
        return ctl

    # --- WisoWindow protocol ----------------------------------------------
    def add_combo(
        self,
        name: str,
        auto_id: str,
        options: list[str],
        current: str | None = None,
        reject: bool = False,
    ) -> Ctl:
        combo = FakeCombo(list(options), current if current is not None else options[0], reject=reject)
        self.combos[auto_id] = combo
        ctl = Ctl(
            "ComboBox",
            name,
            auto_id,
            lambda a=auto_id: self.combos[a].current,
            True,
            (0, 0, 10, 10),
            lambda: None,
            lambda _v: None,
        )
        self.ctls.append(ctl)
        return ctl

    def combo_options(self, automation_id: str) -> list[str]:
        combo = self.combos[automation_id]
        combo.open = True
        return list(combo.options)

    def combo_select(self, automation_id: str, option: str) -> None:
        combo = self.combos[automation_id]
        self.combo_picks.append((automation_id, option))
        if not combo.reject and option in combo.options:
            combo.current = option
        combo.open = False

    def title(self) -> str:
        return self._title

    def opened_path(self) -> Path | None:
        return self.opened

    def controls(self) -> list[Ctl]:
        return list(self.ctls)

    def tables(self) -> list[TableCtl]:
        return [self.table.as_ctl()] if self.table and self.table_visible else []

    def message_box(self) -> MessageBox | None:
        return self.box

    def post_click(self, rect: Rect) -> None:
        self.clicks.append(rect)
        if self.on_click:
            self.on_click(rect)

    def is_foreground(self) -> bool:
        return self.foreground

    def post_double_click(self, rect: Rect) -> None:
        self.clicks.append(rect)
        self._editing = self.table.cell_at(rect) if self.table else None
        self._typed = ""

    def post_text(self, text: str) -> None:
        self.keys.append(text)
        self._typed += text

    def post_key(self, key: str) -> None:
        self.keys.append(key)
        if key == "ENTER" and self._editing and self.table and self._editing[1] == self.table._col("Datum"):
            r, _ = self._editing
            d = self._typed
            if not self.table.reject_dates and len(d) == 8 and d.isdigit():
                self.table.rows[r][self.table._col("Datum")] = f"{d[:2]}.{d[2:4]}."
            self._editing = None

    def close_popups(self) -> int:
        n, self.popups_closed = self.popups_closed, 0
        return n

    def tree_rect(self) -> Rect | None:
        return self.tree

    def capture(self) -> Any:
        return self.image

    def screenshot(self, path: str) -> None:
        with open(path, "wb") as fh:
            fh.write(b"PNG")
