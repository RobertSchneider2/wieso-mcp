"""Real-life end-to-end test: the MCP server as a real stdio process against the installed WISO.

Run with:  pytest -m wiso tests/test_e2e_wiso.py
Needs the installed WISO Steuer and fixtures/private/probe.steuer<tax year>
(a working copy - never the original).
WISO may stay in the background; the test only uses UI Automation and posted messages.
"""

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from wieso_mcp.paths import default_program_year

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "fixtures" / "private" / f"probe.steuer{default_program_year() - 1}"

pytestmark = pytest.mark.wiso


def _value(r):
    if r.is_error:
        raise AssertionError(r.content[0].text)
    sc = r.structured_content
    if isinstance(sc, dict) and set(sc) == {"result"}:
        return sc["result"]
    return sc if sc is not None else json.loads(r.content[0].text)


@pytest.mark.skipif(not PROBE.exists(), reason="no probe working copy")
def test_e2e_stdio_server_enters_row_into_real_wiso(tmp_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "wieso_mcp"],
        env={
            **os.environ,
            "WIESO_MCP_WORKDIR": str(PROBE.parent),
            "WIESO_MCP_AUDIT_DIR": str(tmp_path / "audit"),
        },
    )

    async def go():
        async with Client(params, read_timeout_seconds=300) as c:
            names = [t.name for t in (await c.list_tools()).tools]
            assert "enter_proposal" in names and not [n for n in names if "submit" in n or "send" in n]

            status = _value(await c.call_tool("wiso_status", {}))
            assert status["tax_year"] == 2025

            hits = _value(await c.call_tool("search_fields", {"text": "Arbeitsmittel", "form": "N"}))
            assert any(h["field_id"] == "E0204402" for h in hits)

            r = await c.call_tool("read_return", {})
            if r.is_error:  # WISO only keeps the request XML for a while after 'Prüfen'
                assert "Prüfen" in r.content[0].text
            else:
                assert len(_value(r)["fields"]) > 50

            # writes go to the probe working copy only
            _value(await c.call_tool("open_case", {"case_path": str(PROBE)}))
            _value(await c.call_tool("goto_section", {"label": "Arbeitnehmer"}))
            _value(await c.call_tool("open_card", {"path": "EA[M]\WK0000"}))
            _value(await c.call_tool("open_row", {"var": "wk0_AbschreibugenArbeitsmittel"}))
            _value(await c.call_tool("open_row", {"var": "am1_Arbeitsmaterialien"}))
            before = len([r for r in _value(await c.call_tool("table_rows", {})) if r["description"]])
            label = f"MCP-E2E {before + 1}"
            res = _value(
                await c.call_tool(
                    "add_table_rows",
                    {"rows": [{"description": label, "amount": "7.50", "date": "2025-05-02"}]},
                )
            )
            assert res["rows_written"] == 1
            rows = _value(await c.call_tool("table_rows", {}))
            row = next(r for r in rows if r["description"] == f"02.05.2025 {label}")
            assert Decimal(row["amount"]) == Decimal("7.50")
            for _ in range(3):
                _value(await c.call_tool("ok", {}))
            mtime = PROBE.stat().st_mtime
            _value(await c.call_tool("save_case", {}))
            await anyio.sleep(3)
            assert PROBE.stat().st_mtime > mtime

            refused = await c.call_tool("open_case", {"case_path": str(tmp_path / "Mustermann.steuer2025")})
            assert refused.is_error

            shot = _value(await c.call_tool("screenshot", {"path": str(tmp_path / "e2e.png")}))
            assert Path(shot["path"]).stat().st_size > 10_000
            return tmp_path / "audit" / "audit.jsonl"

    audit = anyio.run(go)
    tools = [json.loads(line)["tool"] for line in audit.read_text("utf-8").splitlines()]
    assert {"open_case", "add_table_row", "ok", "save_case"} <= set(tools)
