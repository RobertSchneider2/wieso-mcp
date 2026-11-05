"""Serialise a UI Automation element tree into plain, JSON-ready nodes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

INPUT_TYPES = frozenset({"Edit", "ComboBox", "CheckBox", "RadioButton", "Spinner"})


@dataclass(frozen=True)
class Node:
    control_type: str
    name: str
    automation_id: str
    value: str | None
    enabled: bool
    rect: tuple[int, int, int, int]
    depth: int

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rect"] = list(self.rect)
        return d


def _rect(info: Any) -> tuple[int, int, int, int]:
    r = getattr(info, "rectangle", None)
    if r is None:
        return (0, 0, 0, 0)
    if isinstance(r, tuple):
        return (int(r[0]), int(r[1]), int(r[2]), int(r[3]))
    return (int(r.left), int(r.top), int(r.right), int(r.bottom))


def _value(el: Any) -> str | None:
    getter = getattr(el, "get_value", None)
    if getter is None:
        return None
    try:
        v = getter()
    except Exception:
        return None
    return None if v is None else str(v)


def _node(el: Any, depth: int) -> Node:
    info = el.element_info
    return Node(
        control_type=str(getattr(info, "control_type", "") or ""),
        name=str(getattr(info, "name", "") or ""),
        automation_id=str(getattr(info, "automation_id", "") or ""),
        value=_value(el),
        enabled=bool(getattr(info, "enabled", True)),
        rect=_rect(info),
        depth=depth,
    )


def snapshot(root: Any, max_depth: int = 40, max_nodes: int = 2000) -> list[Node]:
    """Depth-first walk of ``root``; tolerant of COM errors on individual subtrees."""
    out: list[Node] = []
    stack: list[tuple[Any, int]] = [(root, 0)]
    while stack and len(out) < max_nodes:
        el, depth = stack.pop()
        out.append(_node(el, depth))
        if depth >= max_depth:
            continue
        try:
            kids = list(el.children())
        except Exception:
            continue
        stack.extend((k, depth + 1) for k in reversed(kids))
    return out


def filter_inputs(nodes: list[Node]) -> list[Node]:
    return [n for n in nodes if n.control_type in INPUT_TYPES]
