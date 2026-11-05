from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from wieso_mcp.ui.snapshot import Node, filter_inputs, snapshot


@dataclass
class Info:
    control_type: str
    name: str = ""
    automation_id: str = ""
    enabled: bool = True
    rectangle: tuple[int, int, int, int] = (0, 0, 10, 10)


@dataclass
class FakeEl:
    element_info: Info
    kids: list[FakeEl] = field(default_factory=list)
    value: str | None = None

    def children(self):
        return self.kids

    def get_value(self):
        if self.value is None:
            raise AttributeError("no value pattern")
        return self.value


def tree() -> FakeEl:
    return FakeEl(
        Info("Window", "WISO Steuer 2026", "main"),
        [
            FakeEl(
                Info("Group", "", "dlg"),
                [
                    FakeEl(Info("Edit", "Betrag", "dlg.betrag"), value="120,00"),
                    FakeEl(Info("CheckBox", "Pauschale", "dlg.pausch")),
                    FakeEl(Info("Button", "Weiter", "dlg.next")),
                ],
            ),
            FakeEl(Info("ComboBox", "Person", "dlg.person", enabled=False), value="Max"),
        ],
    )


def test_snapshot_walks_tree_with_depth_and_values():
    nodes = snapshot(tree())
    assert [n.control_type for n in nodes] == ["Window", "Group", "Edit", "CheckBox", "Button", "ComboBox"]
    edit = nodes[2]
    assert isinstance(edit, Node)
    assert (edit.name, edit.automation_id, edit.value, edit.depth) == ("Betrag", "dlg.betrag", "120,00", 2)
    assert nodes[3].value is None
    assert nodes[5].enabled is False


def test_snapshot_respects_max_depth():
    nodes = snapshot(tree(), max_depth=1)
    assert [n.control_type for n in nodes] == ["Window", "Group", "ComboBox"]


def test_snapshot_respects_max_nodes():
    assert len(snapshot(tree(), max_nodes=2)) == 2


def test_filter_inputs_keeps_only_input_controls():
    kinds = [n.control_type for n in filter_inputs(snapshot(tree()))]
    assert kinds == ["Edit", "CheckBox", "ComboBox"]


def test_node_to_dict_is_json_ready():
    d = snapshot(tree())[2].to_dict()
    assert d["automation_id"] == "dlg.betrag"
    assert d["rect"] == [0, 0, 10, 10]


def test_broken_child_does_not_abort_snapshot():
    class Boom(FakeEl):
        def children(self):
            raise RuntimeError("COM error")

    root = FakeEl(Info("Window", "w"), [Boom(Info("Group", "bad")), FakeEl(Info("Edit", "ok"))])
    assert [n.name for n in snapshot(root)] == ["w", "bad", "ok"]


@pytest.mark.wiso
def test_real_wiso_window_exposes_named_controls():
    """Real-life: running WISO 2026 (any case open) exposes Qt objectNames as UIA automation ids."""
    from pywinauto import Desktop

    wins = Desktop(backend="uia").windows(class_name="rsWspMainWindow")
    assert wins, "start WISO Steuer 2026 with a case first"
    nodes = snapshot(wins[0], max_nodes=5000)
    ids = [n.automation_id for n in nodes]
    assert any(i.endswith("searchLine.searchEdit") for i in ids)
    assert any("NaviThemeButton" in i for i in ids)
