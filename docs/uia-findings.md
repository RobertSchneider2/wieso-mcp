# UI Automation findings — WISO Steuer 2026 (33.03, build 20263640)

Investigated on 2026-11-01 against a **copy** of the 2025 case (`fixtures/private/probe.steuer2025`).
All actions ran with WISO **in the background**; the user kept working in other windows.

## Result: input fields are reachable → UI tasks are NOT blocked

| Area | Reachable? | How |
|---|---|---|
| Main window | yes | `class_name="rsWspMainWindow"`, title `"<file> - WISO Steuer 2026"` |
| Open a case | yes | `wiso2026.exe <path>` (command-line argument); takes ~45 s |
| Navigation tree (`rsInternNaviTreeView`) | partly | UIA `Invoke`/`Expand` are **ignored** by Qt. A **posted** `WM_LBUTTONDOWN/UP` (`PostMessage` to the main HWND at the item's client coordinates) works with no focus change or cursor movement. |
| Page cards | yes | Buttons with `automation_id` `…navilistButton<PATH>` (e.g. `EA[M]\WK0000`); UIA `Invoke` works |
| Dialog fields | **yes** | `automation_id` ends with `zWinDialog.<variable>`; `<variable>` is WISO's internal name (`aa1_Vorname`, `wk0_Telefonkosten`, `wk0_Summe`, …); values readable via the Value pattern (`'152,–– €'`) |
| Dialog commit | yes | Buttons `OK` / `Abbrechen` in `rsCentralDialogButtonWidget` (Invoke). Changes only apply on OK. |
| Detail tables | yes (to be explored in task 9) | `zWinDialog.ID_BTNSUBWIN<n>` opens a sub-dialog; `rsEuroTableEdit_Button` opens the amount tables |
| Search box | partly | `searchLine.searchEdit` accepts text, but its suggestion popup (`Qt…QWindowPopupSaveBits`) exposes no items. **Not used.** |
| Ribbon buttons (`Formulare`, …) | no visible effect via Invoke | not needed |
| Screenshot | yes | `PrintWindow(hwnd, PW_RENDERFULLCONTENT)` works while the window is covered |

## Dialog paths
`main26.db3.Dialogeinsprung_Steuerbescheid(Steuervariable, Pfad, Titel)` maps tax variables to dialog paths:
- `[M]` = steuerpflichtige Person, `[F]` = Ehepartner
- Arbeitsmittel: `Wk_[M]\Wk0000_\Am0001_`; Berufsverbände: `Wk_[M]\Wk0000_\wk0_BeitraegezuBerufsverbaenden`;
  Fortbildung: `Wk_[M]\Wk0000_\wk0_Fortbildungskosten`; Spenden: `Sa_[M]\Sa0012_`
- The navigation cards use upper-case variants of the same paths (`EA[M]\WK0000` = Werbungskosten [M]).

## Hazards found
- On open, WISO may show the **Belegabruf assistant** (`btsBelegabrufAssistent`) containing the ELSTER
  certificate password field `vastAbrufAssi_Password`. Must be dismissed with *Abbrechen*, **never filled**.
- Some page buttons start **help videos** (`VideoDialog-Popup`); close via the window's `close()`.
- **Global keystrokes (`send_keys`) go to whatever window is in front**: during the spike they reached the
  user's editor. The driver must not use global keyboard input; keyboard input is only allowed after a
  foreground check (and is not needed for the current design).
- Navigation cards include `…abgeben_button` / "Steuererklärung abgeben" → blocked by `SafetyGuard`.

## *Prüfen* (local ERiC check)
Not exercised yet. `Eingaben überprüfen` (ribbon) is WISO's internal plausibility check; the ELSTER request
XML is written by the ELSTER *Prüfen*/*Vorschau* step. Task 9/11 must confirm this does not transmit anything
before automating it. Until then, *Prüfen* stays a manual user step.
