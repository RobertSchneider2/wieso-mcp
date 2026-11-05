"""Verification report: reopen every plan target read-only and compare it with the plan."""

import json
from decimal import Decimal

import pytest

from wieso_mcp.ui.driver import DriverError
from wieso_mcp.verify import compare_rows, device_name, verify_plan


def test_compare_rows_reports_missing_extra_and_ok():
    want = [{"description": "IT-Verband", "amount": "123.45"}, {"description": "Heise", "amount": "60.00"}]
    assert compare_rows(
        want, [{"description": "Heise", "amount": "60"}, {"description": "IT-Verband", "amount": "123.45"}]
    ) == {
        "status": "ok",
        "missing": [],
        "extra": [],
    }
    res = compare_rows(
        want, [{"description": "IT-Verband", "amount": "123.40"}, {"description": "Neu", "amount": "1"}]
    )
    assert res["status"] == "mismatch"
    assert res["missing"] == [["Heise", "60.00"], ["IT-Verband", "123.45"]]
    assert res["extra"] == [["IT-Verband", "123.40"], ["Neu", "1.00"]]


def test_compare_rows_counts_duplicates():
    want = [{"description": "A", "amount": "1"}] * 2
    assert compare_rows(want, [{"description": "A", "amount": "1"}])["missing"] == [["A", "1.00"]]


def test_device_name_strips_review_prefix_and_date():
    assert device_name("R13 REVIEW Privatanteil? | 21.03.2025 Toshiba MG10 22 TB") == "Toshiba MG10 22 TB"
    assert device_name("18.04.2025 Smarttec") == "Smarttec"
    assert device_name("Plain name") == "Plain name"


class StubDriver:
    """Records navigation; serves canned dialog contents per rows_path end."""

    def __init__(self, tables, entries, overview, problems):
        self.tables, self.entries, self.overview, self.problems = tables, entries, overview, problems
        self.calls = []
        self.where = None
        self.user_dialog = False

    def dialog_open(self):
        return self.user_dialog

    def leave_dialogs(self):
        self.calls.append("leave")
        self.where = None
        return 0

    def goto_section(self, label):
        self.calls.append(("goto", label))

    def open_card(self, path):
        self.calls.append(("card", path))
        self.where = path

    def open_row(self, var):
        self.calls.append(("row", var))
        self.where = var

    def table_rows(self):
        if self.where not in self.tables:
            raise RuntimeError("no table")
        return self.tables[self.where]

    def list_entries(self):
        return [{"index": i + 1, "label": e} for i, e in enumerate(self.entries)]

    def list_fields(self):
        return [{"var": k, "value": v} for k, v in self.overview.get(self.where, {}).items()]

    def screenshot(self, path):
        path.write_bytes(b"png")

    def tree_status(self, only_problems=False):
        return self.problems

    def save(self):  # must never be called
        raise AssertionError("verify must not save")

    def ok(self):  # must never be called
        raise AssertionError("verify must not confirm dialogs")


PLAN = {
    "case": "x.steuer2025",
    "targets": [
        {
            "key": "Person A / Berufsverbände",
            "section": "Arbeitnehmer",
            "card": "EA[M]\\WK0000",
            "rows_path": ["wk0_Beitraege"],
            "kind": "table",
            "rows": [{"description": "IT-Verband", "amount": "123.45"}],
        },
        {
            "key": "Person A / Sonstige",
            "section": "Arbeitnehmer",
            "card": "EA[M]\\WK0000",
            "rows_path": ["wk0_Weitere"],
            "kind": "table",
            "rows": [{"description": "Cursor", "amount": "234.50"}],
        },
        {
            "key": "Person A / Geräte",
            "section": "Arbeitnehmer",
            "card": "EA[M]\\WK0000",
            "rows_path": ["wk0_Arbeitsmittel", "am1_Arbeitnehmer"],
            "kind": "devices",
            "rows": [{"description": "R13 REVIEW x | 21.03.2025 Toshiba MG10", "amount": "345.60"}],
            "dropped": [{"description": "10.08.2025 Fuji LCD", "amount": "12.34"}],
        },
    ],
}


def stub(**kw):
    args = dict(
        tables={"wk0_Beitraege": [{"description": "IT-Verband", "amount": "123.45"}], "wk0_Weitere": []},
        entries=["Toshiba MG10", "Fuji LCD (AliExpress)"],
        overview={
            "EA[M]\\WK0000": {"wk0_Summe": "2.000,–– €", "wk0_Leer": ""},
            "EA[F]\\WK0000": {"wk0_Summe": "1.000,–– €"},
        },
        problems=[{"label": "Kosten", "status": "fehler"}],
    )
    args.update(kw)
    return StubDriver(**args)


def test_verify_plan_writes_report_and_flags_every_problem(tmp_path):
    drv = stub()
    rep = verify_plan(drv, PLAN, tmp_path)
    by_key = {t["key"]: t for t in rep["targets"]}
    assert by_key["Person A / Berufsverbände"]["status"] == "ok"
    assert by_key["Person A / Sonstige"]["status"] == "mismatch"
    assert by_key["Person A / Sonstige"]["missing"] == [["Cursor", "234.50"]]
    dev = by_key["Person A / Geräte"]
    assert dev["status"] == "mismatch"
    assert dev["unexpected_present"] == ["Fuji LCD"]  # deleted by decision, still in WISO
    assert dev["missing"] == []
    assert rep["overview"]["EA[M]\\WK0000"] == {"wk0_Summe": "2.000,–– €"}
    assert rep["tree_errors"] == ["Kosten"]
    assert rep["ok"] is False
    # evidence: one screenshot per target, json + markdown report
    for t in rep["targets"]:
        assert (tmp_path / t["screenshot"]).exists()
    saved = json.loads((tmp_path / "run-report.json").read_text("utf-8"))
    assert saved["ok"] is False
    md = (tmp_path / "run-report.md").read_text("utf-8")
    assert "MISMATCH" in md and "Person A / Sonstige" in md and "Kosten" in md
    # read-only: dialogs left with cancel before every target and at the end
    assert drv.calls.count("leave") >= len(PLAN["targets"]) + 1
    assert drv.calls[-1] == "leave"


def test_verify_plan_all_good(tmp_path):
    drv = stub(
        tables={
            "wk0_Beitraege": [{"description": "IT-Verband", "amount": "123.45"}],
            "wk0_Weitere": [{"description": "Cursor", "amount": "234.5"}],
        },
        entries=["Toshiba MG10"],
        problems=[],
    )
    rep = verify_plan(drv, PLAN, tmp_path)
    assert rep["ok"] is True
    assert "Alles stimmt" in (tmp_path / "run-report.md").read_text("utf-8")


def test_verify_plan_records_navigation_errors_instead_of_crashing(tmp_path):
    drv = stub()

    def broken(var):
        raise RuntimeError(f"row {var} not found")

    drv.open_row = broken
    rep = verify_plan(drv, PLAN, tmp_path)
    assert all(t["status"] == "error" and "not found" in t["error"] for t in rep["targets"])
    assert rep["ok"] is False


def test_amounts_compare_as_decimals():
    assert (
        compare_rows(
            [{"description": "x", "amount": Decimal("5")}], [{"description": "x", "amount": "5,00"}]
        )["status"]
        == "ok"
    )


def test_verify_plan_refuses_when_the_user_has_a_dialog_open(tmp_path):
    drv = stub()
    drv.user_dialog = True
    with pytest.raises(DriverError, match="dialog is open"):
        verify_plan(drv, PLAN, tmp_path)
    assert drv.calls == []  # nothing cancelled - the user's input stays


def test_device_matching_tolerates_renamed_labels():
    from wieso_mcp.verify import _present

    assert _present("Smarttec (Handy/Zubehör?)", ["Smarttec Handy-Zubehör"])
    assert _present("Toshiba MG10 22 TB Festplatte", ["Toshiba MG10 22 TB Festplatte"])
    assert not _present(
        "Fuji LCD (AliExpress)", ["Smarttec Handy-Zubehör", "Apple Thunderbolt-Ethernet-Adapter"]
    )
    assert not _present("Apple Developer", ["Apple Thunderbolt-Ethernet-Adapter"])  # same brand, other item
