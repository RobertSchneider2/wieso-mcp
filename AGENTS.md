# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex, Cursor, …) working **on** this repository, and
for agents **using** the wieso-mcp server to fill in a tax return. Humans: start with
[README.md](README.md).

## Hard rules (never break these)

1. **Never submit.** Do not add any tool, code path or UI action that submits, sends, signs or
   authenticates (ELSTER *Abgeben*). `safety.py` blocks these controls. Do not weaken it, and do not add
   an override.
2. **Never write secrets.** Password, PIN and certificate fields stay untouched, even in tests against
   real WISO.
3. **Working copies only.** UI writes go to cases inside the workdir. Never modify WISO's install
   directory, its `.db3` databases or `btsdatei.xml`. Never modify the user's original case file.
4. **No global input.** No `send_keys`, no global mouse moves. Use UI Automation patterns or messages
   posted to WISO's own window. The user keeps working in other windows while WISO runs in the
   background.
5. **No personal data in git.** Never commit case files (`*.steuer20xx`), `steuer/`,
   `fixtures/private/`, real names, Steuer-IDs, IBANs or real amounts. Test data must be synthetic
   (Max/Erika Mustermann, round amounts).
6. **Don't click on the user's behalf in dialogs you didn't open.** Never cancel or discard dialogs
   the user has open, never tick attestation checkboxes, and don't save the user's case unless asked.

## Setup and commands

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"

.venv\Scripts\pytest                  # unit tests, fake WISO window (fast, run always)
.venv\Scripts\pytest -m wiso          # real-life tests: installed WISO + fixtures/private/probe.steuer<year>
.venv\Scripts\ruff check .            # lint (line length 110)
.venv\Scripts\mypy src                # types
```

## How to work here

- **TDD.** Write the failing test first, against `ui/fake.py` (the fake WISO window). Then implement.
- **Real-life check before handing back.** Any change to the UI driver, server tools or mapping
  recipes must pass `pytest -m wiso` against a real WISO installation. Unit tests alone are not enough,
  because Qt behaves differently from the fake.
- **Keep line endings.** Some files are CRLF and some are LF. Don't convert whole files; diffs should
  only show real changes.
- **Record UI discoveries.** When you find out how a WISO dialog behaves, write it down in
  `docs/uia-findings.md`: automation IDs, what works in the background and what doesn't.

## Architecture

| Module | Role |
|---|---|
| `server.py` | MCP tools (`mcp` SDK `MCPServer`), the context object, tool docstrings = what the agent sees |
| `ui/driver.py` | pywinauto/UIA driver for WISO's Qt window: navigation, fields, tables, list dialogs |
| `ui/fake.py` | In-memory fake WISO window for unit tests |
| `ui/snapshot.py` | Compact UI tree snapshots for the agent |
| `safety.py` | `SafetyGuard`: blocked controls, secret fields, working-copy check |
| `paths.py` | Locates the installed WISO version, AppData and databases (`WISO_*` env overrides) |
| `cases.py` | Lists cases from WISO's recent-files list (read-only) |
| `catalog.py` | ELSTER field catalogue from `ericfelder.db3` (read-only) |
| `elster_xml.py` | Parses the ELSTER request XML that WISO writes on *Prüfen* (reading the return) |
| `bank_export.py` | Loads the reviewed bank-export CSV and aggregates it into proposals |
| `mapping.py` + `mapping.yaml` | Bank category + label → WISO dialog path, ELSTER fields, UI recipe |
| `verify.py` | Compares plan vs. what WISO shows, writes a run report |
| `audit.py` | Append-only JSONL log of every write |
| `yearfolder.py` | Creates the private per-year data folder `steuer/<year>/` |

**WISO facts you will need** (details in `docs/uia-findings.md`):
- Dialog fields have automation IDs ending in `zWinDialog.<variable>`. `<variable>` is WISO's internal
  name, e.g. `wk0_Summe`.
- `[M]` is the taxpayer and `[F]` is the spouse. Example card: `EA[M]\WK0000` (Werbungskosten).
- Changes only apply on **OK**.
- The window title only shows the case **file name**. `open_case` therefore checks the full path
  (`opened_path()`: WISO's command line, else `btsdatei.xml`) before reusing an open window. Keep that check.
- Qt combo boxes **can't** be set in the background. Report them as human steps instead of working
  around them with global input.

## Adding a new entry recipe

1. Explore the dialog on the probe copy with `ui_snapshot`, `nav_cards` and `list_fields`. Write down
   what you find in `docs/uia-findings.md`.
2. Write a unit test with the fake window that replays the recipe.
3. Add the `ui:` recipe to `mapping.yaml` and extend the driver only where needed.
4. Run `pytest -m wiso` against the real WISO and confirm the values read back correctly.

## Using the MCP server (agents filling in a return)

1. Get the overview with `wiso_status` and `list_cases`.
2. Make a copy with `prepare_working_copy`, then `open_case` on **the copy**.
3. Read what is already there: `read_return` / `diff_returns`. This needs a fresh *Prüfen* by the user.
4. Run `summarize_bank_export`, then `enter_proposal` with `dry_run=true`. Show the user the plan and
   get confirmation before calling it with `dry_run=false`.
5. Collect every dropdown or combo field the tools couldn't set into a short **human steps** list:
   page, field, value. Give that list to the user.
6. `save_case` only when the user asks for it. Then the user runs *Prüfen*, and you check the result
   with `verify_entries`.
7. Never offer to submit. Submitting is always the user's job in WISO.
