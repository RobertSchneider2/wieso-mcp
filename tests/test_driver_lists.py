"""List dialogs (devices, phone connections, childcare, ...), checkboxes and generic table cells."""

from decimal import Decimal

import pytest
from test_driver import BTNW, DLG

from wieso_mcp.ui.driver import DriverError, MessageBox
from wieso_mcp.ui.fake import FakeTable


def _nav(win, labels):
    opened = []
    for i, label in enumerate(labels):
        rect = (40, 500 + i * 40, 380, 530 + i * 40)
        win.add("TreeItem", f"{i + 1}) {label}", "", rect=rect)
    win.on_click = lambda r: opened.append(r)
    return opened


def test_list_entries_returns_numbered_navigation_items(env):
    drv, win, *_ = env
    _nav(win, ["Kind (01.01.2019)", "Toshiba Festplatte", "Reichelt RAID-Gehäuse"])
    win.add("TreeItem", "Arbeitsmittel", "")
    win.add("TreeItem", " 19.03.2025 ", "")  # list-row cell, not a navigation entry
    assert [e["label"] for e in drv.list_entries()] == [
        "Kind (01.01.2019)",
        "Toshiba Festplatte",
        "Reichelt RAID-Gehäuse",
    ]
    assert drv.list_entries()[1]["index"] == 2


def test_open_list_entry_clicks_unique_match(env):
    drv, win, *_ = env
    opened = _nav(win, ["Toshiba Festplatte", "Reichelt RAID-Gehäuse", "Reichelt USB-Gehäuse"])
    drv.open_list_entry("Toshiba")
    assert opened == [(40, 500, 380, 530)]
    with pytest.raises(DriverError, match="ambiguous"):
        drv.open_list_entry("Reichelt")
    with pytest.raises(DriverError, match="no list entry"):
        drv.open_list_entry("Apple")


def _trash(win, question, on_yes):
    win.add("Button", "", BTNW, rect=(999, 2025, 1047, 2073))  # bookmark
    clicked = {}

    def ask(rect):
        if rect == (1059, 2025, 1107, 2073):
            clicked["trash"] = True
            win.box = MessageBox(question, {"Ja": on_yes, "Nein": lambda: setattr(win, "box", None)})

    win.add("Button", "", BTNW, rect=(1059, 2025, 1107, 2073))  # trash
    win.add("Button", "", BTNW, rect=(1885, 2019, 1945, 2079))  # assistant
    win.add("Button", "OK", BTNW, rect=(2500, 2025, 2600, 2073))
    win.on_click = ask
    return clicked


def test_delete_entry_confirms_only_the_delete_question(env):
    drv, win, *_ = env
    win.add("Edit", "Bezeichnung", DLG + "am11a_Bezeichnung", "Fuji LCD")
    deleted = []

    def yes():
        deleted.append(1)
        win.box = None

    clicked = _trash(win, "Daten wirklich löschen? Möchtest du die hier erfassten Daten löschen?", yes)
    res = drv.delete_entry()
    assert clicked and deleted == [1] and res == {"deleted": True}


def test_delete_entry_refuses_unexpected_question(env):
    drv, win, *_ = env
    deleted = []
    _trash(win, "Änderungen speichern?", lambda: deleted.append(1))
    with pytest.raises(DriverError, match="unexpected"):
        drv.delete_entry()
    assert deleted == [] and win.box is None  # answered 'Nein'


def test_toggle_checkbox_sets_state_and_verifies(env):
    drv, win, *_ = env
    cb = win.add("CheckBox", "Als Arbeitnehmer", DLG + "te10a_Nutzung_AN.Mann")
    assert drv.toggle_checkbox("te10a_Nutzung_AN.Mann", True) == {
        "var": "te10a_Nutzung_AN.Mann",
        "checked": True,
    }
    assert cb.is_checked() is True
    drv.toggle_checkbox("te10a_Nutzung_AN.Mann", True)  # idempotent
    assert cb.is_checked() is True
    drv.toggle_checkbox("te10a_Nutzung_AN.Mann", False)
    assert cb.is_checked() is False


def test_set_table_cell_by_column_name_with_number_verify(env):
    drv, win, *_ = env
    months = [[m, "0,00 €", "0,00 €"] for m in ("Januar", "Februar", "März")]
    win.table = FakeTable(rows=months, headers=["Monat", "Rechnungsbetrag", "Pauschale"], auto_append=False)
    res = drv.set_table_cell(1, "Rechnungsbetrag", "30,00")
    assert win.table.rows[1][1] == "30,00 €"
    assert res == {"row": 1, "column": "Rechnungsbetrag", "old": "0,00 €", "new": "30,00 €"}
    with pytest.raises(DriverError, match="no column"):
        drv.set_table_cell(1, "Betrag", "1")
    with pytest.raises(DriverError, match="row 7"):
        drv.set_table_cell(7, "Rechnungsbetrag", "1")


def test_set_table_cell_detects_rejected_write(env):
    drv, win, *_ = env
    win.table = FakeTable(
        rows=[["Bitte auswählen...", "0,— €", "0,— €"]],
        headers=["Gezahlt von", "Aufwendungen", "Erstattungen"],
        reject_values=True,
    )
    with pytest.raises(DriverError, match="not accepted"):
        drv.set_table_cell(0, "Gezahlt von", "Max")


def test_amount_cells_compare_numerically():
    from wieso_mcp.ui.driver import _same_cell

    assert _same_cell("254,— €", "254,00")
    assert _same_cell("Max", "Max")
    assert not _same_cell("Bitte auswählen...", "Max")
    assert _same_cell("1.143,–– €", str(Decimal("1143")).replace(".", ","))


def test_percent_cells_compare_numerically():
    from wieso_mcp.ui.driver import _same_cell

    assert _same_cell("50,00 %", "50")
    assert _same_cell("80,00 %", "80 %")
    assert not _same_cell("100,00 %", "50")
