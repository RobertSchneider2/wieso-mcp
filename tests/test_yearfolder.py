"""Per-tax-year private data folder: same layout every year, never overwrites existing files."""

from wieso_mcp.yearfolder import SUBDIRS, init_year, main


def test_init_year_creates_layout_and_readme(tmp_path):
    year_dir = init_year(tmp_path, 2026)
    assert year_dir == tmp_path / "2026"
    for sub in SUBDIRS:
        assert (year_dir / sub).is_dir()
    readme = (year_dir / "README.md").read_text("utf-8")
    assert "Steuerjahr 2026" in readme and "WISO Steuer 2027" in readme
    assert "../2025/README.md" in readme  # points at last year's hand-over notes
    assert ".steuer2026" in readme


def test_init_year_never_overwrites(tmp_path):
    year_dir = init_year(tmp_path, 2026)
    (year_dir / "README.md").write_text("meine Notizen", "utf-8")
    (year_dir / "belege" / "x.pdf").write_bytes(b"%PDF")
    init_year(tmp_path, 2026)
    assert (year_dir / "README.md").read_text("utf-8") == "meine Notizen"
    assert (year_dir / "belege" / "x.pdf").exists()


def test_cli(tmp_path, capsys):
    assert main(["2027", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "2027" / "wiso").is_dir()
    assert str(tmp_path / "2027") in capsys.readouterr().out
