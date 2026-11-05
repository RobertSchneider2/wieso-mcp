# wieso-mcp

> *Wieso selber tippen?* (German for "Why type it yourself?")

**[Deutsche Version → README.de.md](README.de.md)**

wieso-mcp is an unofficial [MCP](https://modelcontextprotocol.io) server that lets an AI agent such as
Claude Code work in the German tax software **WISO Steuer** on Windows. It reads what is already in
the return. It turns reviewed bank bookings into entries and types them into a **working copy**. Then
it shows exactly what changed. **It never submits anything.** *Abgeben* (submitting via ELSTER) is
always done by you, by hand.

Built and verified with **WISO Steuer 2026** (program version 33.03, tax year 2025). The newest
installed WISO version is used automatically; `WISO_PROGRAM_YEAR` pins one.

> **Not affiliated with Buhl Data Service GmbH.** "WISO" and "WISO Steuer" are trademarks of their
> owners and are used here only to say which software this tool works with. This is not tax advice.
> You are responsible for every value in your return: check it before you submit.

## What it does

| Area | Tools |
|------|-------|
| Status & cases | `wiso_status`, `list_cases`, `prepare_working_copy` |
| ELSTER field catalogue | `search_fields`, `describe_field` |
| Read the return | `read_return`, `diff_returns` (from the ELSTER XML WISO writes on *Prüfen*) |
| Bank export (CSV) | `summarize_bank_export`, `enter_proposal`, `verify_entries` |
| UI (working copy only) | `open_case`, `goto_section`, `nav_cards`, `open_card`, `open_row`, `list_fields`, `read_field`, `set_field`, `table_rows`, `add_table_rows`, `ok`, `cancel`, `save_case`, `ui_snapshot`, `screenshot` |

Typical flow: `list_cases` → `prepare_working_copy` → `open_case(copy)` → `summarize_bank_export` →
`enter_proposal` (dry run, confirm, then `dry_run=false`) → `save_case` → you run *Prüfen* in WISO →
`verify_entries`.

## Safety model

- **No submission, ever.** There is no send or submit tool. Every control whose name matches
  abgeben/versenden/senden/übermitteln/authentifizieren/signieren/zertifikat is blocked, with no override.
- **No secrets.** Password, PIN and certificate fields are never written. Your ELSTER login stays yours.
- **Working copies only.** UI writes need a case inside the workdir (`WIESO_MCP_WORKDIR`, default
  `%LOCALAPPDATA%\wieso-mcp\work`). The original case is only touched with `WIESO_MCP_ALLOW_ORIGINAL=1`.
  A backup is made before the first write.
- **Read-only data access.** WISO's databases are opened read-only. Case files (`.steuer20xx`) are
  never read directly; the return is read from the ELSTER XML that WISO itself writes.
- **Background operation.** Only UI Automation patterns and messages posted to WISO's own window are
  used. There are no global keystrokes and no mouse moves, so you can keep working in other windows.
- **Audit log.** Every write is appended to `audit.jsonl` (`WIESO_MCP_AUDIT_DIR`).

## Known limitations

This is a working tool for one household's return, not a finished product. Before you rely on it,
know what it can't do yet:

- **Dropdowns (Qt combo boxes) can't be set.** WISO's combo boxes and combo cells in tables, such as
  *Art der Dienstleistung*, *Gezahlt von* or the person selector, ignore UI Automation and posted
  messages while WISO is in the background. The agent reports these as **human steps**: which page,
  which field, which value. You click them yourself.
- **Only one complete entry recipe.** `mapping.yaml` has a verified UI recipe only for *Werbungskosten →
  Arbeitsmittel*. Other categories need the low-level UI tools (`open_card`, `set_field`,
  `add_table_rows`, …). Once a path works, it can be added to the mapping.
- **Date column needs the foreground.** Dates in WISO's date column (`date_column=True`) only work when
  WISO is the active window. By default, the booking date goes in front of the description instead.
- **The navigation tree is half-reachable.** Qt ignores UIA `Invoke`/`Expand` there. Navigation uses
  posted mouse messages at item coordinates, which depends on the layout.
- **The search box and ribbon buttons are not used.** Their popups expose no UIA items.
- **Message boxes** ("Angaben jetzt prüfen?" and similar) are detected, but they are not yet returned as
  structured questions.
- **Prüfen is manual.** The ELSTER check and preview step stays a user action. wieso-mcp only reads
  the XML afterwards.
- **One WISO version tested.** Every yearly WISO release can change dialog names or the layout. Run the
  real-life tests (`pytest -m wiso`) after each update. See [`docs/jahresablauf.md`](docs/jahresablauf.md).
- **Attaches to an open WISO window by file name.** If a WISO window with a case of the *same file
  name* is already open, the driver reuses it, even when it is a different file in another folder.
  Close other WISO windows before working, and give working copies unique names.
- **Windows only, German UI only.** It needs WISO Steuer as the desktop app, not the web version.
- **Bank export format.** `summarize_bank_export` expects a specific reviewed CSV (see below). Getting
  your bank data into that shape is up to you.

## Bank export format

A semicolon-separated UTF-8 CSV with at least these columns: `ID`, `Datum`, `Empfänger`,
`Verwendungszweck`, `Betrag`, `Kategorie`, `Label`, `Für Abschluss bestätigt`, `Im Jahr <tax year>`.
Only rows with `Im Jahr <year> = 1` and `Für Abschluss bestätigt = 1` are used. Exports for a
different tax year than the open case are refused. `Kategorie` + `Label` are mapped to WISO targets
in `src/wieso_mcp/mapping.yaml`. Example: [`tests/fixtures/tax_2025_final_sample.csv`](tests/fixtures/tax_2025_final_sample.csv).

## For AI agents

Working on this repo or using the server from an agent? Read [AGENTS.md](AGENTS.md). It has the hard
safety rules, the commands, the architecture, how to add an entry recipe, and the recommended tool flow.
`CLAUDE.md` points Claude Code to the same file.

## Install

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
claude mcp add --scope user wieso-mcp -- C:/path/to/wieso-mcp/.venv/Scripts/python.exe -m wieso_mcp
```

Environment overrides: `WISO_PROGRAM_YEAR`, `WISO_INSTALL_DIR`, `WISO_APPDATA_DIR`, `WIESO_MCP_WORKDIR`,
`WIESO_MCP_AUDIT_DIR`.

## Repository layout

| Path | Content | Git |
|------|---------|-----|
| `src/wieso_mcp/` | MCP server, UI driver, mapping | yes |
| `tests/` | unit tests (fake WISO window) and real-life tests (`-m wiso`) | yes |
| `docs/` | annual workflow (`jahresablauf.md`), UI Automation findings, design notes | yes |
| `steuer/<year>/` | your private data per tax year: working copy, receipts, plan, notes, reports | **no** (gitignored) |
| `fixtures/private/` | your test copy `probe.steuer<year>` for the real-life tests | **no** (gitignored) |

New tax year: follow [`docs/jahresablauf.md`](docs/jahresablauf.md). It starts with
`python -m wieso_mcp.yearfolder <year>`.

## Tests

```powershell
.venv\Scripts\pytest                 # unit tests against a fake WISO window
.venv\Scripts\pytest -m wiso         # real-life tests against the installed WISO, see docs/real-life-test.md
```

The real-life tests need your own test copy of a case in `fixtures/private/`. They never touch the
original.

## License

MIT, see [LICENSE](LICENSE).
