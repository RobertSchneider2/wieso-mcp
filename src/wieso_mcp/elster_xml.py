"""Parse the ELSTER E10 request XML that WISO writes on every check/preview."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_FIELD = re.compile(r"^E\d{7}$")
_KINDS = {"validate", "preview", "any"}


class NoRequestFound(FileNotFoundError):
    """No ELSTER request XML in the WISO data folder (run 'Prüfen' in WISO first)."""


@dataclass(frozen=True)
class FieldValue:
    field_id: str
    value: str
    form: str
    context: str
    occurrence: int

    @property
    def key(self) -> str:
        return f"{self.form}/{self.context}/{self.field_id}#{self.occurrence}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["key"] = self.key
        return d


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_request(path: Path) -> list[FieldValue]:
    root = ET.parse(path).getroot()
    e10 = next((e for e in root.iter() if _local(e.tag) == "E10"), None)
    if e10 is None:
        return []
    out: list[FieldValue] = []
    seen: Counter[tuple[str, str, str]] = Counter()

    def walk(el: ET.Element, trail: list[str]) -> None:
        for ch in el:
            name = _local(ch.tag)
            if _FIELD.match(name) and len(ch) == 0:
                form, context = trail[0], "/".join(trail[1:])
                k = (form, context, name)
                out.append(FieldValue(name, (ch.text or "").strip(), form, context, seen[k]))
                seen[k] += 1
            else:
                walk(ch, trail + [name])

    walk(e10, [])
    return out


def diff(old: list[FieldValue], new: list[FieldValue]) -> dict[str, list[Any]]:
    a = {v.key: v for v in old}
    b = {v.key: v for v in new}
    return {
        "added": [b[k] for k in b if k not in a],
        "removed": [a[k] for k in a if k not in b],
        "changed": [
            {"key": k, "field_id": b[k].field_id, "old": a[k].value, "new": b[k].value}
            for k in b
            if k in a and a[k].value != b[k].value
        ],
    }


def latest_request(appdata_dir: Path, kind: str = "any") -> Path:
    if kind not in _KINDS:
        raise ValueError(f"kind must be one of {sorted(_KINDS)}")
    pattern = "btselsterapi_ElsterErklaerung_ESt_{}_request*.xml"
    kinds = ["validate", "preview"] if kind == "any" else [kind]
    files = [f for k in kinds for f in Path(appdata_dir).glob(pattern.format(k))]
    if not files:
        raise NoRequestFound(f"no ESt request XML in {appdata_dir} - run 'Prüfen' in WISO first")
    return max(files, key=lambda f: f.stat().st_mtime)
