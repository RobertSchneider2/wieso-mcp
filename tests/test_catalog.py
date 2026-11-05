import sqlite3
from pathlib import Path

import pytest

from wieso_mcp.catalog import FieldCatalog, FieldInfo
from wieso_mcp.paths import WisoPaths

SCHEMA = """CREATE TABLE Feldformate ( Feldnummer TEXT, VZ INTEGER, Steuerart VARCHAR2(60), Drucktext TEXT,
 Beschreibung TEXT, Kontext TEXT, Format TEXT, MZI INTEGER, Vordruck VARCHAR2(255), Vordruckzeile TEXT,
 Pflichtfeld TEXT, Formatkennzeichen TEXT, Formattext TEXT, MaxLength INTEGER, Version VARCHAR2(8))"""
ROWS = [
    ("E0100201", 2025, "EST", "Name", "", "Allg/A", ".{1,25}", 0, "ESt1A", "8", "", "", "", 25, "1"),
    (
        "E0161301",
        2025,
        "EST",
        "Art der Aufwendungen",
        "",
        "And_Aufw/Krankh/Einz",
        ".{1,999}",
        0,
        "AgB",
        "4",
        "",
        "",
        "",
        999,
        "1",
    ),
    (
        "E0161302",
        2025,
        "EST",
        "Aufwendungen Krankheit",
        "Betrag",
        "And_Aufw/Krankh/Einz",
        r"\d+",
        0,
        "AgB",
        "4",
        "",
        "",
        "",
        12,
        "1",
    ),
    ("E0100201", 2024, "EST", "Name (alt)", "", "Allg/A", ".{1,25}", 0, "ESt1A", "8", "", "", "", 25, "1"),
    ("E0200101", 2025, "EST", "Arbeitsmittel", "", "WK/Arbm", r"\d+", 0, "N", "41", "", "", "", 12, "1"),
]


@pytest.fixture
def db(tmp_path: Path) -> Path:
    p = tmp_path / "ericfelder.db3"
    con = sqlite3.connect(p)
    con.execute(SCHEMA)
    con.executemany("INSERT INTO Feldformate VALUES (" + ",".join("?" * 15) + ")", ROWS)
    con.commit()
    con.close()
    return p


def test_describe_returns_field_for_year(db):
    with FieldCatalog(db) as c:
        f = c.describe("E0100201", vz=2025)
    assert isinstance(f, FieldInfo)
    assert (f.field_id, f.label, f.form, f.line, f.context) == ("E0100201", "Name", "ESt1A", "8", "Allg/A")


def test_describe_unknown_is_none(db):
    with FieldCatalog(db) as c:
        assert c.describe("E9999999", vz=2025) is None


def test_search_case_insensitive_and_filtered(db):
    with FieldCatalog(db) as cat:
        hits = cat.search("krankheit", vz=2025)
        assert {h.field_id for h in hits} == {"E0161302"}
        assert {h.field_id for h in cat.search("aufwendungen", vz=2025, form="AgB")} == {
            "E0161301",
            "E0161302",
        }
        assert len(cat.search("a", vz=2025, limit=2)) == 2


def test_forms_lists_distinct_forms(db):
    with FieldCatalog(db) as c:
        assert c.forms(vz=2025) == ["AgB", "ESt1A", "N"]


def test_catalog_is_opened_read_only(db):
    with FieldCatalog(db) as cat:
        with pytest.raises(sqlite3.OperationalError):
            cat._con.execute("DELETE FROM Feldformate")


def test_real_catalog_has_2025_fields():
    with FieldCatalog(WisoPaths.discover().field_catalog) as cat:
        assert cat.describe("E0100201", vz=2025).label == "Name"


def test_close_releases_connection(tmp_path):
    from conftest import make_catalog

    with FieldCatalog(make_catalog(tmp_path / "c.db3")) as cat:
        cat.close()
        with pytest.raises(sqlite3.ProgrammingError):
            cat.describe("E0100201")


def test_catalog_is_a_context_manager(tmp_path):
    from conftest import make_catalog

    with FieldCatalog(make_catalog(tmp_path / "c.db3")) as cat:
        assert cat.describe("E0100201").label == "Name"
    with pytest.raises(sqlite3.ProgrammingError):
        cat.describe("E0100201")
