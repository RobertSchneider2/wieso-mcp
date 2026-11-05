from wieso_mcp.ui.fake import FakeTable, FakeWindow


def test_fake_table_appends_empty_row_after_amount():
    t = FakeTable()
    ctl = t.as_ctl()
    ctl.set_cell(0, 1, "Toner")
    assert len(ctl.rows()) == 1
    ctl.set_cell(0, 2, "20,00")
    assert ctl.rows() == [["", "Toner", "20,00 €", "0,— €"], ["", "", "0,00 €", "0,— €"]]


def test_fake_table_can_reject_values():
    t = FakeTable(reject_values=True)
    t.as_ctl().set_cell(0, 1, "x")
    assert t.rows[0][1] == ""


def test_fake_window_records_invokes_and_values():
    w = FakeWindow()
    hits = []
    c = w.add("Button", "OK", "id.ok", on_invoke=lambda: hits.append(1))
    e = w.add("Edit", "Feld", "id.e", "a")
    c.invoke()
    e.set_value("b")
    assert w.invoked == ["id.ok"] and hits == [1] and e.value() == "b"
    assert w.controls() == [c, e] and w.tables() == [] and w.message_box() is None
    w.post_click((1, 2, 3, 4))
    assert w.clicks == [(1, 2, 3, 4)]


def test_fake_date_cell_ignores_value_pattern_like_wiso():
    t = FakeTable()
    t.as_ctl().set_cell(0, 0, "10.04.2025")
    assert t.rows[0][0] == ""


def test_fake_date_editor_via_double_click_and_keys():
    w = FakeWindow()
    w.table = FakeTable()
    rect = w.table.as_ctl().cell_rect(0, 0)
    w.post_double_click(rect)
    w.post_text("10042025")
    w.post_key("ENTER")
    assert w.table.rows[0][0] == "10.04."


def test_fake_date_editor_rejecting():
    w = FakeWindow()
    w.table = FakeTable(reject_dates=True)
    w.post_double_click(w.table.as_ctl().cell_rect(0, 0))
    w.post_text("10042025")
    w.post_key("ENTER")
    assert w.table.rows[0][0] == ""


def test_fake_foreground_flag_defaults_false():
    assert FakeWindow().is_foreground() is False
