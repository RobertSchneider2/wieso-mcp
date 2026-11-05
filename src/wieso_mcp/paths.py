"""Locate the WISO Steuer installation and its per-user data directory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class WisoNotInstalled(RuntimeError):
    """Raised when no WISO Steuer installation for the requested program year is found."""


def _registry_install_dir(program_year: int) -> Path | None:
    """Look up the install dir from the Windows uninstall registry (None if not found)."""
    try:
        import winreg
    except ImportError:  # pragma: no cover - non-Windows
        return None
    wanted = f"WISO Steuer {program_year}"
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, key in roots:
        try:
            with winreg.OpenKey(hive, key) as root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as sub:
                        try:
                            name = winreg.QueryValueEx(sub, "DisplayName")[0]
                        except OSError:
                            continue
                        if name != wanted:
                            continue
                        try:
                            loc = winreg.QueryValueEx(sub, "InstallLocation")[0]
                        except OSError:
                            loc = ""
                        if loc:
                            return Path(loc)
        except OSError:
            continue
    return None


def _wiso_base() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WISO"


def _default_install_dir(program_year: int) -> Path:
    return _wiso_base() / f"Steuersoftware {program_year}"


def installed_program_years() -> list[int]:
    """Program years with an installed WISO (folder 'Steuersoftware NNNN' containing wisoNNNN.exe)."""
    years = []
    base = _wiso_base()
    if base.is_dir():
        for d in base.glob("Steuersoftware *"):
            year = d.name.rsplit(" ", 1)[-1]
            if year.isdigit() and (d / f"wiso{year}.exe").is_file():
                years.append(int(year))
    return sorted(years)


def default_program_year() -> int:
    """WISO_PROGRAM_YEAR, else the exe in WISO_INSTALL_DIR, else the newest installed WISO, else 2026."""
    env = os.environ.get("WISO_PROGRAM_YEAR")
    if env:
        return int(env)
    env_dir = os.environ.get("WISO_INSTALL_DIR")
    if env_dir:
        found = sorted(int(e.stem[4:]) for e in Path(env_dir).glob("wiso20[0-9][0-9].exe"))
        if found:
            return found[-1]
    years = installed_program_years()
    return years[-1] if years else 2026


@dataclass(frozen=True)
class WisoPaths:
    program_year: int
    install_dir: Path
    appdata_dir: Path

    @property
    def tax_year(self) -> int:
        return self.program_year - 1

    @property
    def exe(self) -> Path:
        return self.install_dir / f"wiso{self.program_year}.exe"

    @property
    def field_catalog(self) -> Path:
        return self.install_dir / "ericfelder.db3"

    @property
    def recent_files(self) -> Path:
        return self.appdata_dir / "btsdatei.xml"

    @classmethod
    def discover(cls, program_year: int | None = None) -> WisoPaths:
        if program_year is None:
            program_year = default_program_year()
        env_dir = os.environ.get("WISO_INSTALL_DIR")
        if env_dir:
            install = Path(env_dir)
        else:
            install = _registry_install_dir(program_year) or _default_install_dir(program_year)
        if not (install / f"wiso{program_year}.exe").is_file():
            raise WisoNotInstalled(f"WISO Steuer {program_year} not found in {install}")
        env_app = os.environ.get("WISO_APPDATA_DIR")
        if env_app:
            appdata = Path(env_app)
        else:
            local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
            appdata = Path(local) / "Buhl" / "WISO Steuer" / str(program_year)
        return cls(program_year=program_year, install_dir=install, appdata_dir=appdata)
