"""wieso-mcp: MCP server for WISO Steuer (from 2026 / tax year 2025).

Reads the return (ELSTER XML), the field catalogue and a reviewed bank-export CSV, and types entries into a
WORKING COPY of the case through UI Automation. It never submits anything: no tool sends, signs or
transmits to ELSTER, and SafetyGuard blocks every submission-like control.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from .audit import AuditLog
from .bank_export import ExportError, load_export, summarize
from .cases import CaseFileError, load_cases
from .catalog import FieldCatalog
from .elster_xml import NoRequestFound, diff, latest_request, parse_request
from .mapping import Mapping, MappingError
from .paths import WisoNotInstalled, WisoPaths
from .safety import Blocked, SafetyGuard
from .ui.driver import DriverError, WisoDriver, WisoWindow
from .ui.snapshot import filter_inputs, snapshot
from .verify import verify_plan as _verify_plan

T = TypeVar("T")
_EXPECTED = (
    DriverError,
    Blocked,
    ExportError,
    MappingError,
    NoRequestFound,
    CaseFileError,
    WisoNotInstalled,
    FileNotFoundError,
    ValueError,
)
INSTRUCTIONS = """Assists with WISO Steuer (newest installed version; tax year = program year - 1).
NEVER submits: the user files the return manually.
Workflow: list_cases -> prepare_working_copy -> open_case(copy) -> summarize_bank_export ->
enter_proposal (dry_run first, confirm with the user) -> save_case ->
user runs 'Prüfen' in WISO -> verify_entries.
Low-level UI: goto_section / open_card / open_row / list_fields / add_table_rows / ok / cancel.
Ask the user whose expense it is (stpfl = taxpayer, ehepartner = spouse) before entering."""


def _com_runner() -> Callable[[Callable[[], T]], T]:  # pragma: no cover - real COM only
    def init() -> None:
        import comtypes

        comtypes.CoInitialize()

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wiso-ui", initializer=init)

    def run(fn: Callable[[], Any]) -> Any:
        return pool.submit(fn).result()

    return run


@dataclass
class ServerContext:
    paths: WisoPaths
    catalog: FieldCatalog
    mapping: Mapping
    workdir: Path
    audit: AuditLog
    driver: WisoDriver
    ui_runner: Callable[[Callable[[], Any]], Any]
    state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        workdir: Path | None = None,
        audit_dir: Path | None = None,
        attach: Callable[[], WisoWindow | None] | None = None,
        launch: Callable[[Path], None] | None = None,
        sleep: Callable[[float], None] | None = None,
        ui_runner: Callable[[Callable[[], Any]], Any] | None = None,
        program_year: int | None = None,
    ) -> ServerContext:
        paths = WisoPaths.discover(program_year)
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "wieso-mcp"
        workdir = Path(workdir or os.environ.get("WIESO_MCP_WORKDIR") or base / "work")
        workdir.mkdir(parents=True, exist_ok=True)
        audit_dir = Path(audit_dir or os.environ.get("WIESO_MCP_AUDIT_DIR") or base / "audit")
        catalog = FieldCatalog(paths.field_catalog)
        guard = SafetyGuard(workdir, audit_dir / "backups")
        if attach is None or launch is None:  # pragma: no cover - real WISO
            from .ui.driver import attach_real, launcher

            attach, launch = attach or attach_real, launch or launcher(paths.exe)

        def known_cases() -> list[Path]:
            try:
                return [c.path for c in load_cases(paths.recent_files)]
            except CaseFileError:
                return []

        driver = WisoDriver(attach, launch, guard, known_cases=known_cases)
        if sleep:
            driver._sleep = sleep
        return cls(
            paths=paths,
            catalog=catalog,
            mapping=Mapping.load(catalog=catalog, vz=paths.tax_year),
            workdir=workdir,
            audit=AuditLog(audit_dir / "audit.jsonl"),
            driver=driver,
            ui_runner=ui_runner or _com_runner(),
        )


def _tool_errors(fn: Callable[..., T]) -> Callable[..., T]:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except _EXPECTED as exc:
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc

    return wrapper


def build_server(ctx: ServerContext) -> MCPServer:
    mcp = MCPServer("wieso-mcp", version=__version__, instructions=INSTRUCTIONS)
    drv = ctx.driver

    def ui(fn: Callable[[], T]) -> T:
        return ctx.ui_runner(fn)  # type: ignore[no-any-return]

    def tool(f: Callable[..., Any]) -> Callable[..., Any]:
        return mcp.tool()(_tool_errors(f))

    # ------------------------------------------------------------- status / cases
    @tool
    def wiso_status() -> dict[str, Any]:
        """Installation paths, tax year, WISO window state and the case opened through this server."""
        return {
            "version": __version__,
            "install_dir": str(ctx.paths.install_dir),
            "appdata_dir": str(ctx.paths.appdata_dir),
            "program_year": ctx.paths.program_year,
            "tax_year": ctx.paths.tax_year,
            "wiso": ui(drv.state),
            "open_case": str(drv.current_case) if drv.current_case else None,
            "workdir": str(ctx.workdir),
        }

    @tool
    def list_cases(tax_year: int | None = None) -> list[dict[str, Any]]:
        """Cases from WISO's recent-files list (optionally one tax year)."""
        return [c.to_dict() for c in load_cases(ctx.paths.recent_files, tax_year)]

    @tool
    def prepare_working_copy(case_path: str, name: str | None = None) -> dict[str, str]:
        """Copy a case file into the working directory. All UI writes happen on such copies."""
        src = Path(case_path)
        if not src.is_file():
            raise ToolError(f"case file not found: {src}")
        stem = name or f"{src.stem}.mcp-{datetime.now():%Y%m%d-%H%M%S}"
        dest = ctx.workdir.resolve() / f"{stem}{src.suffix}"
        shutil.copy2(src, dest)
        ctx.audit.write("prepare_working_copy", source=str(src), copy=str(dest))
        return {"path": str(dest)}

    # ------------------------------------------------------------- catalogue / return
    @tool
    def search_fields(text: str, form: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        """Search the ELSTER field catalogue (labels/contexts) for the tax year."""
        return [f.to_dict() for f in ctx.catalog.search(text, vz=ctx.paths.tax_year, form=form, limit=limit)]

    @tool
    def describe_field(field_id: str) -> dict[str, Any]:
        """Describe one ELSTER field (e.g. E0204402)."""
        f = ctx.catalog.describe(field_id, vz=ctx.paths.tax_year)
        if f is None:
            raise ToolError(f"unknown field {field_id} for {ctx.paths.tax_year}")
        return f.to_dict()

    def _labelled(values: list[Any]) -> list[dict[str, Any]]:
        out = []
        for v in values:
            d = v.to_dict()
            info = ctx.catalog.describe(v.field_id, vz=ctx.paths.tax_year)
            d["label"] = info.label if info else ""
            d["line"] = info.line if info else ""
            out.append(d)
        return out

    @tool
    def read_return(kind: str = "any", form: str | None = None) -> dict[str, Any]:
        """Read the return from the newest ELSTER request XML WISO wrote ('Prüfen'/'Vorschau')."""
        path = latest_request(ctx.paths.appdata_dir, kind=kind)
        values = [v for v in parse_request(path) if form is None or v.form == form]
        return {
            "file": str(path),
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            "fields": _labelled(values),
        }

    @tool
    def diff_returns(older_file: str, newer_file: str | None = None) -> dict[str, Any]:
        """Compare two ELSTER request XML files (default newer = latest)."""
        newer = Path(newer_file) if newer_file else latest_request(ctx.paths.appdata_dir)
        d = diff(parse_request(Path(older_file)), parse_request(newer))
        return {"added": _labelled(d["added"]), "removed": _labelled(d["removed"]), "changed": d["changed"]}

    # ------------------------------------------------------------- bank export
    def _proposals(csv_path: str, allow_review: bool = False) -> tuple[list[Any], list[Any]]:
        props = summarize(load_export(Path(csv_path), allow_review=allow_review, tax_year=ctx.paths.tax_year))
        unmapped = ctx.mapping.apply(props)
        return props, unmapped

    @tool
    def summarize_bank_export(csv_path: str, allow_review: bool = False) -> dict[str, Any]:
        """Aggregate the reviewed bank-export CSV into proposals with their WISO targets."""
        props, unmapped = _proposals(csv_path, allow_review)
        return {"proposals": [p.to_dict() for p in props], "unmapped": [p.to_dict() for p in unmapped]}

    # ------------------------------------------------------------- UI (working copy only)
    @tool
    def open_case(case_path: str) -> dict[str, Any]:
        """Open a working copy in WISO (launches WISO if needed; dismisses the Belegabruf assistant)."""
        ui(lambda: drv.open_case(Path(case_path)))
        ctx.audit.write("open_case", case=case_path)
        return {"open_case": case_path, "state": ui(drv.state)}

    @tool
    def ui_snapshot(inputs_only: bool = True, max_nodes: int = 3000) -> list[dict[str, Any]]:
        """Accessibility snapshot of the WISO window (for exploring dialogs)."""

        def run() -> list[dict[str, Any]]:
            win = drv._win()
            wrapper = getattr(win, "w", None)
            if wrapper is None:
                return [c.__dict__ | {"value": c.value()} for c in win.controls()][:max_nodes]  # fake
            nodes = snapshot(wrapper, max_nodes=max_nodes)
            return [n.to_dict() for n in (filter_inputs(nodes) if inputs_only else nodes)]

        return [{k: v for k, v in d.items() if not callable(v)} for d in ui(run)]

    @tool
    def goto_section(label: str) -> dict[str, str]:
        """Select a section in the 'Daten erfassen' tree (e.g. 'Arbeitnehmer')."""
        ui(lambda: drv.goto_section(label))
        return {"section": label}

    @tool
    def nav_cards() -> list[dict[str, str]]:
        """Cards on the current page (path + label), e.g. EA[M]\\WK0000 = Werbungskosten taxpayer."""
        return ui(drv.nav_cards)

    @tool
    def open_card(path: str) -> dict[str, str]:
        """Open a page card by its WISO path (from nav_cards)."""
        ui(lambda: drv.open_card(path))
        return {"opened": path}

    @tool
    def open_row(var: str) -> dict[str, str]:
        """Open the detail dialog/table next to a field (by WISO variable name)."""
        ui(lambda: drv.open_row(var))
        return {"opened_row": var}

    @tool
    def list_fields() -> list[dict[str, Any]]:
        """Fields of the open dialog: WISO variable, label, value, amount, enabled."""
        return ui(drv.list_fields)

    @tool
    def read_field(var: str) -> dict[str, Any]:
        """Read one field of the open dialog."""
        return {"var": var, "value": ui(lambda: drv.read_field(var))}

    @tool
    def set_field(var: str, value: str) -> dict[str, Any]:
        """Write one editable field (verified by read-back; audited)."""
        res = ui(lambda: drv.set_field(var, value))
        ctx.audit.write("set_field", case=str(drv.current_case), **res)
        return res

    @tool
    def table_rows() -> list[dict[str, Any]]:
        """Rows of the amount table in the open dialog."""
        return ui(drv.table_rows)

    @tool
    def add_table_rows(rows: list[dict[str, str]], date_column: bool = False) -> dict[str, Any]:
        """Append rows {description, amount, date?} to the open amount table (verified; audited).
        Dates go in front of the description unless date_column=True (needs WISO in the foreground)."""
        written = []
        for r in rows:
            amount = Decimal(str(r["amount"]))
            idx = ui(
                functools.partial(drv.add_table_row, r["description"], amount, r.get("date"), date_column)
            )
            entry = ctx.audit.write("add_table_row", case=str(drv.current_case), row=idx, **r)
            written.append(entry)
        return {"rows_written": len(written), "rows": written}

    @tool
    def clear_table() -> dict[str, Any]:
        """Delete all rows of the open amount table ('Alle Einträge löschen'); returns them (audited).
        Afterwards the dialog is confirmed and reopened, because WISO only appends new rows after that."""
        removed = ui(drv.clear_table)
        ctx.audit.write("clear_table", case=str(drv.current_case), removed=removed)
        return {"removed": removed}

    @tool
    def table_cells() -> dict[str, Any]:
        """Any table of the open dialog as headers + cell texts (months, payers, donations, ...)."""
        return ui(drv.table_cells)

    @tool
    def set_table_cell(row: int, column: str, value: str) -> dict[str, Any]:
        """Write one table cell by row index and column header, verified by read-back (audited).
        Drop-down cells (e.g. 'Gezahlt von') cannot be set in the background and are reported."""
        res = ui(lambda: drv.set_table_cell(row, column, value))
        ctx.audit.write("set_table_cell", case=str(drv.current_case), **res)
        return res

    @tool
    def set_radio(var: str, option: str) -> dict[str, str]:
        """Select a radio option ('Ja'/'Nein'/...) of a group, e.g. 'te10a_hatAnschlussGenutzt.Mann'."""
        res = ui(lambda: drv.set_radio(var, option))
        ctx.audit.write("set_radio", case=str(drv.current_case), **res)
        return res

    @tool
    def set_combo(var: str, option: str) -> dict[str, str]:
        """Pick one entry of a dropdown, e.g. set_combo('aa1_Geschlecht', 'Männlich').

        WISO's Qt combo boxes ignore the UIA Value pattern and report success for
        SelectionItem without committing. This tool expands the list and walks to the
        entry with the arrow keys, then verifies the result by reading the field back.
        `option` is matched case-insensitively; a prefix or substring is accepted as long
        as it is unambiguous (exact match wins over prefix, prefix over substring).
        """
        res = ui(lambda: drv.set_combo(var, option))
        ctx.audit.write("set_combo", case=str(drv.current_case), **res)
        return res

    @tool
    def toggle_checkbox(var: str, checked: bool) -> dict[str, Any]:
        """Set a checkbox of the open dialog to checked/unchecked (idempotent, verified, audited)."""
        res = ui(lambda: drv.toggle_checkbox(var, checked))
        ctx.audit.write("toggle_checkbox", case=str(drv.current_case), **res)
        return res

    @tool
    def new_entry() -> dict[str, str]:
        """Start a new entry in a list dialog (devices, phone connections, childcare, donations ...)."""
        ui(drv.new_entry)
        return {"started": "new entry"}

    @tool
    def tree_status(only_problems: bool = True) -> list[dict[str, str]]:
        """Status symbols of the visible navigation entries: fehler (red triangle), hinweis (yellow),
        ok (green), finanzamt (blue), leer. Expand a section with goto_section first."""
        return ui(lambda: drv.tree_status(only_problems))

    @tool
    def list_entries() -> list[dict[str, Any]]:
        """Numbered list entries visible in the navigation tree (e.g. devices '2) Toshiba ...')."""
        return ui(drv.list_entries)

    @tool
    def open_list_entry(text: str) -> dict[str, str]:
        """Open the list entry whose label contains `text` (case-insensitive, must be unique)."""
        return ui(lambda: drv.open_list_entry(text))

    @tool
    def delete_entry() -> dict[str, bool]:
        """Delete the open list entry. Only WISO's delete question is confirmed; anything else is
        answered 'Nein' and reported (audited)."""
        res = ui(drv.delete_entry)
        ctx.audit.write("delete_entry", case=str(drv.current_case))
        return res

    @tool
    def ok() -> dict[str, Any]:
        """Confirm the open dialog (plausibility hints are acknowledged with 'Nicht jetzt' and returned)."""
        res = ui(drv.ok)
        ctx.audit.write("ok", case=str(drv.current_case), hint=res.get("hint"))
        return res

    @tool
    def cancel() -> dict[str, str]:
        """Cancel the open dialog, discarding its changes."""
        ui(drv.cancel)
        return {"cancelled": "dialog"}

    @tool
    def save_case() -> dict[str, str]:
        """Save the open working copy (Speichern)."""
        ui(drv.save)
        ctx.audit.write("save_case", case=str(drv.current_case))
        return {"saved": str(drv.current_case)}

    @tool
    def screenshot(path: str | None = None) -> dict[str, str]:
        """PNG screenshot of the WISO window (works while it is in the background)."""
        out = Path(path) if path else ctx.workdir / f"wiso-{datetime.now():%Y%m%d-%H%M%S}.png"
        ui(lambda: drv.screenshot(out))
        return {"path": str(out)}

    @tool
    def verify_plan(plan_path: str) -> dict[str, Any]:
        """Read-only check of an applied plan: reopens every target and compares it with the plan,
        reads the Werbungskosten overview and the red status marks, one screenshot per target.
        Writes run-report.json/.md into <workdir>/runs/<timestamp>/. Never confirms or saves."""
        plan_file = Path(plan_path).resolve()
        if not plan_file.is_relative_to(ctx.workdir.resolve()):
            raise ToolError(f"plan must be inside the working directory {ctx.workdir}")
        plan = json.loads(plan_file.read_text("utf-8"))
        if drv.current_case is None:
            raise ToolError("open the case first (open_case)")
        if Path(plan["case"]).resolve() != Path(drv.current_case).resolve():
            raise ToolError(f"plan is for an other case: {plan['case']} (open: {drv.current_case})")
        out = ctx.workdir / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
        rep = ui(lambda: _verify_plan(drv, plan, out))
        return {**rep, "report_md": str(out / "run-report.md"), "report_json": str(out / "run-report.json")}

    # ------------------------------------------------------------- high level
    @tool
    def enter_proposal(
        csv_path: str, category: str, label: str, person: str, dry_run: bool = True, date_column: bool = False
    ) -> dict[str, Any]:
        """Enter one bank-export category into WISO. dry_run=True (default) only returns the plan.
        person: 'stpfl' (taxpayer) or 'ehepartner'. Does not save - call save_case afterwards."""
        props, _ = _proposals(csv_path)
        prop = next((p for p in props if p.category == category and p.label == label), None)
        if prop is None:
            raise ToolError(f"no confirmed bookings for {category}/{label}")
        target = ctx.mapping.target_for(category, label)
        if target is None:
            raise ToolError(f"{category}/{label} has no WISO target in mapping.yaml - enter manually")
        if person not in ("stpfl", "ehepartner"):
            raise ToolError("person must be 'stpfl' (taxpayer) or 'ehepartner' (spouse) - ask the user")
        steps = target.ui_steps(person)
        if steps is None:
            raise ToolError(
                f"no verified UI recipe for {category}/{label} yet - navigate manually "
                f"(search WISO for '{target.dialog_search_term}') and use add_table_rows"
            )
        rows = [
            {"date": b.date, "description": f"{b.payee} – {b.purpose}".strip(" –"), "amount": str(-b.amount)}
            for b in prop.items
        ]
        plan = {
            "dry_run": dry_run,
            "category": category,
            "label": label,
            "person": person,
            "total": str(prop.total),
            "steps": steps,
            "rows": rows,
            "notes": target.notes,
        }
        if dry_run:
            return plan

        def run() -> int:
            drv.leave_dialogs()
            drv.goto_section(steps["section"])
            drv.open_card(steps["card"])
            for var in steps["rows"]:
                drv.open_row(var)
            for r in rows:
                drv.add_table_row(r["description"], Decimal(r["amount"]), r["date"], date_column)
            hints = []
            for _ in range(len(steps["rows"]) + 1):
                hints.append(drv.ok().get("hint"))
            return len(rows)

        n = ui(run)
        ctx.audit.write(
            "enter_proposal",
            case=str(drv.current_case),
            category=category,
            label=label,
            person=person,
            rows=rows,
        )
        return plan | {"dry_run": False, "rows_written": n, "saved": False}

    @tool
    def verify_entries(csv_path: str) -> dict[str, Any]:
        """Compare proposal totals with the newest ELSTER request XML (run 'Prüfen' in WISO first)."""
        props, _ = _proposals(csv_path)
        path = latest_request(ctx.paths.appdata_dir)
        values = parse_request(path)
        checks = []
        for p in props:
            sum_field = (p.target or {}).get("fields", {}).get("sum")
            if not sum_field:
                continue
            found = [Decimal(v.value) for v in values if v.field_id == sum_field and v.value]
            total = sum(found, Decimal(0)) if found else None
            status = "missing" if total is None else ("present" if total >= p.total else "lower")
            checks.append(
                {
                    "category": p.category,
                    "label": p.label,
                    "field": sum_field,
                    "expected": str(p.total),
                    "found": None if total is None else str(total),
                    "status": status,
                }
            )
        return {
            "file": str(path),
            "checks": checks,
            "note": "Sums in WISO include entries from other sources (e.g. previous year, Pauschalen).",
        }

    return mcp


def main() -> None:  # pragma: no cover - entry point
    build_server(ServerContext.create()).run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
