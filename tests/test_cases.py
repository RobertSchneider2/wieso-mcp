from pathlib import Path

import pytest

from wieso_mcp.cases import Case, CaseFileError, load_cases

FIX = Path(__file__).parent / "fixtures" / "btsdatei.xml"


def test_load_all_cases():
    cases = load_cases(FIX)
    assert len(cases) == 2
    c = cases[0]
    assert isinstance(c, Case)
    assert c.path == Path("Q:/Users/Test/Steuer 2026 für 2025/Mustermann.steuer2025")
    assert c.filename == "Mustermann.steuer2025"
    assert c.tax_year == 2025
    assert c.persons == "Max Mustermann und Erika Mustermann"
    assert c.submitted is False
    assert c.kind == "einkommensteuer"
    assert c.last_opened == "So. Feb. 8 20:43:50 2026"


def test_filter_by_tax_year_and_kind():
    cases = load_cases(FIX, tax_year=2025)
    assert [c.filename for c in cases] == ["Mustermann.steuer2025"]
    assert load_cases(FIX, tax_year=2026)[0].kind == "lohnsteuerermaessigung"


def test_imported_files_are_not_cases():
    assert all(not str(c.path).endswith(".steuer2024") for c in load_cases(FIX))


def test_missing_file_returns_empty(tmp_path):
    assert load_cases(tmp_path / "btsdatei.xml") == []


def test_malformed_xml_raises(tmp_path):
    bad = tmp_path / "btsdatei.xml"
    bad.write_text("<btsDateiXml><broken", encoding="utf-8")
    with pytest.raises(CaseFileError):
        load_cases(bad)


def test_to_dict_serialises_path():
    d = load_cases(FIX)[0].to_dict()
    assert d["path"].endswith("Mustermann.steuer2025") and d["tax_year"] == 2025
