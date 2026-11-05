import json
from pathlib import Path

import anyio
import pytest
from mcp import Client

from wieso_mcp.server import ServerContext, build_server
from wieso_mcp.ui.fake import FakeTable, FakeWindow

FIX = Path(__file__).parent / "fixtures"
DLG = "rsCentralDialogScrollArea.qt_scrollarea_viewport.zWinDialog."
BTNW = "rsWspMainWindow.rsCentralWidget.DialogSplitterChild.rsCentralDialogButtonWidget.rsPushButton"


def wiso_with_arbeitsmittel() -> FakeWindow:
    """Fake WISO exposing everything the Arbeitsmittel recipe needs at once."""
    w = FakeWindow("probe - WISO Steuer 2026")
    w.add("TreeItem", "Arbeitnehmer", rect=(0, 0, 100, 20))
    w.add("Button", "Ausgaben", "x.navilistButtonEA[M]\\WK0000")
    w.add(
        "Edit",
        "Arbeitsmittel",
        DLG + "wk0_AbschreibugenArbeitsmittel",
        "318,–– €",
        False,
        (500, 100, 600, 120),
    )
    w.add("Button", "", DLG + "ID_BTNSUBWIN3", rect=(620, 101, 640, 119))
    w.add("Edit", "Büromaterial", DLG + "am1_Arbeitsmaterialien", "0,–– €", False, (500, 200, 600, 220))
    w.add(
        "Button",
        "",
        DLG + "rsEuroTableEdit_Button",
        rect=(620, 201, 640, 219),
        on_invoke=lambda: setattr(w, "table_visible", True),
    )
    w.add("Edit", "Beruf", DLG + "aa1_AusgeuebterBeruf", "IT")
    w.add(
        "Button", "OK", BTNW, on_invoke=lambda: setattr(w, "table_visible", False)
    )  # like WISO: OK closes the table
    w.add("Button", "Speichern", "")
    w.table = FakeTable()
    return w


@pytest.fixture
def ctx(tmp_path, fake_install, fake_appdata, monkeypatch):
    monkeypatch.setenv("WISO_INSTALL_DIR", str(fake_install))
    monkeypatch.setenv("WISO_APPDATA_DIR", str(fake_appdata))
    monkeypatch.delenv("WIESO_MCP_ALLOW_ORIGINAL", raising=False)
    work = tmp_path / "work"
    state = {"win": wiso_with_arbeitsmittel()}
    c = ServerContext.create(
        workdir=work,
        audit_dir=tmp_path / "audit",
        attach=lambda: state["win"],
        launch=lambda p: None,
        sleep=lambda s: None,
        ui_runner=lambda fn: fn(),
    )
    c.state = state
    yield c
    c.catalog.close()


def call(server, name, args=None):
    async def go():
        async with Client(server) as c:
            r = await c.call_tool(name, args or {})
            if r.is_error:
                return True, r.content[0].text if r.content else ""
            sc = r.structured_content
            if isinstance(sc, dict) and set(sc) == {"result"}:
                return False, sc["result"]
            return False, sc if sc is not None else json.loads(r.content[0].text)

    return anyio.run(go)


def tools(server):
    async def go():
        async with Client(server) as c:
            return [t.name for t in (await c.list_tools()).tools]

    return anyio.run(go)


def test_tool_inventory_has_no_submission_tool(ctx):
    names = tools(build_server(ctx))
    for expected in (
        "wiso_status",
        "list_cases",
        "prepare_working_copy",
        "search_fields",
        "describe_field",
        "read_return",
        "summarize_bank_export",
        "open_case",
        "goto_section",
        "open_card",
        "open_row",
        "list_fields",
        "read_field",
        "set_field",
        "add_table_rows",
        "ok",
        "cancel",
        "save_case",
        "enter_proposal",
        "verify_entries",
        "ui_snapshot",
        "screenshot",
    ):
        assert expected in names, expected
    assert not [n for n in names if any(k in n for k in ("send", "submit", "abgeb", "elster_"))]


def test_status_and_cases(ctx):
    s = build_server(ctx)
    err, st = call(s, "wiso_status")
    assert not err and st["tax_year"] == 2025 and st["wiso"] == "case_open"
    err, cases = call(s, "list_cases", {"tax_year": 2025})
    assert [c["filename"] for c in cases] == ["Mustermann.steuer2025"]


def test_field_catalog_tools(ctx):
    s = build_server(ctx)
    err, hits = call(s, "search_fields", {"text": "arbeitsmittel"})
    assert not err and "E0204401" in [h["field_id"] for h in hits]
    err, f = call(s, "describe_field", {"field_id": "E0100201"})
    assert f["label"] == "Name"
    err, msg = call(s, "describe_field", {"field_id": "E9999999"})
    assert err and "E9999999" in msg


def test_read_return_labels_fields_and_filters_form(ctx):
    err, ret = call(build_server(ctx), "read_return", {"form": "AgB"})
    assert not err and ret["file"].endswith("_request.xml")
    labelled = {(f["field_id"], f["value"]): f["label"] for f in ret["fields"]}
    assert labelled[("E0161302", "350")] == "Betrag"
    assert all(f["form"] == "AgB" for f in ret["fields"])


def test_summarize_bank_export(ctx):
    err, res = call(
        build_server(ctx), "summarize_bank_export", {"csv_path": str(FIX / "tax_2025_final_sample.csv")}
    )
    assert not err
    by = {(p["category"], p["label"]): p for p in res["proposals"]}
    assert by[("Werbungskosten", "Arbeitsmittel")]["total"] == "179.99"
    assert by[("Werbungskosten", "Arbeitsmittel")]["target"]["form"] == "N"
    assert {"category": "Sonderausgaben", "label": ""} in [
        {"category": u["category"], "label": u["label"]} for u in res["unmapped"]
    ]


def test_prepare_working_copy_never_touches_original(ctx, tmp_path):
    orig = tmp_path / "Mustermann.steuer2025"
    orig.write_bytes(b"R&S\x1aoriginal")
    err, res = call(build_server(ctx), "prepare_working_copy", {"case_path": str(orig)})
    copy = Path(res["path"])
    assert not err and copy.parent == ctx.workdir.resolve() and copy.read_bytes() == b"R&S\x1aoriginal"
    assert orig.read_bytes() == b"R&S\x1aoriginal"


def test_open_case_on_original_is_refused(ctx, tmp_path):
    err, msg = call(build_server(ctx), "open_case", {"case_path": str(tmp_path / "Mustermann.steuer2025")})
    assert err and "WIESO_MCP_ALLOW_ORIGINAL" in msg


def _open_copy(ctx, s, tmp_path):
    orig = tmp_path / "probe.steuer2025"
    orig.write_bytes(b"R&S\x1a")
    _, res = call(s, "prepare_working_copy", {"case_path": str(orig), "name": "probe"})
    ctx.state["win"]._title = f"{Path(res['path']).stem} - WISO Steuer 2026"
    err, _ = call(s, "open_case", {"case_path": res["path"]})
    assert not err
    return Path(res["path"])


def test_set_field_writes_and_audits(ctx, tmp_path):
    s = build_server(ctx)
    _open_copy(ctx, s, tmp_path)
    err, res = call(s, "set_field", {"var": "aa1_AusgeuebterBeruf", "value": "IT Consultant"})
    assert not err and res["new"] == "IT Consultant"
    log = (ctx.audit.path).read_text("utf-8").splitlines()
    assert json.loads(log[-1])["tool"] == "set_field"


def test_ui_errors_are_reported_readably(ctx, tmp_path):
    s = build_server(ctx)
    _open_copy(ctx, s, tmp_path)
    err, msg = call(s, "set_field", {"var": "gibtsnicht", "value": "x"})
    assert err and "gibtsnicht" in msg


def test_enter_proposal_dry_run_then_real(ctx, tmp_path):
    s = build_server(ctx)
    _open_copy(ctx, s, tmp_path)
    args = {
        "csv_path": str(FIX / "tax_2025_final_sample.csv"),
        "category": "Werbungskosten",
        "label": "Arbeitsmittel",
        "person": "stpfl",
    }
    err, plan = call(s, "enter_proposal", args)
    assert not err and plan["dry_run"] is True
    assert plan["rows"] == [
        {"date": "2025-04-10", "description": "Amazon – Monitor", "amount": "199.99"},
        {"date": "2025-04-20", "description": "Amazon – Erstattung Monitor", "amount": "-20.00"},
    ]
    assert plan["steps"]["card"] == "EA[M]\\WK0000"
    assert ctx.state["win"].table.rows[0][1] == ""  # nothing written in dry run
    err, done = call(s, "enter_proposal", {**args, "dry_run": False})
    assert not err, done
    written = [r[1] for r in ctx.state["win"].table.rows if r[1]]
    assert len(written) == 2 and written[0].startswith("10.04.2025 Amazon")
    assert done["rows_written"] == 2


def test_enter_proposal_requires_person(ctx, tmp_path):
    s = build_server(ctx)
    _open_copy(ctx, s, tmp_path)
    err, msg = call(
        s,
        "enter_proposal",
        {
            "csv_path": str(FIX / "tax_2025_final_sample.csv"),
            "category": "Werbungskosten",
            "label": "Arbeitsmittel",
            "person": "ask",
            "dry_run": False,
        },
    )
    assert err and "stpfl" in msg


def test_verify_entries_reports_xml_values(ctx):
    err, res = call(build_server(ctx), "verify_entries", {"csv_path": str(FIX / "tax_2025_final_sample.csv")})
    assert not err
    am = next(r for r in res["checks"] if r["label"] == "Arbeitsmittel")
    assert am["expected"] == "179.99" and am["status"] in ("missing", "present", "lower")


def test_list_and_table_tools_are_exposed(ctx):
    names = tools(build_server(ctx))
    for expected in (
        "clear_table",
        "set_radio",
        "toggle_checkbox",
        "new_entry",
        "list_entries",
        "open_list_entry",
        "delete_entry",
        "table_cells",
        "set_table_cell",
    ):
        assert expected in names, expected


def test_table_cells_and_set_table_cell_are_audited(ctx, tmp_path):
    from wieso_mcp.ui.fake import FakeTable

    srv = build_server(ctx)
    _open_copy(ctx, srv, tmp_path)
    win = ctx.state["win"]
    win.table = FakeTable(
        rows=[["Januar", "15,00 €", "3,00 €"]], headers=["Monat", "Rechnungsbetrag", "Pauschale"]
    )
    err, cells = call(srv, "table_cells")
    assert not err and cells == {
        "headers": ["Monat", "Rechnungsbetrag", "Pauschale"],
        "rows": [["Januar", "15,00 €", "3,00 €"]],
    }
    err, res = call(srv, "set_table_cell", {"row": 0, "column": "Rechnungsbetrag", "value": "30,00"})
    assert not err and res["new"] == "30,00 €"
    log = (tmp_path / "audit" / "audit.jsonl").read_text("utf-8")
    assert '"set_table_cell"' in log


def test_toggle_checkbox_and_list_entry_tools(ctx, tmp_path):
    srv = build_server(ctx)
    _open_copy(ctx, srv, tmp_path)
    win = ctx.state["win"]
    dlg = "rsCentralDialogScrollArea.qt_scrollarea_viewport.zWinDialog."
    win.add("CheckBox", "Privat", dlg + "te10a_Nutzung_Privat.Mann")
    win.add("TreeItem", "1) Toshiba Festplatte", "", rect=(40, 500, 380, 530))
    err, res = call(srv, "toggle_checkbox", {"var": "te10a_Nutzung_Privat.Mann", "checked": True})
    assert not err and res["checked"] is True
    err, entries = call(srv, "list_entries")
    assert not err and entries == [{"index": 1, "label": "Toshiba Festplatte"}]
    err, res = call(srv, "open_list_entry", {"text": "toshiba"})
    assert not err and res == {"opened": "1) Toshiba Festplatte"}
    err, msg = call(srv, "delete_entry")
    assert err and "delete button" in msg  # no list entry dialog open in the fake


def _plan(case, targets=None):
    return {"case": str(case), "targets": targets or [], "overview_cards": []}


def test_verify_plan_tool_writes_private_report(ctx, tmp_path):
    s = build_server(ctx)
    case = _open_copy(ctx, s, tmp_path)
    target = {
        "key": "T",
        "section": "Arbeitnehmer",
        "card": "EA[M]\WK0000",
        "rows_path": ["nope"],
        "kind": "table",
        "rows": [],
    }
    plan = ctx.workdir / "plan.json"
    plan.write_text(json.dumps(_plan(case, [target])), "utf-8")
    err, res = call(s, "verify_plan", {"plan_path": str(plan)})
    assert not err, res
    assert res["ok"] is False and res["targets"][0]["status"] == "error"
    report = Path(res["report_md"])
    assert report.exists() and report.is_relative_to(ctx.workdir.resolve() / "runs")
    assert not ctx.state["win"].saved if hasattr(ctx.state["win"], "saved") else True


def test_verify_plan_tool_refuses_plan_outside_workdir(ctx, tmp_path):
    s = build_server(ctx)
    case = _open_copy(ctx, s, tmp_path)
    plan = tmp_path / "elsewhere.json"
    plan.write_text(json.dumps(_plan(case)), "utf-8")
    err, msg = call(s, "verify_plan", {"plan_path": str(plan)})
    assert err and "working directory" in msg


def test_verify_plan_tool_refuses_plan_for_other_case(ctx, tmp_path):
    s = build_server(ctx)
    _open_copy(ctx, s, tmp_path)
    plan = ctx.workdir / "plan.json"
    plan.write_text(json.dumps(_plan(ctx.workdir / "other.steuer2025")), "utf-8")
    err, msg = call(s, "verify_plan", {"plan_path": str(plan)})
    assert err and "other case" in msg


def test_verify_plan_tool_explains_refusal_when_a_dialog_is_open(ctx, tmp_path):
    s = build_server(ctx)
    case = _open_copy(ctx, s, tmp_path)
    plan = ctx.workdir / "plan.json"
    plan.write_text(json.dumps(_plan(case)), "utf-8")
    ctx.state["win"].add("Button", "Abbrechen", BTNW)
    err, msg = call(s, "verify_plan", {"plan_path": str(plan)})
    assert err and "dialog is open" in msg


def test_summarize_bank_export_refuses_other_tax_year(ctx, tmp_path):
    """The fake install is WISO 2026 (tax year 2025): a 2026 export must not be entered into it."""
    src = (FIX / "tax_2025_final_sample.csv").read_text("utf-8-sig").replace("Im Jahr 2025", "Im Jahr 2026")
    p = tmp_path / "tax_2026_final.csv"
    p.write_text(src, "utf-8-sig")
    err, msg = call(build_server(ctx), "summarize_bank_export", {"csv_path": str(p)})
    assert err and "2026" in msg and "2025" in msg
