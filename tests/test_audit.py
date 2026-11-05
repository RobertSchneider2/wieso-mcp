import json

from wieso_mcp.audit import AuditLog


def test_audit_log_appends_jsonl(tmp_path):
    log = AuditLog(tmp_path / "audit" / "audit.jsonl")
    log.write("set_field", case="c.steuer2025", field="dlg.betrag", old="", new="12,00")
    log.write("save_case", case="c.steuer2025")
    lines = [json.loads(x) for x in (tmp_path / "audit" / "audit.jsonl").read_text("utf-8").splitlines()]
    assert [entry["tool"] for entry in lines] == ["set_field", "save_case"]
    assert lines[0]["new"] == "12,00" and "ts" in lines[0]


def test_audit_write_returns_entry_and_keeps_unicode(tmp_path):
    entry = AuditLog(tmp_path / "a.jsonl").write("set_field", field="Lohnanteil", new="Ä 1.234,56 €")
    assert entry["new"] == "Ä 1.234,56 €"
    assert "Ä 1.234,56 €" in (tmp_path / "a.jsonl").read_text("utf-8")
