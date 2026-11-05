from pathlib import Path

import pytest

from wieso_mcp.paths import WisoNotInstalled, WisoPaths


@pytest.fixture
def fake_install(tmp_path: Path) -> Path:
    d = tmp_path / "Steuersoftware 2026"
    d.mkdir()
    (d / "wiso2026.exe").write_bytes(b"MZ")
    (d / "ericfelder.db3").write_bytes(b"")
    return d


def test_env_overrides_win(fake_install, tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    monkeypatch.setenv("WISO_INSTALL_DIR", str(fake_install))
    monkeypatch.setenv("WISO_APPDATA_DIR", str(appdata))
    p = WisoPaths.discover(program_year=2026)
    assert p.install_dir == fake_install
    assert p.appdata_dir == appdata
    assert p.tax_year == 2025
    assert p.program_year == 2026
    assert p.exe == fake_install / "wiso2026.exe"
    assert p.field_catalog == fake_install / "ericfelder.db3"
    assert p.recent_files == appdata / "btsdatei.xml"


def test_missing_install_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("WISO_INSTALL_DIR", str(tmp_path / "nope"))
    with pytest.raises(WisoNotInstalled):
        WisoPaths.discover(program_year=2026)


def test_default_appdata_uses_localappdata(fake_install, tmp_path, monkeypatch):
    monkeypatch.setenv("WISO_INSTALL_DIR", str(fake_install))
    monkeypatch.delenv("WISO_APPDATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    p = WisoPaths.discover(program_year=2026)
    assert p.appdata_dir == tmp_path / "Buhl" / "WISO Steuer" / "2026"


def test_registry_lookup_used_when_no_env(fake_install, monkeypatch):
    monkeypatch.delenv("WISO_INSTALL_DIR", raising=False)
    monkeypatch.setattr("wieso_mcp.paths._registry_install_dir", lambda year: fake_install)
    assert WisoPaths.discover(program_year=2026).install_dir == fake_install


def test_real_machine_install_is_found():
    """Real-life check on this machine: WISO Steuer 2026 must be discoverable without overrides."""
    p = WisoPaths.discover(program_year=2026)
    assert p.exe.is_file()
    assert p.field_catalog.is_file()


def _install(base: Path, year: int) -> Path:
    d = base / "WISO" / f"Steuersoftware {year}"
    d.mkdir(parents=True)
    (d / f"wiso{year}.exe").write_bytes(b"MZ")
    return d


def test_newest_installed_year_wins(tmp_path, monkeypatch):
    """Year change: without a year, the newest installed WISO is used (2027 -> tax year 2026)."""
    from wieso_mcp.paths import installed_program_years

    _install(tmp_path, 2026)
    _install(tmp_path, 2027)
    (tmp_path / "WISO" / "Steuersoftware 2028").mkdir()  # leftover folder without exe
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("WISO_INSTALL_DIR", raising=False)
    monkeypatch.delenv("WISO_PROGRAM_YEAR", raising=False)
    monkeypatch.setattr("wieso_mcp.paths._registry_install_dir", lambda year: None)
    assert installed_program_years() == [2026, 2027]
    p = WisoPaths.discover()
    assert (p.program_year, p.tax_year) == (2027, 2026)


def test_program_year_env_pins_the_year(tmp_path, monkeypatch):
    _install(tmp_path, 2026)
    _install(tmp_path, 2027)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("WISO_INSTALL_DIR", raising=False)
    monkeypatch.setenv("WISO_PROGRAM_YEAR", "2026")
    monkeypatch.setattr("wieso_mcp.paths._registry_install_dir", lambda year: None)
    assert WisoPaths.discover().program_year == 2026


def test_no_install_at_all_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("WISO_INSTALL_DIR", raising=False)
    monkeypatch.delenv("WISO_PROGRAM_YEAR", raising=False)
    monkeypatch.setattr("wieso_mcp.paths._registry_install_dir", lambda year: None)
    with pytest.raises(WisoNotInstalled):
        WisoPaths.discover()


def test_install_dir_override_determines_year(tmp_path, monkeypatch):
    d = _install(tmp_path, 2027)
    monkeypatch.setenv("WISO_INSTALL_DIR", str(d))
    monkeypatch.delenv("WISO_PROGRAM_YEAR", raising=False)
    monkeypatch.setenv("WISO_APPDATA_DIR", str(tmp_path))
    assert WisoPaths.discover().tax_year == 2026
