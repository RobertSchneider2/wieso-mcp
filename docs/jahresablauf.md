# Annual workflow (tax return with wieso-mcp)

Generic checklist without personal data. Personal notes for each year live in `steuer/<year>/README.md`, which is gitignored.

## 0. Year change (once, in spring)

1. Install the new WISO version (e.g. *WISO Steuer 2027* for tax year 2026).
   - wieso-mcp picks the **newest installed** version automatically.
   - You can pin a version with `WISO_PROGRAM_YEAR=2026`.
2. Create the year folder: `.venv\Scripts\python -m wieso_mcp.yearfolder 2026`.
3. Read `steuer/<previous year>/README.md` → section **Für nächstes Jahr** (for next year).
4. In WISO, create the new case and carry over last year's data. Copy it into `steuer/<year>/wiso/` as a working copy.
5. Make a test copy for the real-life tests: `fixtures/private/probe.steuer<year>`.
6. Run the real-life tests against the new version: `.venv\Scripts\pytest -m wiso`.
   - If something fails, the UI has changed. Update `docs/uia-findings.md`, the driver and `mapping.yaml` using TDD.

## 1. Collect

- Wage tax certificates, bank tax certificates, health insurance and pension statements. Download them in WISO with your ELSTER login.
- Your reviewed bank export (CSV, format in the README). It must have the column `Im Jahr <year>`.
- Invoices from mail. Save them to `steuer/<year>/belege/`.

## 2. Plan

- `summarize_bank_export` → plan file `steuer/<year>/plan/plan-<year>.json`.
- Note open decisions in `steuer/<year>/notizen/`.

## 3. Enter (working copy only)

- `open_case(working copy)` → enter with the UI tools or the plan.
- Dropdowns (Qt combo boxes) can't be set in the background. You set them by hand.

## 4. Check

- `verify_plan(plan)` → report in `runs/`.
- Run *Prüfen* in WISO.
- Compare the draft PDF with the previous year: big differences, missing items.

## 5. Submit (by you only)

- Save, then submit through ELSTER in WISO. wieso-mcp never submits.
- Fill in the status in `steuer/<year>/README.md`. Write down what to do next year under **Für nächstes Jahr**.

## 6. Tax assessment (Bescheid)

- Use *Bescheid prüfen* in WISO to compare. The deadline for an objection is one month.

## 7. Wrap up the repo

- Tests, ruff, mypy, commit.
- Bump the version (`pyproject.toml`) and tag `steuer<year>`.
