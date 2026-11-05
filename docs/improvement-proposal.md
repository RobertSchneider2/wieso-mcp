# wieso-mcp: improvement proposal (after the first real 2025 run)

These are lessons from entering one real return through the MCP plus ad-hoc scratch scripts. The examples are anonymised.
Effort: S ≈ under 1 day, M ≈ 1–3 days, L ≈ a week or more.

## Status

| # | Item | Status |
|---|---|---|
| 1 | Scratch building blocks as MCP tools | **done** (0dcc3f9): `list_entries`, `open_list_entry`, `delete_entry`, `new_entry`, `toggle_checkbox`, `set_radio`, `clear_table`, `table_cells`, `set_table_cell` |
| 4 | Verification report | **done**: `verify_plan(plan_path)` reopens every plan target read-only, compares rows (tables) and labels (devices, incl. deleted ones), reads the Werbungskosten overview and the red marks (`tree_status`), one screenshot per target, `run-report.json/.md` in `<workdir>/runs/<timestamp>/`. Refuses while a dialog is open, so the user's input is never discarded. Wiring into `apply_plan` follows with item 2 |
| – | Navigation | `goto_section` collapses expanded sections via UIA ExpandCollapse to reach sections the virtualised tree has scrolled out of view (4c9b674) |
| – | Year change | **done** (v0.2.0): newest installed WISO auto-detected (`WISO_PROGRAM_YEAR`), bank export year column generic and checked against the case, `python -m wieso_mcp.yearfolder <year>`, `docs/jahresablauf.md` |
| 2, 3, 5–8 | | open – next candidates before the 2026 return |

## 1. Promote the scratch-script building blocks to MCP tools (S)

**Problem.**
- Much of the session ran through throw-away scripts that called driver internals: `_win()`, `_table()`, `post_click` on tree items, and raw pywinauto for checkboxes and combo boxes.
- An MCP client can't do any of that, and every script re-implemented navigation.

**Change.** Expose these as tools, each with dry-run, audit and verify:
- `clear_table`
- `set_radio` (groups `g.g` and `g.Mann.g.Mann`)
- `toggle_checkbox` (Toggle pattern)
- `new_entry`
- `open_list_entry(label_regex)` (posted click on the left nav-tree item `"N) …"`)
- `delete_entry` (opens the entry, presses the dialog's delete button, confirms only a "löschen" question)
- `set_table_cell(row, column_name, value)` for per-month grids (phone costs, childcare, donations)

**Gain.** The whole session's work becomes reproducible through MCP alone, with no private-API access.

## 2. Declarative list-dialog recipes plus an idempotent `apply_plan` (M)

**Problem.**
- `mapping.yaml` only describes single-table targets.
- Devices, phone connections, childcare providers, §35a items and donations are *lists of forms*, and the recipe for each was discovered by hand.
- Reruns needed name-matching hacks: skip a device if it is present, and strip REVIEW prefixes.

**Change.**
- Add recipe kinds `table`, `list_of_forms` and `month_grid` to `mapping.yaml`. Each recipe holds:
  - the field order (for example the date last, since it reveals the follow-up questions)
  - radio answers
  - a key field for identity (`Bezeichnung`)
  - which values to verify
- A single `apply_plan(plan, mode=dry_run|apply)` then computes the diff per target (add, update, delete, unchanged) against what WISO currently shows. It writes only the diff, saves, and reads everything back.

**Gain.** Reruns after user decisions become safe and fast: only changed entries are touched, and there is no clear-and-rebuild.

## 3. Human-step queue for Qt combo boxes (S), optional consented foreground mode (M)

**Problem.**
- Qt combo boxes and combo-editor cells cannot be set in the background:
  - UIA Value is ignored.
  - SelectionItem.Select and Invoke don't commit.
  - LegacyIAccessible DoDefaultAction does nothing.
- This blocked new childcare providers ("Art der Dienstleistung", "Gezahlt von"), new §35a entries ("Welcher Beleg liegt vor?") and the phone connection type.

**Change.**
- (a) When a recipe hits a combo it can't set, record a *human step*: the target path, the field label and the value to pick. Continue with everything else, and keep the entry if WISO allows.
- (b) Generate one consolidated checklist, `human-steps.md`, plus a sheet in the review xlsx, ordered by navigation path. That means "6 clicks in 3 dialogs", not scattered notes.
- (c) Optional later: a per-run `foreground_consent` mode. It brings WISO to the front, posts focus and arrow/enter keys only to WISO's HWND, then restores the user's window. Off by default because of the "no global input" rule.

**Gain.** Combos stop being blockers. The user does a short, batched click list instead of re-entering whole items.

## 4. Built-in verification report after every apply (S)

**Problem.**
- Read-back, sums and overview values were assembled ad hoc in `run_plan.py`.
- Some failures were only caught by screenshots, for example:
  - an inline editor reverting a description
  - OK not being accepted
  - a table that did not append rows

**Change.** `apply_plan` always:
1. saves
2. reopens each target and compares it row by row with the plan
3. reads key overview totals (Werbungskosten per person, Sonderausgaben, Kinderbetreuung "anzusetzen")
4. takes a screenshot per target into the private run folder
5. writes `run-report.json` plus a short markdown summary

A mismatch fails the run loudly.

**Gain.** A trustworthy "done" signal, with evidence to hand to the user.

## 5. Robustness catalogue as first-class driver behaviour (S–M)

**Problem.** Each of these WISO quirks cost a debugging round:
- the Steuer-Abruf assistant asks the same question several times
- the "Daten erfassen" start page
- after "Alle Einträge löschen", no more rows are appended until the dialog is reopened
- the Berufsverbände table drops the first description
- OK silently refused
- plausibility boxes such as "Angaben jetzt prüfen?" (Prüfen / Nicht jetzt)
- grids found only by class `rsTableView`

Some fixes are in place; the rest exist only in scripts.

**Change.**
- Keep all of them in the driver, each with a fake-based regression test (most already are).
- Add a structured `WisoAsks` result for message boxes, so that a client can choose "Nicht jetzt" and log it.
- Add a `docs/uia-findings.md` table, one row per quirk with symptom and fix.

**Gain.** Fewer surprises on the next year or the next form.

## 6. Decision workflow as a tool: review xlsx → plan → apply (M)

**Problem.**
- The review loop worked well with the user: REVIEW-tagged rows, an xlsx with drop-downs, group decisions and an "Ergebnis" formula.
- But it lives in three scratch scripts with hard-coded paths and hard-coded removed-row lists.

**Change.** Move it into the package:
- `make_review(plan)` builds an xlsx that keeps existing decisions and always shows the original values.
- `apply_decisions(xlsx)` turns the decisions into a new plan.
- Support decisions for list entries too (devices: rename / delete / percentage share via `am11a_Anteilberuflichgenutzt`).
- The V and T sections (removed prior-year values, open items) come from the run reports, not from code.

**Gain.** One round-trip ("Review fertig") updates WISO with no manual edits, devices included.

## 7. Speed (M)

**Problem.**
- Every target takes about 30–60 s: full navigation from the section root, fixed sleeps of 0.5–2.5 s, and repeated `controls()` walks over the whole window.
- A full run takes about 10 minutes.

**Change.**
- Replace fixed sleeps with condition polling: wait until the field or table appears, or until the message box disappears.
- Cache the dialog subtree per step.
- Navigate relatively (stay inside a card for sibling rows).
- Run verification without leaving and re-entering sections where possible.

**Gain.** Likely 3–5× faster runs, which makes iterative review rounds cheap.

## 8. Prior-year and source-data awareness (M)

**Problem.**
- The main risk wasn't automation; it was content.
- Carried-over prior-year rows looked like current data:
  - Kita months that were actually free
  - membership fees at the old rate
  - a December top-up inflating the phone 3-month flat rate
- These were caught only through manual cross-checks with the bank export and the user's memory.

**Change.** A `prior_year_check` step that flags every WISO value which:
1. equals last year's value exactly, or
2. has no matching transaction in the bank export.

It also flags WISO calculation choices that extrapolate (for example "Pauschal für Okt–Dez") when the source shows irregular payments.

**Gain.** The REVIEW list targets real doubts, and wrong carry-overs no longer slip through.

---

**Suggested order:** 1 → 4 → 3a/b → 2 → 6 → 5 → 7 → 8.
Items 1 and 4 alone remove most of the ad-hoc scripting. Item 3 removes the remaining dead ends.
