from decimal import Decimal
from pathlib import Path

import pytest

from wieso_mcp.bank_export import Proposal
from wieso_mcp.catalog import FieldCatalog
from wieso_mcp.mapping import DEFAULT_MAPPING, Mapping, MappingError, Target
from wieso_mcp.paths import WisoPaths

YAML = """
targets:
  - category: Werbungskosten
    label: Arbeitsmittel
    form: N
    dialog_search_term: Arbeitsmittel
    person: ask
    entry_mode: itemised
    fields: {label: E0204401, amount: E0204402, sum: E0204403}
  - category: Sonderausgaben
    label: Spenden
    form: SA
    dialog_search_term: Spenden
    person: stpfl
    entry_mode: sum
    fields: {sum: E0108105}
"""


class FakeCatalog:
    known = {"E0204401", "E0204402", "E0204403", "E0108105"}

    def describe(self, field_id, vz=2025):
        return object() if field_id in self.known else None


@pytest.fixture
def mfile(tmp_path: Path) -> Path:
    p = tmp_path / "mapping.yaml"
    p.write_text(YAML, encoding="utf-8")
    return p


def test_load_and_lookup(mfile):
    m = Mapping.load(mfile, catalog=FakeCatalog())
    t = m.target_for("Werbungskosten", "Arbeitsmittel")
    assert isinstance(t, Target)
    assert (t.form, t.dialog_search_term, t.person, t.entry_mode) == ("N", "Arbeitsmittel", "ask", "itemised")
    assert t.fields["amount"] == "E0204402"
    assert m.target_for("Werbungskosten", "Unbekannt") is None
    assert m.target_for("Nicht relevant", "") is None


def test_apply_sets_targets_and_reports_unmapped(mfile):
    m = Mapping.load(mfile, catalog=FakeCatalog())
    props = [
        Proposal("Werbungskosten", "Arbeitsmittel", Decimal("10")),
        Proposal("Sonderausgaben", "", Decimal("5")),
    ]
    unmapped = m.apply(props)
    assert props[0].target is not None and props[0].target["fields"]["sum"] == "E0204403"
    assert props[1].target is None
    assert unmapped == [props[1]]


def test_unknown_field_id_rejected(mfile, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(YAML.replace("E0108105", "E9999999"), encoding="utf-8")
    with pytest.raises(MappingError, match="E9999999"):
        Mapping.load(bad, catalog=FakeCatalog())


@pytest.mark.parametrize(("key", "val"), [("person", "nachbar"), ("entry_mode", "magic")])
def test_invalid_enum_rejected(tmp_path, key, val):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        YAML.replace(f"{key}: ask" if key == "person" else f"{key}: itemised", f"{key}: {val}"),
        encoding="utf-8",
    )
    with pytest.raises(MappingError):
        Mapping.load(bad, catalog=FakeCatalog())


def test_packaged_mapping_valid_against_real_catalog():
    with FieldCatalog(WisoPaths.discover().field_catalog) as cat:
        m = Mapping.load(DEFAULT_MAPPING, catalog=cat)
        for label in ("Arbeitsmittel", "Berufsverbände", "Fortbildung", "Homeoffice/Internet", "Fahrtkosten"):
            assert m.target_for("Werbungskosten", label) is not None, label
        for label in ("Versicherung", "Kinderbetreuung", "Spenden"):
            assert m.target_for("Sonderausgaben", label) is not None, label
        for label in ("Handwerker", "Nebenkosten"):
            assert m.target_for("Haushaltsnahe Dienstleistungen", label) is not None, label


def test_ui_recipe_resolves_person_placeholder(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        YAML
        + """    ui:
      section: Arbeitnehmer
      card: 'EA[{P}]\\WK0000'
      rows: [wk0_AbschreibugenArbeitsmittel, am1_Arbeitsmaterialien]
""",
        encoding="utf-8",
    )
    t = Mapping.load(p, catalog=FakeCatalog()).target_for("Sonderausgaben", "Spenden")
    assert t.ui_steps("stpfl") == {
        "section": "Arbeitnehmer",
        "card": "EA[M]\\WK0000",
        "rows": ["wk0_AbschreibugenArbeitsmittel", "am1_Arbeitsmaterialien"],
    }
    assert t.ui_steps("ehepartner")["card"] == "EA[F]\\WK0000"
    with pytest.raises(MappingError):
        t.ui_steps("ask")


def test_target_without_ui_recipe_returns_none(mfile):
    t = Mapping.load(mfile, catalog=FakeCatalog()).target_for("Werbungskosten", "Arbeitsmittel")
    assert t.ui_steps("stpfl") is None


def test_packaged_arbeitsmittel_has_verified_ui_recipe():
    m = Mapping.load(DEFAULT_MAPPING)
    steps = m.target_for("Werbungskosten", "Arbeitsmittel").ui_steps("stpfl")
    assert steps["rows"][-1] == "am1_Arbeitsmaterialien"
