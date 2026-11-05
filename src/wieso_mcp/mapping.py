"""Map bank-export categories (Kategorie + Label) to WISO dialogs and ELSTER fields."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from .bank_export import Proposal

DEFAULT_MAPPING = Path(__file__).with_name("mapping.yaml")
PERSONS = frozenset({"stpfl", "ehepartner", "kind", "ask"})
MODES = frozenset({"itemised", "sum"})


class MappingError(ValueError):
    pass


class _Catalog(Protocol):
    def describe(self, field_id: str, vz: int = 2025) -> Any: ...


@dataclass(frozen=True)
class Target:
    category: str
    label: str
    form: str
    dialog_search_term: str
    person: str
    entry_mode: str
    fields: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    ui: dict[str, Any] = field(default_factory=dict)

    def ui_steps(self, person: str) -> dict[str, Any] | None:
        """Navigation recipe for the UI driver; {P} in the card path becomes M (stpfl) or F (ehepartner)."""
        if not self.ui:
            return None
        code = {"stpfl": "M", "ehepartner": "F"}.get(person)
        if code is None:
            raise MappingError(f"person must be 'stpfl' or 'ehepartner' for UI entry, got {person!r}")
        return {
            "section": self.ui["section"],
            "card": str(self.ui["card"]).replace("{P}", code),
            "rows": list(self.ui.get("rows", [])),
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Mapping:
    def __init__(self, targets: list[Target]) -> None:
        self._by_key = {(t.category, t.label): t for t in targets}

    @classmethod
    def load(cls, path: Path = DEFAULT_MAPPING, catalog: _Catalog | None = None, vz: int = 2025) -> Mapping:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        targets: list[Target] = []
        for i, raw in enumerate(data.get("targets", [])):
            try:
                t = Target(
                    category=str(raw["category"]),
                    label=str(raw.get("label") or ""),
                    form=str(raw["form"]),
                    dialog_search_term=str(raw["dialog_search_term"]),
                    person=str(raw["person"]),
                    entry_mode=str(raw["entry_mode"]),
                    fields={str(k): str(v) for k, v in (raw.get("fields") or {}).items()},
                    notes=str(raw.get("notes") or ""),
                    ui=dict(raw.get("ui") or {}),
                )
            except KeyError as exc:
                raise MappingError(f"target #{i}: missing key {exc}") from exc
            if t.person not in PERSONS:
                raise MappingError(f"target #{i}: invalid person {t.person!r}")
            if t.entry_mode not in MODES:
                raise MappingError(f"target #{i}: invalid entry_mode {t.entry_mode!r}")
            if catalog is not None:
                for fid in t.fields.values():
                    if catalog.describe(fid, vz=vz) is None:
                        raise MappingError(f"target #{i}: unknown ELSTER field {fid} for VZ {vz}")
            targets.append(t)
        return cls(targets)

    def target_for(self, category: str, label: str) -> Target | None:
        return self._by_key.get((category, label))

    def apply(self, proposals: list[Proposal]) -> list[Proposal]:
        """Attach targets in place; return proposals that have no target."""
        unmapped = []
        for p in proposals:
            t = self.target_for(p.category, p.label)
            p.target = t.to_dict() if t else None
            if t is None:
                unmapped.append(p)
        return unmapped
