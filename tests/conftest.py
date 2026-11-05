import sqlite3
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"

SCHEMA = """CREATE TABLE Feldformate ( Feldnummer TEXT, VZ INTEGER, Steuerart VARCHAR2(60), Drucktext TEXT,
 Beschreibung TEXT, Kontext TEXT, Format TEXT, MZI INTEGER, Vordruck VARCHAR2(255), Vordruckzeile TEXT,
 Pflichtfeld TEXT, Formatkennzeichen TEXT, Formattext TEXT, MaxLength INTEGER, Version VARCHAR2(8))"""
CATALOG_ROWS = [
    ("E0100001", "Art der Erklärung", "Art_Erkl", "ESt1A", "1"),
    ("E0100201", "Name", "Allg/A", "ESt1A", "8"),
    ("E0100301", "Vorname", "Allg/A", "ESt1A", "9"),
    ("E0161301", "Art der Aufwendungen", "And_Aufw/Krankh/Einz", "AgB", "4"),
    ("E0161302", "Betrag", "And_Aufw/Krankh/Einz", "AgB", "4"),
    ("E0161304", "Summe Krankheitskosten", "And_Aufw/Krankh/Sum", "AgB", "5"),
    ("E0204401", "Art der Arbeitsmittel", "Wk/Arbeitsmittel/Einz", "N", "54"),
    ("E0204402", "Betrag", "Wk/Arbeitsmittel/Einz", "N", "54"),
    ("E0204403", "Summe", "Wk/Arbeitsmittel/Sum", "N", "56"),
    ("E0204001", "Bezeichnung der Verbände", "Wk/Berufsverb/Einz", "N", "53"),
    ("E0204002", "Summe", "Wk/Berufsverb/Sum", "N", "53"),
    ("E0204003", "Betrag", "Wk/Berufsverb/Einz", "N", "53"),
    ("E0204804", "Bezeichnung", "Wk/Fortb/Einz", "N", "60"),
    ("E0204808", "Betrag", "Wk/Fortb/Einz", "N", "60"),
    ("E0204812", "Summe", "Wk/Fortb/Sum", "N", "60"),
    ("E0205405", "Bezeichnung", "Wk/Weitere_Wk/Sonst", "N", "62"),
    ("E0205406", "Betrag", "Wk/Weitere_Wk/Sonst", "N", "62"),
    ("E0204803", "Summe weitere WK", "Wk/Weitere_Wk/Sum", "N", "64"),
    ("E0506105", "Kinderbetreuung Summe", "KBK/Art/Sum", "Kind", "67"),
    ("E0108105", "Spenden Inland", "Zuw/Sp_MB/Foerd_st_beg_Zw_Inl/Sum_Best", "SA", "5"),
    ("E0111217", "Art der Aufwendungen", "St_Erm/Handw_L/Einz", "HA_35a", "6"),
    ("E0170601", "Rechnungsbeträge", "St_Erm/Handw_L/Einz", "HA_35a", "6"),
    ("E0111214", "Lohnanteile", "St_Erm/Handw_L/Einz", "HA_35a", "6"),
    ("E0111215", "Summe Lohnanteile", "St_Erm/Handw_L/Sum", "HA_35a", "9"),
]


def make_catalog(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.execute(SCHEMA)
    con.executemany(
        "INSERT INTO Feldformate VALUES (" + ",".join("?" * 15) + ")",
        [
            (f, 2025, "EST", label, "", ctx, "", 0, form, line, "", "", "", 99, "1")
            for f, label, ctx, form, line in CATALOG_ROWS
        ],
    )
    con.commit()
    con.close()
    return path


@pytest.fixture
def fake_install(tmp_path: Path) -> Path:
    d = tmp_path / "install"
    d.mkdir()
    (d / "wiso2026.exe").write_bytes(b"MZ")
    make_catalog(d / "ericfelder.db3")
    return d


@pytest.fixture
def fake_appdata(tmp_path: Path) -> Path:
    d = tmp_path / "appdata"
    d.mkdir()
    (d / "btsdatei.xml").write_bytes((FIX / "btsdatei.xml").read_bytes())
    (d / "btselsterapi_ElsterErklaerung_ESt_validate_request.xml").write_bytes(
        (FIX / "est_validate_request.xml").read_bytes()
    )
    return d


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Driver against a FakeWindow (shared by the driver test modules)."""
    from wieso_mcp.safety import SafetyGuard
    from wieso_mcp.ui.driver import WisoDriver
    from wieso_mcp.ui.fake import FakeWindow

    monkeypatch.delenv("WIESO_MCP_ALLOW_ORIGINAL", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    case = work / "probe.steuer2025"
    case.write_bytes(b"R&S")
    guard = SafetyGuard(work, tmp_path / "backups")
    win = FakeWindow()
    launched = []
    state = {"win": win}
    drv = WisoDriver(
        attach=lambda: state["win"],
        launch=lambda p: launched.append(p),
        guard=guard,
        sleep=lambda s: None,
        timeout=1.0,
    )
    drv.current_case = case
    return drv, win, guard, case, launched, state
