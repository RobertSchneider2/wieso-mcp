"""set_combo: Qt dropdowns ignore the Value pattern, so the tool has to expand and walk the list."""

import pytest

from wieso_mcp.ui.driver import DriverError, _match_option

DLG = "rsCentralDialogScrollArea.qt_scrollarea_viewport.zWinDialog."
OPTIONS = ["Bitte auswählen...", "Männlich", "Weiblich", "Divers / Ohne Angabe"]


def test_match_option_prefers_exact_then_prefix_then_substring():
    options = ["Bitte auswählen...", "Männlich", "Weiblich", "Divers / Ohne Angabe"]
    assert _match_option("männlich", options) == "Männlich"
    assert _match_option("weib", options) == "Weiblich"
    assert _match_option("ohne", options) == "Divers / Ohne Angabe"
    assert _match_option("gibtsnicht", options) is None
    assert _match_option("  ", options) is None


def test_set_combo_selects_and_reads_back(env):
    drv, win, *_ = env
    win.add_combo("Geschlecht", DLG + "aa1_Geschlecht", OPTIONS)
    res = drv.set_combo("aa1_Geschlecht", "männlich")  # lower case on purpose
    assert res == {"var": "aa1_Geschlecht", "old": "Bitte auswählen...", "selected": "Männlich"}
    assert win.combos[DLG + "aa1_Geschlecht"].current == "Männlich"


def test_set_combo_raises_when_wiso_ignores_the_pick(env):
    """The Value-pattern behaviour: the pick is swallowed without an error, the read-back catches it."""
    drv, win, *_ = env
    win.add_combo("Geschlecht", DLG + "aa1_Geschlecht", OPTIONS, reject=True)
    with pytest.raises(DriverError, match="verify failed for aa1_Geschlecht"):
        drv.set_combo("aa1_Geschlecht", "Männlich")


def test_set_combo_rejects_unknown_option_and_lists_the_alternatives(env):
    drv, win, *_ = env
    win.add_combo("Geschlecht", DLG + "aa1_Geschlecht", OPTIONS)
    with pytest.raises(DriverError, match="has no option 'unbekannt'"):
        drv.set_combo("aa1_Geschlecht", "unbekannt")
    assert win.combo_picks == []  # nothing was even attempted


def test_set_combo_refuses_a_plain_text_field(env):
    drv, win, *_ = env
    win.add("Edit", "Vorname", DLG + "aa1_Vorname", "")
    with pytest.raises(DriverError, match="is not a dropdown"):
        drv.set_combo("aa1_Vorname", "Max")


def test_set_combo_needs_an_open_case(env):
    drv, win, *_ = env
    win.add_combo("Geschlecht", DLG + "aa1_Geschlecht", OPTIONS)
    drv.current_case = None
    with pytest.raises(DriverError, match="no case opened"):
        drv.set_combo("aa1_Geschlecht", "Männlich")
