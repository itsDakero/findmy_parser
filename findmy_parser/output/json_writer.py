"""JSON output: one object per location fix, same fields as the CSV rows."""

from __future__ import annotations

import json
from pathlib import Path

from ..discovery import DiscoveryResult
from . import iter_rows


def write_json(result: DiscoveryResult, path: Path) -> None:
    rows = list(iter_rows(result))
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(rows, fp, indent=2, sort_keys=True)
        fp.write("\n")
