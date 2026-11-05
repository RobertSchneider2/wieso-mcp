from decimal import Decimal
from pathlib import Path

import pytest

from wieso_mcp.paths import default_program_year
from wieso_mcp.safety import Blocked, SafetyGuard
from wieso_mcp.ui.driver import DriverError, MessageBox, WisoDriver, format_amount, parse_amount_text
from wieso_mcp.ui.fake import FakeTable

PROBE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "private" / f"probe.steuer{default_program_year() - 1}"
)
DLG = "rsCentralDialogScrollArea.qt_scrollarea_viewport.zWinDialog."
BTNW = "rsWspMainWindow.rsCentralWidget.DialogSplitterChild.rsCentralDialogButtonWidget.rsPushButton"


def test_amount_helpers():
    assert format_amount(Decimal("1234.5")) == "1234,50"
    assert parse_amount_text("1.234,50 €") == Decimal("1234.50")
    assert parse_amount_text("152,–– €") == Decimal("152")
    assert parse_amount_text("0,— €") == Decimal("0")
    assert parse_amount_text("") is None


def test_state_none_start_case_modal(env):
    drv, win, *_, state = env
    assert drv.state() == "case_open"
    win._title = " WISO Steuer 2026"
    assert drv.state() == "start"
    win.box = MessageBox("Frage?", {"Ja": lambda: None})
    assert drv.state() == "modal"
    state["win"] = None
    assert drv.state() == "none"


def test_open_case_launches_and_dismisses_belegabruf(env):
    drv, win, guard, case, launched, state = env
    state["win"] = None
    win._title = "probe - WISO Steuer 2026"

    def launch(p):
        launched.append(p)
        state["win"] = win

    drv._launch = launch
    cancelled = []
    win.add(
        "Button",
        "Abbrechen",
        "rsWspMainWindow.btsBelegabrufAssistent.frame.buttonFrame.rsPushButton",
        on_invoke=lambda: cancelled.append(1),
    )
    drv.open_case(case)
    assert launched == [case] and cancelled == [1] and drv.current_case == case


def test_open_case_refuses_original_file(env, tmp_path):
    drv, *_ = env
    with pytest.raises(Blocked):
        drv.open_case(tmp_path / "Mustermann.steuer2025")


def test_open_case_refuses_when_other_case_open(env):
    drv, win, guard, case, *_ = env
    win._title = "andere - WISO Steuer 2026"
    with pytest.raises(DriverError, match="andere"):
        drv.open_case(case)


def test_goto_section_posts_click_on_tree_item(env):
    drv, win, *_ = env
    win.add("TreeItem", "Arbeitnehmer", rect=(10, 20, 110, 40))
    drv.goto_section("Arbeitnehmer")
    assert win.clicks == [(10, 20, 110, 40)]
    with pytest.raises(DriverError, match="Arbeitnehmer"):
        drv.goto_section("Gibtsnicht")


def test_goto_section_blocks_submission_items(env):
    drv, win, *_ = env
    win.add("TreeItem", "Steuererklärung abgeben")
    with pytest.raises(Blocked):
        drv.goto_section("Steuererklärung abgeben")


def test_open_card_by_nav_path(env):
    drv, win, *_ = env
    win.add("Button", "Kontrolliere", "x.navilistDueTitlegroup.navilistButtonEA[M]\\WK0000")
    drv.open_card("EA[M]\\WK0000")
    assert win.invoked == ["x.navilistDueTitlegroup.navilistButtonEA[M]\\WK0000"]
    with pytest.raises(DriverError, match="EA\\[M\\]\\\\WK0000"):
        drv.open_card("EA[F]\\XX")


def test_list_and_read_fields(env):
    drv, win, *_ = env
    win.add("Edit", "Internet und Telefon", DLG + "wk0_Telefonkosten", "152,–– €", enabled=False)
    win.add("CheckBox", "", DLG + "infoButton_staticText_wk0_Telefonkosten")
    win.add("Edit", "", "searchLine.searchEdit", "x")
    fields = drv.list_fields()
    assert [f["var"] for f in fields] == ["wk0_Telefonkosten"]
    assert fields[0]["amount"] == "152.00" and fields[0]["enabled"] is False
    assert drv.read_field("wk0_Telefonkosten") == "152,–– €"


def test_set_field_writes_verifies_and_backs_up(env):
    drv, win, guard, case, *_ = env
    win.add("Edit", "Beruf", DLG + "aa1_AusgeuebterBeruf", "alt")
    res = drv.set_field("aa1_AusgeuebterBeruf", "neu")
    assert res == {"var": "aa1_AusgeuebterBeruf", "old": "alt", "new": "neu"}
    assert drv.read_field("aa1_AusgeuebterBeruf") == "neu"
    assert len(list(guard.backup_dir.iterdir())) == 1


def test_set_field_rejects_disabled_secret_and_unverified(env):
    drv, win, *_ = env
    win.add("Edit", "Summe", DLG + "wk0_Summe", "1,–– €", enabled=False)
    win.add("Edit", "", "zWinDialog.vastAbrufAssi_Password", "")
    stuck = win.add("Edit", "x", DLG + "aa1_Stuck", "a")
    stuck.set_value = lambda v: None
    with pytest.raises(DriverError, match="read-only"):
        drv.set_field("wk0_Summe", "5")
    with pytest.raises(Blocked):
        drv.set_field("vastAbrufAssi_Password", "geheim")
    with pytest.raises(DriverError, match="verify"):
        drv.set_field("aa1_Stuck", "b")


def test_open_row_invokes_button_in_same_row(env):
    drv, win, *_ = env
    win.add(
        "Edit", "Arbeitsmittel", DLG + "wk0_AbschreibugenArbeitsmittel", "318,–– €", rect=(500, 100, 600, 120)
    )
    win.add("Button", "", DLG + "ID_BTNSUBWIN1", rect=(620, 40, 640, 60))
    win.add("Button", "", DLG + "ID_BTNSUBWIN3", rect=(620, 101, 640, 119))
    drv.open_row("wk0_AbschreibugenArbeitsmittel")
    assert win.invoked == [DLG + "ID_BTNSUBWIN3"]


def test_add_table_rows_and_read_back(env):
    drv, win, *_ = env
    win.table = FakeTable()
    drv.add_table_row("Monitor", Decimal("179.99"))
    drv.add_table_row("Toner", Decimal("20"))
    rows = drv.table_rows()
    assert [(r["description"], r["amount"]) for r in rows] == [("Monitor", "179.99"), ("Toner", "20.00")]


def test_add_table_row_date_goes_into_description_by_default(env):
    drv, win, *_ = env
    win.table = FakeTable()
    drv.add_table_row("Amazon - Toner", Decimal("20"), date="2025-04-10")
    row = drv.table_rows()[0]
    assert row["description"] == "10.04.2025 Amazon - Toner" and row["date"] == ""
    assert win.keys == []  # nothing typed


def test_add_table_row_date_column_when_wiso_in_foreground(env):
    drv, win, *_ = env
    win.table = FakeTable()
    win.foreground = True
    drv.add_table_row("Toner", Decimal("20"), date="2025-04-10", date_column=True)
    assert drv.table_rows()[0]["date"] == "10.04."
    assert "ESCAPE" not in win.keys


def test_add_table_row_date_column_refused_in_background(env):
    drv, win, *_ = env
    win.table = FakeTable()
    win.foreground = False
    with pytest.raises(DriverError, match="foreground"):
        drv.add_table_row("Toner", Decimal("20"), date="2025-04-10", date_column=True)
    assert win.keys == [] and win.table.rows[0][1] == ""


def test_add_table_row_date_not_accepted_raises(env):
    drv, win, *_ = env
    win.table = FakeTable(reject_dates=True)
    win.foreground = True
    with pytest.raises(DriverError, match="verify"):
        drv.add_table_row("Toner", Decimal("20"), date="10.04.2025", date_column=True)


def test_add_table_row_verification_failure(env):
    drv, win, *_ = env
    win.table = FakeTable(reject_values=True)
    with pytest.raises(DriverError, match="verify"):
        drv.add_table_row("Monitor", Decimal("1"))


def test_no_table_raises(env):
    drv, *_ = env
    with pytest.raises(DriverError, match="table"):
        drv.add_table_row("x", Decimal("1"))


def test_cancel_confirms_discard(env):
    drv, win, *_ = env
    answered = []
    win.add(
        "Button",
        "Abbrechen",
        BTNW,
        on_invoke=lambda: setattr(
            win,
            "box",
            MessageBox(
                "Änderungen nicht übernehmen?", {"Ja": lambda: answered.append("Ja"), "Nein": lambda: None}
            ),
        ),
    )
    drv.cancel()
    assert answered == ["Ja"]


def test_ok_with_unexpected_message_box_raises(env):
    drv, win, *_ = env
    win.add(
        "Button",
        "OK",
        BTNW,
        on_invoke=lambda: setattr(win, "box", MessageBox("Plausibilitätsfehler", {"OK": lambda: None})),
    )
    with pytest.raises(DriverError, match="Plausibilitätsfehler"):
        drv.ok()


def test_ok_answers_plausibility_hint_with_nicht_jetzt(env):
    drv, win, *_ = env
    answered = []

    def show_hint():
        win.box = MessageBox(
            "Eingaben überprüfen ... liegen Hinweise vor. Möchtest du die Hinweise ansehen?",
            {
                "Ansehen": lambda: answered.append("Ansehen"),
                "Nicht jetzt": lambda: answered.append("Nicht jetzt"),
            },
        )

    win.add("Button", "OK", BTNW, on_invoke=show_hint)
    win.box = None
    result = drv.ok()
    assert answered == ["Nicht jetzt"]
    assert "Hinweise" in result["hint"]


def test_leave_dialogs_cancels_until_no_dialog(env):
    drv, win, *_ = env
    levels = {"n": 2}

    def pop():
        levels["n"] -= 1
        if levels["n"] == 0:
            win.ctls[:] = [c for c in win.ctls if c.name != "Abbrechen"]

    win.add("Button", "Abbrechen", BTNW, on_invoke=pop)
    assert drv.leave_dialogs() == 2
    assert drv.leave_dialogs() == 0


def test_save_invokes_ribbon_save_only_for_allowed_case(env, tmp_path):
    drv, win, *_ = env
    win.add("Button", "Speichern", "")
    drv.save()
    assert win.invoked == ["Speichern"]
    drv.current_case = tmp_path / "original.steuer2025"
    with pytest.raises(Blocked):
        drv.save()


def test_invoke_of_submission_control_blocked(env):
    drv, win, *_ = env
    win.add("Button", "Was möchtest du tun?", "titlegroup_naechsteSchritte.abgeben_button")
    with pytest.raises(Blocked):
        drv.open_card("abgeben_button")


def test_screenshot_delegates(env, tmp_path):
    drv, *_ = env
    out = tmp_path / "s.png"
    drv.screenshot(out)
    assert out.read_bytes() == b"PNG"


# ---------------------------------------------------------------- real-life (-m wiso)
@pytest.mark.wiso
def test_real_driver_adds_buromaterial_row_and_saves(tmp_path):
    """Real-life: on the fixture COPY, add one Büromaterial row for person [M], commit, save, read back."""
    import os

    from wieso_mcp.paths import WisoPaths
    from wieso_mcp.ui.driver import attach_real, launcher

    work, case = PROBE.parent, PROBE
    assert case.is_file(), f"copy a backup to {PROBE} first"
    drv = WisoDriver(attach_real, launcher(WisoPaths.discover().exe), SafetyGuard(work, tmp_path / "bk"))
    drv.open_case(case)
    drv.leave_dialogs()
    drv.goto_section("Arbeitnehmer")
    drv.open_card(r"EA[M]\WK0000")
    drv.open_row("wk0_AbschreibugenArbeitsmittel")
    before = parse_amount_text(drv.read_field("am1_Arbeitsmaterialien")) or Decimal(0)
    drv.open_row("am1_Arbeitsmaterialien")
    existing = {r["description"] for r in drv.table_rows()}
    label = f"MCP-Realtest {len(existing) + 1}"
    drv.add_table_row(label, Decimal("12.34"), date="2025-04-10")
    assert any(r["description"] == f"10.04.2025 {label}" for r in drv.table_rows())
    drv.ok()  # table -> Arbeitsmittel
    after = parse_amount_text(drv.read_field("am1_Arbeitsmaterialien"))
    assert after is not None and after > before
    drv.ok()  # Arbeitsmittel -> Werbungskosten
    drv.ok()  # Werbungskosten -> Arbeitnehmer page
    m0 = os.path.getmtime(case)
    drv.save()
    assert os.path.getmtime(case) != m0
    drv.open_card(r"EA[M]\WK0000")
    drv.open_row("wk0_AbschreibugenArbeitsmittel")
    assert parse_amount_text(drv.read_field("am1_Arbeitsmaterialien")) == after
    drv.cancel()
    drv.cancel()


# ---- column layouts, clearing, radios, list entries (2025 entry run) --------------------------------
def test_add_table_row_uses_header_layout_without_date_column(env):
    drv, win, *_ = env
    win.table = FakeTable(
        rows=[["", "1,00", "0,00 €", "0,00 €", "0,— €"]],
        headers=["Bezeichnung", "Anzahl", "Betrag", "Summe", "Gerundet"],
    )
    drv.add_table_row("Verband X", Decimal("54.20"), date="2025-12-30")
    assert win.table.rows[0][0] == "30.12.2025 Verband X"
    assert win.table.rows[0][2] == "54,20 €"
    assert drv.table_rows() == [
        {"index": 0, "date": "", "description": "30.12.2025 Verband X", "amount": "54.20"}
    ]


def test_add_table_row_accepts_aufwendungen_as_amount_column(env):
    # Arbeitsmittel > Reparatur und Reinigung: amount column is called "Aufwendungen"
    drv, win, *_ = env
    layout = [
        "Datum",
        "Bezeichnung",
        "Aufwendungen",
        "Anteil \nberufliche \nNutzung",
        "Aufgerundeter \nberuflicher Anteil",
    ]
    win.table = FakeTable(rows=[["", "", "0,00 €", "100,00 %", "0,— €"]], headers=layout)
    drv.add_table_row("iPad Reparatur", Decimal("349"), date="2025-04-23")
    assert win.table.rows[0][1] == "23.04.2025 iPad Reparatur"
    assert drv.table_rows()[0]["amount"] == "349.00"


def test_date_column_refused_when_table_has_none(env):
    drv, win, *_ = env
    win.table = FakeTable(
        rows=[["", "1,00", "0,00 €", "0,00 €", "0,— €"]],
        headers=["Bezeichnung", "Anzahl", "Betrag", "Summe", "Gerundet"],
    )
    win.foreground = True
    with pytest.raises(DriverError, match="no date column"):
        drv.add_table_row("x", Decimal("1"), date="2025-01-01", date_column=True)


def _clear_button(win):
    def on_invoke():
        def yes():
            win.table.rows = [["", "", "0,00 €", "0,— €"]]
            win.box = None

        win.box = MessageBox(
            "Frage Möchtest du wirklich alle Einträge löschen?", {"Ja": yes, "Nein": lambda: None}
        )

    win.add("Button", "Alle Einträge löschen", "x.rsTableWidget.clearButton", on_invoke=on_invoke)


def test_clear_table_confirms_and_returns_removed_rows(env):
    drv, win, *_ = env
    win.table = FakeTable(
        rows=[["", "Software-Abo 2024", "120,00 €", "120,— €"], ["", "", "0,00 €", "0,— €"]]
    )
    _clear_button(win)
    removed = drv.clear_table()
    assert removed == [{"index": 0, "date": "", "description": "Software-Abo 2024", "amount": "120.00"}]
    assert drv.table_rows() == []


def test_clear_table_on_empty_table_does_nothing(env):
    drv, win, *_ = env
    win.table = FakeTable()
    _clear_button(win)
    assert drv.clear_table() == []
    assert win.invoked == []


def test_clear_table_fails_if_rows_remain(env):
    drv, win, *_ = env
    win.table = FakeTable(rows=[["", "a", "1,00 €", "1,— €"]])
    win.add("Button", "Alle Einträge löschen", "x.clear", on_invoke=lambda: None)
    with pytest.raises(DriverError, match="still"):
        drv.clear_table()


def test_set_radio_selects_option(env):
    drv, win, *_ = env
    yes = win.add("RadioButton", "Ja", DLG + "am11a_istComputer")
    win.add("RadioButton", "Nein", DLG + "am11a_istComputer")
    drv.set_radio("am11a_istComputer", "Ja")
    assert yes.is_selected()


def test_set_radio_unknown_option(env):
    drv, win, *_ = env
    win.add("RadioButton", "Ja", DLG + "am11a_istComputer")
    with pytest.raises(DriverError, match="Vielleicht"):
        drv.set_radio("am11a_istComputer", "Vielleicht")


def test_set_field_amount_verifies_numerically(env):
    drv, win, *_ = env
    holder = {}
    c = win.add("Edit", "Kosten", DLG + "am11a_Anschaffungskosten", "0,00 €")
    c.set_value = lambda v: holder.update(v=f"{v} €")
    c.value = lambda: holder.get("v", "0,00 €")
    assert drv.set_field("am11a_Anschaffungskosten", "345,60")["new"] == "345,60"


def test_new_entry_invokes_add_button(env):
    drv, win, *_ = env
    win.add("Button", "Eintrag hinzufügen", "x.ListboxDialogNewDialogButton")
    drv.new_entry()
    assert win.invoked == ["x.ListboxDialogNewDialogButton"]


@pytest.mark.wiso
@pytest.mark.skipif(not PROBE.exists(), reason="no probe working copy")
def test_real_layouts_clear_radio_and_device_entry():
    """Real WISO: Berufsverbände layout, clearing a table, device entry with radios - all cancelled."""
    from wieso_mcp.paths import WisoPaths
    from wieso_mcp.ui.driver import attach_real, launcher

    guard = SafetyGuard(PROBE.parent, PROBE.parent / "backups")
    drv = WisoDriver(attach_real, launcher(WisoPaths.discover().exe), guard)
    drv.open_case(PROBE)
    drv.leave_dialogs()
    drv.goto_section("Arbeitnehmer")
    drv.open_card(r"EA[M]\WK0000")

    drv.open_row("wk0_BeitraegezuBerufsverbaenden")
    assert "Anzahl" in drv._table().headers() and "Datum" not in drv._table().headers()
    drv.add_table_row("MCP-Realtest Verband", Decimal("1.50"), date="2025-12-30")
    assert any(r["description"] == "30.12.2025 MCP-Realtest Verband" for r in drv.table_rows())
    drv.cancel()

    drv.open_row("wk0_AbschreibugenArbeitsmittel")
    drv.open_row("am1_Arbeitsmaterialien")
    drv.add_table_row("MCP-Clear 1", Decimal("1"))
    drv.add_table_row("MCP-Clear 2", Decimal("2"))
    removed = drv.clear_table()
    assert {"MCP-Clear 1", "MCP-Clear 2"} <= {r["description"] for r in removed}
    assert drv.table_rows() == []
    drv.cancel()

    drv.open_row("am1_Arbeitnehmer")
    drv.new_entry()
    drv.set_field("am11a_Bezeichnung", "MCP-Realtest Gerät")
    drv.set_field("am11a_Anschaffungskosten", "345,60")
    drv.set_field(
        "am11a_Anschaffungsdatum", "21.03.2025"
    )  # last: committing it reveals the follow-up questions
    drv.set_radio("am11a_istComputer", "Ja")
    fields = {f["var"]: f for f in drv.list_fields()}
    assert fields["am11a_AfaSTJ"]["amount"] == "345.60"
    drv.leave_dialogs()


def test_set_radio_waits_for_late_questions(env):
    drv, win, *_ = env
    calls = {"n": 0}
    original = win.controls

    def late_controls():
        calls["n"] += 1
        if calls["n"] == 3:  # WISO adds the follow-up questions a moment after a field commit
            win.add("RadioButton", "Ja", DLG + "am11a_istComputer")
        return original()

    win.controls = late_controls
    drv.set_radio("am11a_istComputer", "Ja")
    assert win.selected[DLG + "am11a_istComputer"] == "Ja"


def test_set_radio_matches_wiso_group_ids(env):
    drv, win, *_ = env
    win.add("RadioButton", "Ja", DLG + "am11a_sollSofortAfa.am11a_sollSofortAfa")
    drv.set_radio("am11a_sollSofortAfa", "Ja")
    assert win.selected[DLG + "am11a_sollSofortAfa.am11a_sollSofortAfa"] == "Ja"


def test_dismiss_blockers_confirms_assistant_abort(env):
    drv, win, *_ = env
    aid = "rsWspMainWindow.btsBelegabrufAssistent.frame.buttonFrame.rsPushButton"
    confirmed = []
    pending = {"n": 2}  # WISO may stack the same question several times

    def yes():
        confirmed.append(1)
        pending["n"] -= 1
        win.box = ask_box() if pending["n"] else None

    def ask_box():
        return MessageBox(
            'Assistenten abbrechen? Möchtest du den Assistenten "Steuer-Abruf" wirklich abbrechen?',
            {"Ja": yes, "Nein": lambda: None},
        )

    def cancel():
        win.box = ask_box()

    win.add("Button", "Abbrechen", aid, on_invoke=cancel)
    assert drv.dismiss_blockers() == ["belegabruf_assistent"]
    assert confirmed == [1, 1] and win.box is None


def test_leave_dialogs_also_dismisses_late_assistant(env):
    drv, win, *_ = env
    cancelled = []
    win.add(
        "Button",
        "Abbrechen",
        "rsWspMainWindow.btsBelegabrufAssistent.f.rsPushButton",
        on_invoke=lambda: cancelled.append(1),
    )
    drv.leave_dialogs()
    assert cancelled == [1]


def test_goto_section_switches_to_daten_erfassen_first(env):
    drv, win, *_ = env

    def show_tree(rect):
        if rect == (0, 0, 50, 10) and not any(c.kind == "TreeItem" for c in win.ctls):
            win.add("TreeItem", "Arbeitnehmer", rect=(0, 100, 50, 110))

    win.on_click = show_tree
    win.add("CheckBox", "Daten erfassen", "x.rsNaviThemeButton", rect=(0, 0, 50, 10))
    drv.goto_section("Arbeitnehmer")
    assert win.clicks == [(0, 0, 50, 10), (0, 100, 50, 110)]


def test_add_table_row_refuses_when_table_does_not_append(env):
    """Berufsverbände offers no new empty row; reopening loses data in WISO, so the driver must refuse."""
    drv, win, *_ = env
    layout = ["Bezeichnung", "Anzahl", "Betrag", "Summe", "Gerundet"]
    win.table = FakeTable(rows=[["", "1,00", "0,00 €", "0,00 €", "0,— €"]], headers=layout, auto_append=False)
    drv.add_table_row("Beitrag 0", Decimal("10"))
    with pytest.raises(DriverError, match="does not append"):
        drv.add_table_row("Beitrag 1", Decimal("10"))
    assert [r["description"] for r in drv.table_rows()] == ["Beitrag 0"]


def test_clear_table_reopens_dialog_so_table_appends_again(env):
    """After 'Alle Einträge löschen' WISO stops appending rows until the dialog is confirmed and reopened."""
    drv, win, *_ = env
    win.table = FakeTable(rows=[["", "alt", "5,00 €", "5,— €"], ["", "", "0,00 €", "0,— €"]])
    events = []

    def show():
        events.append("open")
        win.table_visible = True

    def hide():
        events.append("ok")
        win.table_visible = False

    win.add("Edit", "Fachliteratur", DLG + "am1_Fachliteratur", "5,–– €", False, (500, 100, 600, 120))
    win.add("Button", "", DLG + "ID_BTNSUBWIN3", rect=(620, 101, 640, 119), on_invoke=show)
    win.add("Button", "OK", BTNW, on_invoke=hide)
    _clear_button(win)
    drv.open_row("am1_Fachliteratur")
    drv.clear_table()
    assert events == ["open", "ok", "open"]


def test_set_radio_rechecks_selection_after_rerender(env):
    drv, win, *_ = env
    yes = win.add("RadioButton", "Ja", DLG + "am11a_istComputer.am11a_istComputer")
    checks = {"n": 0}

    def slow_selected():
        checks["n"] += 1
        return checks["n"] >= 3  # WISO re-renders the question block before the state is visible

    yes.is_selected = slow_selected
    drv.set_radio("am11a_istComputer", "Ja")
    assert checks["n"] >= 3


def test_clear_table_without_reopen(env):
    drv, win, *_ = env
    win.table = FakeTable(rows=[["", "alt", "5,00 €", "5,— €"], ["", "", "0,00 €", "0,— €"]])
    events = []
    win.add("Edit", "Verband", DLG + "wk0_Verband", "5,–– €", False, (500, 100, 600, 120))
    win.add(
        "Button",
        "",
        DLG + "ID_BTNSUBWIN3",
        rect=(620, 101, 640, 119),
        on_invoke=lambda: events.append("open"),
    )
    win.add("Button", "OK", BTNW, on_invoke=lambda: events.append("ok"))
    _clear_button(win)
    drv.open_row("wk0_Verband")
    drv.clear_table(reopen=False)
    assert events == ["open"]


def test_add_table_row_rewrites_description_after_amount(env):
    """Berufsverbände drops a description written into the placeholder row before the amount commits it."""
    drv, win, *_ = env
    layout = ["Bezeichnung", "Anzahl", "Betrag", "Summe", "Gerundet"]
    win.table = FakeTable(
        rows=[["", "1,00", "0,00 €", "0,00 €", "0,— €"]],
        headers=layout,
        auto_append=False,
        drop_first_description=True,
    )
    drv.add_table_row("IT-Verband 2025", Decimal("123.45"))
    assert win.table.rows[0][0] == "IT-Verband 2025"


def test_ok_raises_when_dialog_stays_open(env):
    drv, win, *_ = env
    win.table = FakeTable(rows=[["", "", "7,00 €", "7,— €"], ["", "", "0,00 €", "0,— €"]])
    win.add("Button", "OK", BTNW)  # WISO refuses (required field empty) - nothing changes
    with pytest.raises(DriverError, match="still open"):
        drv.ok()


def test_is_wiso_table_matches_class_or_automation_id():
    from wieso_mcp.ui.driver import _is_wiso_table

    assert _is_wiso_table("x.zWinDialog.rsTableView", "")
    assert _is_wiso_table("x.zWinDialog.te12_tabellenDaten", "rsTableView")  # phone costs per month
    assert not _is_wiso_table("x.zWinDialog.ki18a_tabdata", "QTableWidget")


def test_set_radio_with_person_suffix_in_group(env):
    drv, win, *_ = env
    gid = "te10a_hatAnschlussGenutzt.Mann.te10a_hatAnschlussGenutzt.Mann"
    win.add("RadioButton", "Ja", DLG + gid)
    win.add("RadioButton", "Nein", DLG + gid)
    win.add("RadioButton", "Ja", DLG + "te10a_hatAnschlussGenutzt.Frau.te10a_hatAnschlussGenutzt.Frau")
    drv.set_radio("te10a_hatAnschlussGenutzt.Mann", "Ja")
    assert win.selected == {DLG + gid: "Ja"}


# ---------------------------------------------------------------- same file name, other folder
def test_open_case_refuses_same_name_window_with_other_path(env, tmp_path):
    drv, win, guard, case, *_ = env
    other = tmp_path / "elsewhere" / case.name
    win.opened = other  # WISO shows "probe - WISO Steuer 2026" but has a different file open
    with pytest.raises(DriverError, match="elsewhere"):
        drv.open_case(case)
    assert drv.current_case is None


def test_open_case_accepts_same_name_window_with_same_path(env):
    drv, win, guard, case, launched, *_ = env
    win.opened = case
    drv.open_case(case)
    assert drv.current_case == case and launched == []


def test_open_case_refuses_unverifiable_window_when_name_is_ambiguous(env, tmp_path):
    drv, win, guard, case, *_ = env
    win.opened = None  # e.g. opened through WISO's own menu: path unknown
    drv._known_cases = lambda: [case, tmp_path / "old" / case.name]
    with pytest.raises(DriverError, match="same file name"):
        drv.open_case(case)


def test_open_case_accepts_unverifiable_window_when_name_is_unique(env, tmp_path):
    drv, win, guard, case, *_ = env
    win.opened = None
    drv._known_cases = lambda: [case, tmp_path / "other.steuer2025"]
    drv.open_case(case)
    assert drv.current_case == case


def test_case_path_from_command_line():
    from wieso_mcp.ui.driver import case_from_cmdline

    cmd = r'"C:\Program Files\WISO\Steuersoftware 2026\wiso2026.exe" "G:\a b\probe.steuer2025"'
    assert case_from_cmdline(cmd) == Path(r"G:\a b\probe.steuer2025")
    assert case_from_cmdline(r"C:\x\wiso2026.exe G:\c\x.steuer2025") == Path(r"G:\c\x.steuer2025")
    assert case_from_cmdline(r'"C:\x\wiso2026.exe"') is None
    assert case_from_cmdline(None) is None
