from decimal import Decimal
from pathlib import Path

import pytest

from wieso_mcp.bank_export import ExportError, Proposal, load_export, parse_amount, summarize

FIX = Path(__file__).parent / "fixtures" / "tax_2025_final_sample.csv"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-25.00", "-25.00"),
        ("-199,99", "-199.99"),
        ("-1.234,56", "-1234.56"),
        ("20", "20"),
        ("1,234.50", "1234.50"),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == Decimal(expected)


def test_parse_amount_rejects_garbage():
    with pytest.raises(ExportError):
        parse_amount("abc")


def test_load_keeps_only_confirmed_in_year_rows():
    rows = load_export(FIX)
    assert [r.id for r in rows] == [1, 2, 3, 4, 5, 8]
    assert rows[0].payee == "IT-Verband" and rows[0].label == "Berufsverbände"


def test_summarize_groups_by_category_and_label():
    props = summarize(load_export(FIX))
    by = {(p.category, p.label): p for p in props}
    assert all(isinstance(p, Proposal) for p in props)
    assert by[("Werbungskosten", "Berufsverbände")].total == Decimal("50.00")
    assert by[("Werbungskosten", "Arbeitsmittel")].total == Decimal("179.99")  # refund nets out
    assert by[("Sonderausgaben", "Kinderbetreuung")].total == Decimal("180.00")
    assert by[("Sonderausgaben", "")].total == Decimal("50.00")
    assert len(by[("Werbungskosten", "Berufsverbände")].items) == 2


def test_income_category_keeps_sign(tmp_path):
    f = tmp_path / "tax_2025_final_x.csv"
    lines = FIX.read_text(encoding="utf-8-sig").splitlines()
    f.write_text(
        lines[0] + "\n9;2025-01-31;Arbeitgeber;Gehalt;3000.00;Einkünfte;confirmed;1;manual;;;g;D;1;1\n",
        encoding="utf-8",
    )
    (p,) = summarize(load_export(f))
    assert p.total == Decimal("3000.00")


def test_review_export_refused_unless_allowed(tmp_path):
    f = tmp_path / "tax_2025_review_20260101.csv"
    f.write_bytes(FIX.read_bytes())
    with pytest.raises(ExportError, match="review"):
        load_export(f)
    assert len(load_export(f, allow_review=True)) == 6


def test_missing_columns_raise(tmp_path):
    f = tmp_path / "tax_2025_final_bad.csv"
    f.write_text("ID;Datum\n1;2025-01-01\n", encoding="utf-8")
    with pytest.raises(ExportError, match="Spalten"):
        load_export(f)


def test_proposal_to_dict_uses_strings_for_money():
    d = summarize(load_export(FIX))[0].to_dict()
    assert isinstance(d["total"], str) and isinstance(d["items"][0]["amount"], str)


def _year_csv(tmp_path, year: int) -> Path:
    text = FIX.read_text("utf-8-sig").replace("Im Jahr 2025", f"Im Jahr {year}")
    p = tmp_path / f"tax_{year}_final.csv"
    p.write_text(text, "utf-8-sig")
    return p


def test_load_accepts_any_tax_year_column(tmp_path):
    """Year change: the next export has 'Im Jahr 2026' instead of 'Im Jahr 2025'."""
    rows = load_export(_year_csv(tmp_path, 2026))
    assert rows == load_export(FIX)


def test_load_rejects_export_of_other_tax_year(tmp_path):
    with pytest.raises(ExportError, match="2026.*2025"):
        load_export(_year_csv(tmp_path, 2026), tax_year=2025)
    assert load_export(_year_csv(tmp_path, 2026), tax_year=2026)


def test_load_rejects_export_without_year_column(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text(FIX.read_text("utf-8-sig").replace("Im Jahr 2025", "Jahr"), "utf-8-sig")
    with pytest.raises(ExportError, match="Im Jahr"):
        load_export(p)
