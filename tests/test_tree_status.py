"""Status symbols of the navigation tree (red triangle = error, yellow = hint, green = ok ...)."""

from wieso_mcp.ui.driver import classify_status


def test_classify_status_colours_from_real_wiso():
    assert classify_status((193, 68, 14)) == "fehler"
    assert classify_status((255, 222, 50)) == "hinweis"
    assert classify_status((28, 156, 15)) == "ok"
    assert classify_status((38, 131, 196)) == "finanzamt"
    assert classify_status((134, 163, 201)) == "leer"
    assert classify_status((235, 244, 255)) == "leer"


class FakeImage:
    def __init__(self, marks):
        self.marks = marks  # {(x, y): rgb}

    def getpixel(self, xy):
        x, y = xy
        for (mx, my), rgb in self.marks.items():
            if abs(mx - x) <= 3 and abs(my - y) <= 3:
                return rgb
        return (250, 250, 250)


def test_tree_status_reads_symbol_right_of_each_visible_item(env):
    drv, win, *_ = env
    win.tree = (20, 400, 960, 1800)
    win.add("TreeItem", "Arbeitnehmer", "", rect=(63, 591, 1294, 661))
    win.add("TreeItem", "Kosten", "", rect=(220, 1255, 1294, 1309))
    win.add("TreeItem", "Arbeitsmittel", "", rect=(126, 1417, 1294, 1471))
    win.add("TreeItem", " 19.03.2025 ", "", rect=(1033, 531, 1180, 603))  # list cell, ignored
    win.add("TreeItem", "Weit unten", "", rect=(126, 2000, 1294, 2050))  # scrolled out of view
    win.image = FakeImage({(900, 626): (193, 68, 14), (900, 1282): (193, 68, 14), (897, 1444): (28, 156, 15)})
    assert drv.tree_status() == [
        {"label": "Arbeitnehmer", "status": "fehler"},
        {"label": "Kosten", "status": "fehler"},
        {"label": "Arbeitsmittel", "status": "ok"},
    ]
    assert drv.tree_status(only_problems=True) == [
        {"label": "Arbeitnehmer", "status": "fehler"},
        {"label": "Kosten", "status": "fehler"},
    ]


def test_goto_section_collapses_open_sections_to_reach_hidden_ones(env):
    drv, win, *_ = env
    top = win.add("TreeItem", "Arbeitnehmer", "", rect=(63, 591, 1294, 661))
    win.add("TreeItem", "Ausgaben (Werbungskosten)", "", rect=(94, 661, 1294, 715))
    closed = win.add("TreeItem", "Persönliches", "", rect=(63, 483, 1294, 537))
    collapsed = []

    def collapse_top():  # UIA ExpandCollapse - no mouse; hides the subtree
        collapsed.append("Arbeitnehmer")
        win.ctls = [c for c in win.ctls if c.name != "Ausgaben (Werbungskosten)"]
        win.add("TreeItem", "Allgemeine Ausgaben", "", rect=(63, 661, 1294, 715))

    top.collapse = collapse_top
    closed.collapse = lambda: collapsed.append("Persönliches")
    closed.is_expanded = lambda: False
    top.is_expanded = lambda: True
    clicks = []
    win.on_click = clicks.append
    drv.goto_section("Allgemeine Ausgaben")
    assert collapsed == ["Arbeitnehmer"]  # only expanded sections are collapsed
    assert clicks == [(63, 661, 1294, 715)]  # the only click is the section itself


def test_dialog_open_detects_the_dialog_buttons(env):
    drv, win, *_ = env
    assert drv.dialog_open() is False
    win.add(
        "Button",
        "Abbrechen",
        "rsWspMainWindow.rsCentralWidget.DialogSplitterChild.rsCentralDialogButtonWidget.rsPushButton",
    )
    assert drv.dialog_open() is True
