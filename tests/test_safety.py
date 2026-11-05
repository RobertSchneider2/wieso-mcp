from pathlib import Path

import pytest

from wieso_mcp.safety import Blocked, SafetyGuard


@pytest.fixture
def guard(tmp_path: Path, monkeypatch) -> SafetyGuard:
    monkeypatch.delenv("WIESO_MCP_ALLOW_ORIGINAL", raising=False)
    work = tmp_path / "work"
    work.mkdir()
    return SafetyGuard(workdir=work, backup_dir=tmp_path / "backups")


@pytest.mark.parametrize(
    ("name", "auto_id"),
    [
        ("Drucken  Abgeben", "x.backstagecommand_druckenUndAbgeben"),
        ("Was möchtest du tun?", "titlegroup_naechsteSchritte.abgeben_button"),
        ("Steuererklärung abgeben", ""),
        ("Jetzt versenden", ""),
        ("Daten übermitteln", ""),
        ("ELSTER-Versand starten", ""),
        ("Authentifizieren", ""),
        ("", "elster_send_button"),
        ("Test/Debug-Funktionen", ""),
    ],
)
def test_send_like_controls_blocked(guard, name, auto_id):
    with pytest.raises(Blocked):
        guard.check_invoke(name, auto_id)


@pytest.mark.parametrize(
    ("name", "auto_id"),
    [("Speichern", "x.backstagecommand_fallSpeichern"), ("Weiter", ""), ("Abbrechen", ""), ("OK", "")],
)
def test_harmless_controls_allowed(guard, name, auto_id):
    guard.check_invoke(name, auto_id)


@pytest.mark.parametrize("auto_id", ["zWinDialog.vastAbrufAssi_Password", "pin_edit", "kennwortFeld"])
def test_password_fields_never_written(guard, auto_id):
    with pytest.raises(Blocked):
        guard.check_set("", auto_id)


def test_normal_field_write_allowed(guard):
    guard.check_set("Betrag", "dlg.betrag")


def test_case_under_workdir_allowed(guard):
    guard.check_case(guard.workdir / "copy.steuer2025")


def test_original_case_blocked_by_default(guard, tmp_path):
    with pytest.raises(Blocked, match="WIESO_MCP_ALLOW_ORIGINAL"):
        guard.check_case(tmp_path / "Mustermann.steuer2025")


def test_original_case_allowed_with_env(guard, tmp_path, monkeypatch):
    monkeypatch.setenv("WIESO_MCP_ALLOW_ORIGINAL", "1")
    guard.check_case(tmp_path / "Mustermann.steuer2025")


def test_path_traversal_out_of_workdir_blocked(guard):
    with pytest.raises(Blocked):
        guard.check_case(guard.workdir / ".." / "escape.steuer2025")


def test_backup_created_once_per_case(guard):
    case = guard.workdir / "copy.steuer2025"
    case.write_bytes(b"R&S\x1a data")
    first = guard.ensure_backup(case)
    assert first is not None and first.read_bytes() == b"R&S\x1a data"
    assert guard.ensure_backup(case) is None
    assert len(list(guard.backup_dir.iterdir())) == 1
