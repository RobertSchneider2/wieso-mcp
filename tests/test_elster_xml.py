import os
import shutil
import time
from pathlib import Path

import pytest

from wieso_mcp.elster_xml import FieldValue, NoRequestFound, diff, latest_request, parse_request
from wieso_mcp.paths import WisoPaths

FIX = Path(__file__).parent / "fixtures" / "est_validate_request.xml"


def test_parse_yields_every_field_leaf():
    vals = parse_request(FIX)
    assert all(isinstance(v, FieldValue) for v in vals)
    ids = [v.field_id for v in vals]
    assert ids == [
        "E0100001",
        "E0100201",
        "E0100301",
        "E0161301",
        "E0161302",
        "E0161301",
        "E0161302",
        "E0161304",
    ]
    name = vals[1]
    assert (name.value, name.form, name.context) == ("Mustermann", "ESt1A", "Allg/A")


def test_repeated_groups_get_occurrence_index():
    vals = [v for v in parse_request(FIX) if v.field_id == "E0161302"]
    assert [(v.value, v.occurrence) for v in vals] == [("350", 0), ("1200", 1)]
    assert vals[1].context == "And_Aufw/Krankh/Einz"


def test_key_is_unique_per_field_occurrence():
    vals = parse_request(FIX)
    assert len({v.key for v in vals}) == len(vals)


def test_diff_reports_added_removed_changed(tmp_path):
    other = tmp_path / "b.xml"
    txt = FIX.read_text(encoding="utf-8").replace(">350<", ">400<").replace("<E0100301>Max</E0100301>", "")
    txt = txt.replace("<Sum>", "<Sum><E0161305>1</E0161305>")
    other.write_text(txt, encoding="utf-8")
    d = diff(parse_request(FIX), parse_request(other))
    assert [v.field_id for v in d["removed"]] == ["E0100301"]
    assert [v.field_id for v in d["added"]] == ["E0161305"]
    assert [(c["old"], c["new"]) for c in d["changed"]] == [("350", "400")]


def test_latest_request_picks_newest(tmp_path):
    a = tmp_path / "btselsterapi_ElsterErklaerung_ESt_validate_request.xml"
    b = tmp_path / "btselsterapi_ElsterErklaerung_ESt_validate_request_3.xml"
    p = tmp_path / "btselsterapi_ElsterErklaerung_ESt_preview_request.xml"
    for f in (a, b, p):
        shutil.copy(FIX, f)
    now = time.time()
    os.utime(a, (now - 100, now - 100))
    os.utime(b, (now - 10, now - 10))
    os.utime(p, (now, now))
    assert latest_request(tmp_path, kind="validate") == b
    assert latest_request(tmp_path, kind="preview") == p
    assert latest_request(tmp_path, kind="any") == p


def test_latest_request_missing_raises(tmp_path):
    with pytest.raises(NoRequestFound):
        latest_request(tmp_path)


def test_bad_kind_rejected(tmp_path):
    with pytest.raises(ValueError):
        latest_request(tmp_path, kind="send")


def test_real_2025_appdata_request_parses():
    """Real-life: last year's program folder holds a real validate request; it must parse."""
    p = WisoPaths.discover(program_year=2025)
    vals = parse_request(latest_request(p.appdata_dir, kind="validate"))
    assert any(v.field_id == "E0100201" for v in vals)
