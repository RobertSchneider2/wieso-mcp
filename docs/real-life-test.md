# Real-life tests

These tests drive the newest installed WISO Steuer (or `WISO_PROGRAM_YEAR`). They are excluded from the default run (`-m 'not wiso'`).

## Preparation

1. Copy a case into `fixtures/private/probe.steuer<tax year>` (gitignored), e.g. `probe.steuer2025` for WISO Steuer 2026.
   **Never use the original case.**
2. Optional: WISO may already be running with the probe open. The tests open it otherwise (~45 s).
3. WISO can stay in the background. Do not use WISO while the tests run.

## Run

```powershell
.venv\Scripts\pytest -m wiso
```

| Test | Checks |
|------|--------|
| `tests/test_driver.py::test_real_driver_adds_buromaterial_row_and_saves` | driver: navigate to Arbeitsmittel › Büromaterial, add dated row, OK, save, re-read |
| `tests/test_e2e_wiso.py` | `python -m wieso_mcp` over stdio: status, catalogue, return, add row, save, refusal of original case, screenshot, audit log |
| `tests/test_snapshot.py`, `test_paths.py`, `test_catalog.py`, `test_elster_xml.py` | real install, field catalogue and request XML (skipped when absent) |

The tests add rows named `MCP-Realtest n` / `MCP-E2E n` to the probe copy. They accumulate; delete the
probe and copy a fresh one when you like.

## Notes

- `read_return` needs the ESt request XML, which WISO writes on *Prüfen* and removes again later.
- If a WISO message box is open, the tools stop and report its text instead of guessing an answer.
